"""Trabajos locales con evidencia en disco y propiedad de usuario y sesión."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
from itertools import islice
import json
import logging
import math
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import time
import traceback

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import close_old_connections
from django.utils import timezone

from .ai import PlanningError, plan_question, compose_response, verified_explanation, _verification_notes, provider_config
from .answers import capabilities_answer
from .data import Cancellation, DataError, QueryRejected, get_source
from .models import QueryJob
from .operations import (dashboard_plan, movement_report, service_status_report, tracking_plan,
                         tracking_report, tracking_question, package_sample, location_count_report)
from .policy import validate_ai_sql, ai_chart_supported, public_catalog
from .quotas import purge_expired
from .context import advance_state, settled_state, needs_result_rows, explanation_followup
from .question_validation import validate_question, QuestionValidationError
from .system_config import configuration, value, _snapshot, usage_context

PAGE_SIZE = 100
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='postal-query')
_active = {}
_seen = {}
_lock = threading.Lock()
_lease_started = False
_last_cleanup = 0.0
_logger = logging.getLogger(__name__)


def spool_path(job_id):
    folder = Path(settings.RESULT_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (str(job_id) + '.sqlite3')


def expired(job):
    return job.status not in ('queued', 'running') and job.updated_at < timezone.now() - timedelta(hours=settings.RESULT_TTL_HOURS)


def page_rows(job_id, page, panel=0):
    path = spool_path(job_id)
    if not path.exists():
        return []
    if type(panel) is not int or panel < 0 or panel > 5:
        raise DataError('invalid_panel', 'El panel solicitado no existe.')
    table = 'rows' if panel == 0 else f'rows_{panel}'
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as conn:
        return [json.loads(row[0]) for row in conn.execute(
            f'SELECT value FROM {table} WHERE position >= ? AND position < ? ORDER BY position',
            ((page - 1) * PAGE_SIZE, page * PAGE_SIZE))]


def _verified_context(result, question):
    context = {'question': result.question, 'title': result.title, 'response_type': result.response_type,
               'sql': result.sql, 'filters': result.filters,
               'source_tables': result.source_tables, 'total_rows': result.row_count,
               'report_panels': [{key: panel[key] for key in ('title', 'sql', 'filters', 'row_count') if key in panel}
                                 for panel in result.panels]}
    for index, (panel, saved) in enumerate(zip(context['report_panels'], result.panels)):
        chart = saved.get('chart')
        if chart:
            panel['chart'] = chart
            panel['chart_spec'] = saved.get('chart_spec')
            if not panel['chart_spec']:
                # Older saved results predate chart_spec; recover it only from matching verified cells.
                rows = page_rows(result.id, 1, index)
                labels = chart.get('labels', [])
                if rows and len(rows) == len(labels):
                    label = next((column for column in saved.get('columns', []) if
                                  [str(row[column]) if row[column] is not None else 'Sin dato' for row in rows] == labels), None)
                    value = next((column for column in saved.get('columns', []) if
                                  all(isinstance(row[column], (int, float)) and not isinstance(row[column], bool) for row in rows)
                                  and [row[column] for row in rows] == chart.get('values')), None)
                    if label and value:
                        panel['chart_spec'] = {'kind': chart['kind'], 'label_column': label, 'value_column': value,
                                               'label': chart.get('label', value)}
        if saved.get('comparison'):
            panel['comparison'] = saved['comparison']
    if result.panels and result.panels[0].get('comparison'):
        context['comparison'] = result.panels[0]['comparison']
    if needs_result_rows(question):
        context.update(preview_first_page=page_rows(result.id, 1)[:20],
                       preview_is_partial=result.row_count > 20)
    return context


def _safe_chart(spec, rows, row_count):
    if not spec or row_count > PAGE_SIZE:
        return None
    label, value = spec.get('label_column'), spec.get('value_column')
    if not rows or any(label not in row or value not in row for row in rows):
        return None
    values = []
    for row in rows:
        raw = row[value]
        if raw is None or isinstance(raw, bool):
            return None
        try:
            number = float(raw)
        except (ValueError, TypeError, OverflowError):
            return None
        if not math.isfinite(number):
            return None
        values.append(number)
    chart = {'kind': spec.get('kind', 'bar'), 'labels': [str(row[label]) if row[label] is not None else 'Sin dato' for row in rows],
             'values': values, 'label': spec.get('label', value)}
    if 'view' in spec:
        chart['view'] = spec['view']
        if chart['view'] in ('doughnut', 'pie') and (not 2 <= len(values) <= (5 if chart['view'] == 'doughnut' else PAGE_SIZE) or any(v < 0 for v in values) or not 0 < sum(values) < math.inf):
            chart['view'] = 'horizontal'
    return chart


def _catalog_answer(question, catalog):
    from .answers import text_answer
    supplied = text_answer(question)
    if supplied:
        return supplied
    text = question.lower()
    if (re.search(r'qu[eé]\s+(?:significa|es)\s+(?:el\s+)?ems\b|\bexplica(?:me)?\s+(?:el\s+)?ems\b', text)
            and not re.search(r'\b(?:cu[aá]ntos|cuenta|conteo|total)\b', text)):
        return {'title': 'Qué significa EMS', 'rows': [{'servicio': 'EMS', 'significado': 'Express Mail Service'}],
                'columns': ['servicio', 'significado'], 'source_tables': [],
                'answer': 'EMS significa Express Mail Service, un servicio postal expreso internacional para documentos y mercancías '
                          '([EMS Cooperative](https://www.ems.post/en)). '
                          'El nombre del servicio por sí solo no garantiza la entrega mañana; los plazos, tarifas y condiciones '
                          'deben verificarse con Correos de Bolivia.'
                          + (' Ejemplo hipotético: una persona podría usar EMS para enviar documentos al exterior.'
                             if re.search(r'\bejemplo\b', text) else '')}
    if not (re.search(r'\b(campos|columnas|relaciones|catálogo|estructura|esquema)\b', text)
            or re.search(r'cu[aá]ntas\s+tablas', text)
            or re.search(r'\b(explica|explicar|describe|describir)\b.*\btablas?\b', text)):
        return None
    visible = public_catalog(catalog)
    if not value('SKILL_CATALOG'):
        raise DataError('disabled', 'El administrador desactivó el catálogo.')
    mentioned = [table for table in visible if re.search(r'(?<![a-z0-9_])' + re.escape(table['name'].lower()) + r'(?![a-z0-9_])', text)]
    if not mentioned and re.search(r'cu[aá]ntas\s+tablas', text):
        return {'title': 'Catálogo autorizado', 'rows': [{'tablas': len(visible)}], 'columns': ['tablas'],
                'source_tables': ['catálogo autorizado'], 'answer': 'Total de tablas habilitadas para consultas.'}
    if not mentioned:
        raise PlanningError('clarification', 'Indica una tabla del catálogo autorizado para consultar sus campos y relaciones.')
    rows = []
    for table in mentioned:
        for column in table['columns']:
            links = [f"{r.get('table', '')}.{r.get('target', '')}" for r in table.get('relations', []) if r.get('column') == column['name']]
            rows.append({'tabla': table['name'], 'campo': column['name'], 'tipo': column.get('type', ''),
                         'relacion_declarada': ', '.join(links) or 'Sin clave foránea visible en el catálogo'})
    return {'title': 'Estructura: ' + ', '.join(t['name'] for t in mentioned)[:150], 'rows': rows,
            'columns': ['tabla', 'campo', 'tipo', 'relacion_declarada'],
            'source_tables': [t['name'] for t in mentioned],
            'answer': 'Campos autorizados y relaciones entre campos visibles en el catálogo.'}


def _package_type_answer(question, previous, catalog):
    """Explain an observed type without asking the user to define the same code."""
    if previous is None or not previous.sql:
        return None
    request = question.casefold().strip(' ¿?¡!.')
    match = re.fullmatch(r'(?:qu[eé] (?:es|significa)|qu[eé] quiere decir|explica(?:me|r|m[eé])?)\s+(.+)', request)
    if not match:
        return None
    from sqlglot import exp
    try:
        tree, sources = validate_ai_sql(previous.sql)
    except QueryRejected:
        return None
    # Only direct type fields: a derived value or a CTE may have a different meaning.
    if not isinstance(tree, exp.Select):
        return None
    tables = {table.alias_or_name: table.name for table in tree.find_all(exp.Table) if table.db == 'assistant'}
    fields = []
    for projection in tree.expressions:
        column = projection.unalias()
        if not isinstance(column, exp.Column) or column.name not in ('tipo', 'tipo_paquete', 'tipo_correspondencia'):
            continue
        table_name = tables.get(column.table, '')
        if not table_name.startswith('paquetes_'):
            continue
        metadata = next((table for table in catalog if table['name'] == table_name), None)
        if metadata is None or any(relation.get('column') == column.name for relation in metadata.get('relations', [])):
            continue
        fields.append(projection.alias_or_name)
    rows = page_rows(previous.id, 1)
    values = {str(row[field]).strip() for row in rows for field in fields if row.get(field) is not None}
    target = match[1].strip(' "\'')
    selected = [value for value in values if target in (value.casefold(), 'el código ' + value.casefold(), 'el codigo ' + value.casefold())]
    if not selected and target in ('ese tipo', 'ese código', 'ese codigo', 'esa sigla') and previous.row_count <= PAGE_SIZE and len(values) == 1:
        selected = list(values)
    if len(selected) != 1:
        return None
    value = selected[0]
    return {'title': 'Significado del tipo de paquete', 'rows': [{'tipo_paquete': value}],
            'columns': ['tipo_paquete'], 'source_tables': sources,
            'answer': f'«{value}» es el valor registrado en el campo de tipo del paquete consultado. '
                      'El catálogo disponible no documenta su significado ni una equivalencia con un nombre completo. '
                      'Para interpretarlo hace falta el catálogo de tipos o la documentación del sistema postal.'}


def cancel(job_id):
    with _lock:
        token = _active.get(str(job_id))
    if token:
        token.cancel()
    QueryJob.objects.filter(pk=job_id, status__in=['queued', 'running']).update(
        status='cancelled', answer='Consulta cancelada.', updated_at=timezone.now())


def touch(job_id):
    with _lock:
        if str(job_id) in _active:
            _seen[str(job_id)] = time.monotonic()


def reap_abandoned(now=None):
    now = time.monotonic() if now is None else now
    with _lock:
        abandoned = [key for key, seen in _seen.items() if now - seen > 120]
    for key in abandoned:
        cancel(key)


def _lease_loop():
    while True:
        time.sleep(15)
        close_old_connections()
        try:
            reap_abandoned()
            maintain_results()
        except Exception as exc:
            _logger.error('Maintenance failed: %s', type(exc).__name__)
        close_old_connections()


def start_maintenance():
    global _lease_started
    with _lock:
        if not _lease_started:
            _lease_started = True
            threading.Thread(target=_lease_loop, name='postal-presence', daemon=True).start()


def maintain_results(force=False):
    global _last_cleanup
    now = time.monotonic()
    if not force and now - _last_cleanup < 60:
        return
    _last_cleanup = now
    purge_expired()
    from .conversations import purge_trash
    purge_trash()
    cutoff = timezone.now() - timedelta(hours=settings.RESULT_TTL_HOURS)
    for job in QueryJob.objects.exclude(status__in=['queued', 'running']).filter(updated_at__lt=cutoff).iterator():
        try:
            spool_path(job.id).unlink(missing_ok=True)
        except OSError:
            continue
        job.delete()
    # Jobs from a previous server process have no live worker; never report them as running forever.
    with _lock:
        active_ids = list(_active)
    QueryJob.objects.filter(status__in=['queued', 'running'], updated_at__lt=timezone.now() - timedelta(minutes=2)).exclude(pk__in=active_ids).update(
        status='error', error={'code': 'interrupted', 'message': 'El servidor se reinició. Vuelva a ejecutar la consulta.'}, updated_at=timezone.now())


def cancel_session(user_id, session_hash):
    for job_id in QueryJob.objects.filter(user_id=user_id, session_hash=session_hash, status__in=['queued', 'running']).values_list('id', flat=True):
        cancel(job_id)


def submit(job, payload, previous=None):
    global _lease_started
    maintain_results()
    token = Cancellation()
    with _lock:
        if len(_active) >= 8:
            raise DataError('busy', 'Hay varias consultas en curso. Espere o cancele una antes de continuar.')
        _active[str(job.id)] = token
        _seen[str(job.id)] = time.monotonic()
        if not settings.JOBS_EAGER and not _lease_started:
            _lease_started = True
            threading.Thread(target=_lease_loop, name='postal-presence', daemon=True).start()
    if settings.JOBS_EAGER:
        _run(job.id, payload, previous, token)
    else:
        _executor.submit(_run, job.id, payload, previous, token)


def _explain_result(question, intent, evidence):
    try:
        return compose_response(question, intent, evidence)
    except PlanningError as exc:
        return {**verified_explanation(question, evidence),
                'warning': 'El servidor explica los datos verificados. La explicación de IA no está disponible. ' + exc.message}


def _explain_previous_result(job, previous, question, state, token):
    percentage = bool(re.search(r'porcentaj|proporci[oó]n', question, re.I)
                      and re.search(r'retoma|anterior|reporte|resultado', question, re.I)
                      and re.search(r'entregad', question, re.I))
    if percentage:
        from django.db.models import Q
        from .answers import state_counts, same_report_scope
        ids = list(dict.fromkeys([str(previous.id)] if previous else []))
        ids += [item['result_id'] for item in reversed(state.get('results', [])) if item['result_id'] not in ids]
        candidates = {str(candidate.id): candidate for candidate in QueryJob.objects.filter(
            pk__in=ids, user_id=job.user_id, status='ok').filter(
                Q(conversation__isnull=True, session_hash=job.session_hash) |
                Q(conversation__user_id=job.user_id, conversation__deleted_at__isnull=True))}
        matching = None
        for identifier in ids:
            candidate = candidates.get(identifier)
            if candidate is None or expired(candidate):
                continue
            for index, panel in enumerate(candidate.panels):
                if state_counts({**panel, 'rows': page_rows(candidate.id, 1, index)}) and same_report_scope(question, panel):
                    matching = candidate
                    break
            if matching:
                break
        if matching is None:
            return False
        previous = matching
    division = bool(re.search(r'repart|distribu', question, re.I) and
                    re.search(r'\bentre\s+\d+\s+equipos?\b', question, re.I) and
                    re.search(r'anterior|ese total|esos registros', question, re.I))
    if previous is None or previous.status != 'ok' or not (explanation_followup(question) or division or percentage):
        return False
    if expired(previous) or not spool_path(previous.id).is_file():
        raise DataError('stale_context', 'Los datos anteriores vencieron. Repite la consulta antes de pedir la explicación.')
    panels = previous.panels or [{'index': 0, 'title': previous.title, 'columns': previous.columns,
        'source_tables': previous.source_tables, 'filters': previous.filters, 'sql': previous.sql,
        'chart': previous.chart, 'row_count': previous.row_count, 'status': previous.status}]
    evidence = [{**panel, 'rows': page_rows(previous.id, 1, index)} for index, panel in enumerate(panels)]
    token.check()
    if division or percentage:
        notes, citations = _verification_notes(question, evidence)
        if not notes:
            raise PlanningError('clarification', '¿Qué total verificado quieres repartir? Indica un único servicio o resultado.')
        narration = {'answer': '\n\n'.join(notes), 'citations': citations, 'generated': False}
    else:
        narration = _explain_result(question, 'answer', evidence)
    token.check()
    # Retain the exact snapshot for later followups and exports, without another postal query.
    shutil.copyfile(spool_path(previous.id), spool_path(job.id))
    token.check()
    title = 'Explicación de ' + re.sub(r'^Explicación de ', '', previous.title)
    analysis = {**narration, 'presentation': 'explanation', 'generated': narration.get('generated', True)}
    analysis.pop('answer', None)
    QueryJob.objects.filter(pk=job.id, status='running').update(
        status='ok', title=title[:180], answer=narration['answer'], sql=previous.sql,
        columns=previous.columns, source_tables=previous.source_tables, filters=previous.filters,
        chart=previous.chart, row_count=previous.row_count, demo=previous.demo, panels=panels,
        response_type=previous.response_type, analysis=analysis,
        context_state=settled_state(question, job.id, state, panels), updated_at=timezone.now())
    return True


def _validate_branch_locations(sql, source, token):
    """Check branch catalog predicates before treating missing locations as zero parcels."""
    from sqlglot import exp
    from sqlglot.optimizer.scope import traverse_scope
    from .policy import validate_sql
    from .geography import normalized_name, DEPARTMENTS, SPELLINGS, ALIASES
    tree, _ = validate_sql(sql)
    for scope in traverse_scope(tree):
        for predicate in scope.find_all(exp.EQ, exp.In, exp.Like, exp.ILike):
            field = predicate.this
            while isinstance(field, (exp.Lower, exp.Upper, exp.Trim, exp.Paren)):
                field = field.this
            if not isinstance(field, exp.Column) or field.name not in ('municipio', 'departamento'):
                continue
            table = scope.sources.get(field.table)
            if not isinstance(table, exp.Table) or table.name != 'sucursales':
                continue
            values = predicate.expressions if isinstance(predicate, exp.In) else [predicate.expression]
            literals = []
            for value in values:
                while isinstance(value, (exp.Lower, exp.Upper, exp.Trim, exp.Paren)):
                    value = value.this
                if isinstance(value, exp.Literal) and value.is_string:
                    literals.append(value)
            if not literals or len(literals) != len(values):
                continue
            known = DEPARTMENTS if field.name == 'departamento' else SPELLINGS
            pattern = isinstance(predicate, (exp.Like, exp.ILike))
            for value in literals:
                if not pattern and ALIASES.get(normalized_name(value.this), normalized_name(value.this)) in known:
                    continue
                if pattern:
                    condition = predicate.copy()
                    for column in condition.find_all(exp.Column):
                        column.set('table', None)
                else:
                    condition = exp.EQ(this=exp.Lower(this=exp.Trim(this=exp.column(field.name))),
                                       expression=exp.Literal.string(value.this.strip().lower()))
                probe = exp.select(exp.Count(this=exp.Star()).as_('cantidad')).from_('assistant.sucursales').where(condition)
                with source.stream(probe.sql(dialect='postgres'), cancellation=token) as stream:
                    found = next(stream.rows, {}).get('cantidad', 0)
                if not found:
                    raise PlanningError('clarification',
                        'No se reconoce esa ubicación en el catálogo de sucursales: ' + value.this[:250]
                        + '. ¿Puedes corregir el municipio o departamento?')


def _run(job_id, payload, previous, token):
    from .models import AssistantSkill
    snapshot_token = None
    usage_token = None
    conversation_state = payload.get('conversation_state', {})
    if not conversation_state:
        for turn in payload.get('conversation_context', []):
            conversation_state = advance_state(conversation_state, turn['question'], turn.get('clarification'))
    if not settings.JOBS_EAGER:
        close_old_connections()
    try:
        job = QueryJob.objects.get(pk=job_id)
        snapshot = configuration()
        from .provider_catalog import active_connection
        snapshot['MANAGED_CONNECTION'] = active_connection()
        snapshot['CUSTOM_SKILLS'] = list(AssistantSkill.objects.filter(enabled=True).values('preset_key', 'stage', 'instructions'))
        snapshot_token = _snapshot.set(snapshot)
        usage_token = usage_context.set((job.user_id, job.id))
        token.check()
        QueryJob.objects.filter(pk=job_id, status='queued').update(status='running', updated_at=timezone.now())
        if job.kind == 'chat':
            try:
                validate_question(payload['question'])
            except QuestionValidationError as exc:
                raise PlanningError(exc.code, exc.message) from exc
            answer = capabilities_answer(payload['question'], snapshot)
            if answer:
                token.check()
                QueryJob.objects.filter(pk=job_id, status='running').update(
                    status='ok', title='Asistente de Correos de Bolivia', answer=answer,
                    response_type='help', updated_at=timezone.now())
                return
            if re.search(r'\b(?:ah[ií]|all[ií]|all[aá])\b', payload['question'], re.I):
                from sqlglot import exp
                from .policy import validate_sql
                location_known = False
                if previous is not None and previous.sql:
                    tree, _ = validate_sql(previous.sql)
                    location_known = any(column.name in ('ciudad', 'cuidad', 'municipio', 'departamento', 'destino', 'origen')
                                         for where in tree.find_all(exp.Where) for column in where.find_all(exp.Column))
                if not location_known:
                    raise PlanningError('clarification',
                        '¿A qué lugar te refieres y qué periodo quieres consultar? El respaldo histórico no permite confirmar datos en tiempo real.')
            if _explain_previous_result(job, previous, payload['question'], conversation_state, token):
                return
        source = get_source()
        metadata = source.catalog()
        catalog_result = None
        verified_report = None
        if job.kind == 'chat':
            catalog_result = (_catalog_answer(payload['question'], metadata)
                              or _package_type_answer(payload['question'], previous, metadata))
            previous_dashboard = previous is not None and previous.response_type == 'dashboard' and previous.title == 'Dashboard de envíos'
            if not catalog_result:
                context_questions = [turn['question'] for turn in payload.get('conversation_context', [])]
                if conversation_state:
                    context_questions = [
                        *(item['question'] for item in conversation_state.get('results', [])),
                        conversation_state['request'], *conversation_state.get('updates', {}).values(),
                        *conversation_state.get('notes', []),
                        *(turn['question'] for turn in conversation_state.get('recent', [])),
                        *context_questions]
                if previous is not None and previous.question not in context_questions:
                    context_questions.insert(0, previous.question)
                codes = tracking_question(payload['question'])
                if codes:
                    if not snapshot['SKILL_TRACKING'] or len(codes) > 1 and not snapshot['SKILL_BULK_TRACKING']:
                        raise DataError('disabled', 'El administrador desactivó esta capacidad de rastreo.')
                    verified_report = tracking_report(codes, None, source, token)
                else:
                    verified_report = package_sample(payload['question'], metadata, source, token, context_questions)
                if not verified_report:
                    verified_report = movement_report(payload['question'], metadata, context_questions)
            if not catalog_result and not verified_report and (previous is None or previous_dashboard):
                verified_report = service_status_report(payload['question'], metadata, previous_dashboard=previous_dashboard)
            if verified_report:
                spec = verified_report
            elif not catalog_result:
                context = None
                if previous is not None:
                    context = _verified_context(previous, payload['question'])
                if payload.get('conversation_context'):
                    context = {**(context or {}), 'conversation': payload['conversation_context']}
                if conversation_state:
                    context = {**(context or {}), 'state': conversation_state}
                    if re.search(r'\binicial\b|\boriginal(?:es)?\b|\bal principio\b', payload['question'], re.I):
                        origins = conversation_state.get('results', [])
                        if origins and origins[0]['result_id'] != str(getattr(previous, 'id', '')):
                            original = QueryJob.objects.filter(pk=origins[0]['result_id'],
                                user_id=job.user_id, session_hash=job.session_hash).first()
                            if original is None or expired(original):
                                raise DataError('stale_context', 'El resultado original venció. Repita la consulta para recuperar contexto.')
                            context['historical_result'] = _verified_context(original, payload['question'])
                try:
                    spec = plan_question(payload['question'], context, metadata)
                except PlanningError as exc:
                    if exc.code not in ('provider_busy', 'provider_credit', 'missing_api_key'):
                        raise
                    verified_report = location_count_report(payload['question'], metadata, previous)
                    if not verified_report:
                        raise
                    spec = verified_report
                from sqlglot import exp
                queries = spec.get('queries', [spec])
                for query in queries:
                    if verified_report:
                        continue
                    tree, plan_sources = validate_ai_sql(query['sql'])
                    query['filters'] = {'fuentes': plan_sources, 'condiciones': [where.this.sql(dialect='postgres') for where in tree.find_all(exp.Where)]}
                    if query.get('chart') and not ai_chart_supported(query['sql'], query['chart']['label_column'], query['chart']['value_column']):
                        query['chart'] = None
        elif job.kind == 'tracking':
            if 'codes' in payload:
                spec = tracking_report(payload['codes'], payload.get('service'), source, token)
            else:
                spec = tracking_plan(payload['code'], payload.get('service'), source, token)
        elif job.kind == 'dashboard':
            spec = dashboard_plan(payload['metric'], metadata)
        else:
            raise DataError('invalid_operation', 'La operación no está disponible.')
        token.check()
        if catalog_result:
            queries = [catalog_result]
            response_type, title = 'answer', catalog_result['title']
        else:
            queries = spec.get('queries', [spec])
            response_type, title = spec.get('intent', 'answer'), spec['title']
        panels, evidence, all_sources = [], [], []
        path = spool_path(job_id)
        with closing(sqlite3.connect(path)) as spool:
            for index, query in enumerate(queries):
                token.check()
                table = 'rows' if index == 0 else f'rows_{index}'
                spool.execute(f'CREATE TABLE {table} (position INTEGER PRIMARY KEY, value TEXT NOT NULL)')
                count, preview = 0, []
                def save_rows(rows):
                    nonlocal count
                    for row in rows:
                        token.check()
                        encoded = json.dumps(row, cls=DjangoJSONEncoder, ensure_ascii=False, allow_nan=False)
                        spool.execute(f'INSERT INTO {table} VALUES (?, ?)', (count, encoded))
                        if len(preview) < PAGE_SIZE:
                            preview.append(json.loads(encoded))
                        count += 1
                        if count % PAGE_SIZE == 0:
                            spool.commit()
                if catalog_result:
                    save_rows(query['rows'])
                    columns, sources = query['columns'], query['source_tables']
                    answer, filters, sql, chart = query['answer'], {}, '', None
                else:
                    if job.kind == 'chat':
                        _validate_branch_locations(query['sql'], source, token)
                    with source.stream(query['sql'], query.get('params'), token) as stream:
                        if not stream.sources:
                            raise QueryRejected('La consulta debe usar una fuente postal autorizada.')
                        columns, sources = stream.columns, stream.sources
                        save_rows(stream.rows)
                    filters, sql = query.get('filters', {}), query['sql']
                    answer = query.get('answer') or f'Se verificaron {count} filas en las fuentes autorizadas. La tabla muestra una página de hasta {PAGE_SIZE} filas.'
                    if count == 1 and job.kind == 'tracking' and not filters.get('choose_service'):
                        answer += ' Solo hay ficha de registro; no se encontraron movimientos compatibles.'
                    chart = _safe_chart(query.get('chart'), preview, count)
                    if query.get('chart') and not chart and count > PAGE_SIZE:
                        answer += ' El gráfico se omite por la cantidad de categorías; la tabla conserva el resultado completo.'
                status = 'ok' if count else 'no_matches'
                if not count:
                    answer = 'No se encontraron coincidencias con los filtros consultados.'
                    if not catalog_result and len(sources) == 1:
                        with source.stream(f'SELECT 1 AS existe FROM assistant."{sources[0]}" LIMIT 1', cancellation=token) as check:
                            if next(check.rows, None) is None:
                                status, answer = 'empty_table', 'La tabla fuente autorizada está vacía en este respaldo.'
                panel = {'index': index, 'title': query['title'], 'answer': answer, 'status': status,
                         'columns': columns, 'source_tables': sources, 'filters': filters, 'sql': sql,
                         'chart': chart, 'chart_spec': query.get('chart'), 'row_count': count}
                if query.get('comparison'):
                    panel['comparison'] = query['comparison']
                panels.append(panel)
                evidence.append({**panel, 'rows': preview})
                all_sources.extend(name for name in sources if name not in all_sources)
            spool.commit()
        primary = panels[0]
        status = 'ok' if any(panel['row_count'] for panel in panels) else (
            'empty_table' if all(panel['status'] == 'empty_table' for panel in panels) else 'no_matches')
        answer = primary['answer'] if len(panels) == 1 else f'Se verificaron {len(panels)} consultas para este informe. Cada panel indica su origen y alcance.'
        if job.kind == 'tracking' and 'codes' in payload:
            answer = spec['answer']
        analysis = {'generated': False}
        if verified_report:
            answer = verified_report['answer']
            if verified_report.get('note'):
                analysis['note'] = verified_report['note']
        elif job.kind == 'chat' and not catalog_result and status == 'ok':
            token.check()
            narration = (_explain_result(payload['question'], response_type, evidence) if provider_config()[1]
                         else verified_explanation(payload['question'], evidence))
            answer = narration['answer']
            analysis = {'generated': True, **{key: value for key, value in narration.items() if key != 'answer'}}
        if job.kind == 'chat' and status == 'no_matches':
            if (previous is not None and previous.status == 'no_matches'
                    and any(name.startswith('paquetes_') for name in previous.source_tables)
                    and not any(name.startswith('eventos') for name in previous.source_tables)
                    and re.search(r'\bprimer[oa]?\b|(?:ese|mismo) paquete', payload['question'], re.I)):
                title = primary['title'] = 'No hay un paquete identificado'
                answer = 'La consulta anterior no encontró ningún paquete; no hay un paquete identificado para mostrar sus datos o movimientos.'
            elif re.search(r'entregad[oa]|entrega|lleg[oó]|llegada', payload['question'], re.I):
                answer = 'No se encontraron registros que confirmen la entrega solicitada. La ausencia de registros no demuestra que el paquete haya sido entregado.'
            primary['answer'] = answer
        if job.kind == 'chat' and not catalog_result:
            notes, citations = _verification_notes(payload['question'], evidence)
            missing = [note for note in notes if note not in answer]
            if missing:
                answer = '\n\n'.join([*missing, answer])
                analysis.setdefault('citations', []).extend(citations)
            if re.search(r'\b(?:fuente|filtros?)\b', payload['question'], re.I):
                provenance = []
                for panel in panels:
                    sources = ', '.join('assistant.' + name for name in panel['source_tables'])
                    filters = panel['filters']
                    conditions = filters.get('condiciones')
                    description = ('; '.join(conditions) or 'Sin condiciones adicionales; todo el respaldo disponible') if conditions is not None else json.dumps(filters, ensure_ascii=False)
                    provenance.append(f"Fuente de «{panel['title']}»: {sources}. Filtros: {description}. Respaldo histórico, no tiempo real.")
                analysis['provenance'] = provenance
                answer += '\n\nLos resultados corresponden al respaldo histórico y reflejan los filtros de la consulta.'
        token.check()
        QueryJob.objects.filter(pk=job_id, status='running').update(
            status=status, title=title, answer=answer, sql=primary['sql'], columns=primary['columns'], source_tables=all_sources,
            filters=primary['filters'], chart=primary['chart'] or {}, row_count=primary['row_count'], demo=source.demo,
            panels=panels, response_type=response_type, analysis=analysis,
            context_state=settled_state(payload.get('question', ''), job_id, conversation_state, panels), updated_at=timezone.now())
    except (DataError, QueryRejected, PlanningError) as exc:
        status = 'cancelled' if token.cancelled or getattr(exc, 'code', '') == 'cancelled' else 'error'
        if getattr(exc, 'code', '') == 'clarification':
            conversation_state = advance_state(conversation_state, payload.get('question', ''), exc.message)
            if previous is not None:
                conversation_state['result_id'] = str(previous.id)
        QueryJob.objects.filter(pk=job_id, status__in=['queued', 'running']).update(
            status=status, error={'code': exc.code, 'message': exc.message}, answer=exc.message,
            context_state=conversation_state, updated_at=timezone.now())
    except Exception as exc:
        # Do not expose SQL values, provider payloads or connection strings in errors/logs.
        frames = ' -> '.join(f'{Path(frame.filename).name}:{frame.lineno}:{frame.name}'
                             for frame in traceback.extract_tb(exc.__traceback__))
        _logger.error('Query job %s failed: %s at %s', job_id, type(exc).__name__, frames)
        QueryJob.objects.filter(pk=job_id, status__in=['queued', 'running']).update(
            status='error', error={'code': 'execution_error', 'message': 'No se pudo completar la consulta. Revise la configuración o reformule la pregunta.'},
            answer='La consulta falló; no se presentan datos como verificados.', updated_at=timezone.now())
    finally:
        if usage_token is not None:
            usage_context.reset(usage_token)
        if snapshot_token is not None:
            _snapshot.reset(snapshot_token)
        with _lock:
            _active.pop(str(job_id), None)
            _seen.pop(str(job_id), None)
        if not settings.JOBS_EAGER:
            close_old_connections()
