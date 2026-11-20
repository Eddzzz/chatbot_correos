import hashlib
import re
import uuid
from functools import wraps

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.db import transaction
from django.db.models import Q
from django.utils.crypto import constant_time_compare
from django.shortcuts import redirect, render
from django.utils.text import slugify
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from . import jobs
from .data import DataError, DemoSource, get_source
from .models import QueryJob
from .json_validation import load_object
from .operations import SERVICES
from .pdf import render_pdf
from .policy import QueryRejected, public_catalog, validate_sql
from .history import issue_proof, public_result
from .quotas import reserve
from .labels import COLUMN_LABELS, LABEL_WORDS
from .system_config import value as config_value


def error(code, message, status=400):
    return JsonResponse({'error': {'code': code, 'message': message}}, status=status)


def csrf_failure(request, reason=''):
    if request.path.startswith('/api/'):
        return error('csrf', 'La sesión de seguridad cambió. Recargue la página y vuelva a intentar.', 403)
    return HttpResponse('La sesión de seguridad cambió. Recargue la página para volver a ingresar.', status=403)


def session_fingerprint(key):
    return hashlib.sha256((settings.SECRET_KEY + ':' + (key or '')).encode()).hexdigest()


def api_identity(request):
    return session_fingerprint(request.session.session_key)


def rate_error(code, message, wait):
    response = error(code, f'{message} Vuelva a intentar en {wait} s.', 429)
    response['Retry-After'] = str(wait)
    return response


def api_view(method='GET'):
    def decorate(func):
        @wraps(func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return error('authentication_required', 'Inicie sesión para consultar datos.', 401)
            expected_user = request.headers.get('X-Bolipost-User')
            if not expected_user:
                return error('identity_required', 'Recargue la página para vincular la solicitud a su sesión.', 400)
            if not constant_time_compare(expected_user, api_identity(request)):
                return error('identity_changed', 'La cuenta cambió en otra pestaña. Recargue para usar la sesión actual.', 409)
            if request.method != method:
                return error('method_not_allowed', 'Método no permitido.', 405)
            try:
                return func(request, *args, **kwargs)
            except Http404:
                return error('not_found', 'El recurso no existe para esta cuenta.', 404)
            except DataError as exc:
                return error(exc.code, exc.message)
            except RequestDataTooBig:
                return error('request_too_large', 'La solicitud supera el tamaño permitido.', 413)
        return wrapped
    return decorate


def body(request, required, optional=(), maximum=65536):
    if len(request.body) > maximum:
        raise RequestDataTooBig()
    if request.content_type != 'application/json':
        raise DataError('invalid_json', 'Envíe un objeto JSON válido.')
    try:
        value = load_object(request.body)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise DataError('invalid_json', 'El cuerpo JSON no es válido.')
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise DataError('invalid_input', 'Los campos de la solicitud no son válidos.')
    return value


def text(value, maximum, label):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or '\x00' in value:
        raise DataError('invalid_input', f'Introduzca {label} válido, de hasta {maximum} caracteres.')
    return value.strip()


def owned_job(request, job_id):
    job = QueryJob.objects.filter(pk=job_id, user=request.user).filter(
        Q(conversation__isnull=True, session_hash=session_fingerprint(request.session.session_key)) |
        Q(conversation__user=request.user, conversation__deleted_at__isnull=True)).first()
    if job is None:
        return None
    # Old results can still contain fields or catalog metadata from the former policy.
    panels = job.panels or [{'sql': job.sql, 'columns': job.columns}]
    if 'metadatos del respaldo' in job.source_tables:
        return None
    try:
        for panel in panels:
            sql = panel.get('sql')
            if not sql and 'consulta_permitida' in panel.get('columns', ()):
                return None
            if sql:
                validate_sql(sql)
    except QueryRejected:
        return None
    return job


@login_required
@ensure_csrf_cookie
def app(request, chat_id=None):
    return render(request, 'postal/app.html', {'data_mode': config_value('DATA_MODE'),
                  'assistant_skills': {name: config_value('SKILL_' + name.upper()) for name in
                                       ('csv', 'xlsx', 'pdf', 'bulk_tracking')},
                  'column_labels': COLUMN_LABELS, 'label_words': LABEL_WORDS})


@require_POST
def logout_view(request):
    expected = request.POST.get('expected_user')
    if request.user.is_authenticated:
        if not expected or not constant_time_compare(expected, request.api_identity):
            return redirect(settings.LOGIN_URL)
        jobs.cancel_session(request.user.id, session_fingerprint(request.session.session_key))
    logout(request)
    return redirect(settings.LOGIN_URL)


@api_view()
def status_view(request):
    from .ai import provider_config
    provider, key, _, _ = provider_config()
    configured = bool(key) and (provider != 'Cloudflare' or bool(config_value('CLOUDFLARE_ACCOUNT_ID')))
    return JsonResponse({'data_mode': config_value('DATA_MODE'),
        'database_configured': config_value('DATA_MODE') == 'demo' or bool(config_value('BUSINESS_DATABASE_URL')),
        'assistant_configured': configured,
        'skills': {name: config_value('SKILL_' + name.upper()) for name in
                   ('chat', 'tracking', 'dashboard', 'catalog', 'pdf', 'csv', 'xlsx', 'bulk_tracking')}})


@api_view()
def catalog_view(request):
    if not config_value('SKILL_CATALOG'):
        return error('disabled', 'El administrador desactivó el catálogo.', 403)
    return JsonResponse({'tables': public_catalog()})


def create_job(request, kind, payload, previous=None):
    if not config_value('SKILL_' + kind.upper()) or kind == 'chat' and not config_value('PLANNER_ENABLED'):
        return error('disabled', 'El administrador desactivó esta capacidad del asistente.', 403)
    jobs.maintain_results()
    if not request.session.session_key:
        request.session.save()
    fingerprint = session_fingerprint(request.session.session_key)
    conversation = None
    chat_id = payload.pop('chat_id', None)
    if chat_id is not None:
        from .models import Conversation
        conversation = Conversation.objects.filter(pk=chat_id, user=request.user, deleted_at__isnull=True).first()
        if conversation is None:
            return error('not_found', 'La conversación no está disponible.', 404)
    with transaction.atomic():
        wait = reserve(f'query:{kind}', request.user.pk, settings.QUERY_RATE_LIMITS[kind], settings.QUERY_RATE_WINDOW)
        if wait:
            return rate_error('rate_limited', 'Se alcanzó el límite de solicitudes para esta herramienta.', wait)
        if QueryJob.objects.filter(user=request.user, kind=kind, status__in=['queued', 'running']).count() >= settings.QUERY_CONCURRENCY_PER_KIND:
            transaction.set_rollback(True)
            return rate_error('busy', 'Hay consultas en curso en esta herramienta.', 3)
        job = QueryJob.objects.create(user=request.user, session_hash=fingerprint, kind=kind, conversation=conversation,
            question=payload.get('question', payload.get('code', payload.get('metric', ''))), demo=config_value('DATA_MODE') == 'demo')
    try:
        jobs.submit(job, payload, previous)
    except DataError as exc:
        job.delete()
        if exc.code == 'busy':
            return rate_error(exc.code, exc.message, 3)
        raise
    return JsonResponse({'id': str(job.id), 'status': 'queued'}, status=202)


@api_view('POST')
def chat_view(request):
    payload = body(request, ['question'], ['previous_id', 'history_ids', 'chat_id'])
    payload['question'] = text(payload['question'], 4000, 'una pregunta')
    conversation_id = payload.get('chat_id')
    if conversation_id is not None:
        try:
            conversation_id = uuid.UUID(str(conversation_id))
        except (ValueError, TypeError, AttributeError):
            return error('invalid_input', 'La conversación no es válida.')
        payload['chat_id'] = conversation_id
    history_ids = payload.pop('history_ids', [])
    if not isinstance(history_ids, list) or len(history_ids) > 12:
        return error('invalid_context', 'El historial de contexto no es válido.')
    try:
        if any(not isinstance(value, str) or len(value) != 36 for value in history_ids):
            raise ValueError
        history_ids = [uuid.UUID(value) for value in history_ids]
    except (ValueError, TypeError, AttributeError):
        return error('invalid_context', 'El historial de contexto no es válido.')
    if len(set(history_ids)) != len(history_ids):
        return error('invalid_context', 'El historial de contexto no es válido.')
    if 'previous_id' in payload:
        if not isinstance(payload['previous_id'], str) or len(payload['previous_id']) != 36:
            return error('invalid_context', 'El contexto anterior no es válido.')
        try:
            previous_id = uuid.UUID(str(payload['previous_id']))
        except (ValueError, TypeError, AttributeError):
            return error('invalid_context', 'El contexto anterior no es válido.')
        history_ids = [value for value in history_ids if value != previous_id] + [previous_id]
    if len(history_ids) > 12:
        return error('invalid_context', 'El historial de contexto no es válido.')
    history = []
    for context_id in history_ids:
        item = owned_job(request, context_id)
        if item is None:
            return error('stale_context', 'El resultado anterior ya no pertenece a esta sesión. Repita la consulta para recuperar contexto.', 404)
        if conversation_id is not None and item.conversation_id != conversation_id:
            return error('invalid_context', 'El contexto pertenece a otra conversación.')
        if item.response_type == 'help':
            continue
        if jobs.expired(item):
            return error('stale_context', 'El resultado anterior venció. Repita la consulta para recuperar contexto.', 404)
        if item.status not in ('ok', 'no_matches', 'empty_table') and not (item.status == 'error' and item.error.get('code') == 'clarification'):
            return error('invalid_context', 'La consulta anterior no tiene un resultado ni una aclaración pendiente.')
        history.append(item)
    previous = next((item for item in reversed(history) if item.status in ('ok', 'no_matches', 'empty_table')), None)
    if history:
        payload['conversation_context'] = [{'question': item.question,
            **({'clarification': item.error['message']} if item.status == 'error' else {})} for item in history]
        payload['conversation_state'] = history[-1].context_state
        # A clarification-only continuation still needs its last verified result.
        result_id = history[-1].context_state.get('result_id')
        if result_id and (previous is None or str(previous.id) != result_id):
            referenced = owned_job(request, result_id)
            if referenced is None or jobs.expired(referenced):
                return error('stale_context', 'El resultado anterior venció. Repita la consulta para recuperar contexto.', 404)
            if conversation_id is not None and referenced.conversation_id != conversation_id:
                return error('invalid_context', 'El contexto pertenece a otra conversación.')
            previous = referenced
    return create_job(request, 'chat', payload, previous)


@api_view('POST')
def tracking_view(request):
    from .operations import validate_tracking_codes
    payload = body(request, [], ['code', 'codes', 'service'])
    if ('code' in payload) == ('codes' in payload):
        return error('invalid_input', 'Envíe un código o una lista de códigos.')
    if 'codes' in payload:
        payload['codes'] = validate_tracking_codes(payload['codes'])
        if not config_value('SKILL_BULK_TRACKING'):
            return error('disabled', 'El administrador desactivó el rastreo por lotes.', 403)
    else:
        payload['code'] = validate_tracking_codes([payload['code']])[0]
    if payload.get('service') in ('', None):
        payload.pop('service', None)
    elif not isinstance(payload['service'], str) or payload['service'] not in SERVICES:
        return error('invalid_service', 'Seleccione un servicio disponible.')
    return create_job(request, 'tracking', payload)


@api_view('POST')
def dashboard_view(request):
    payload = body(request, ['metric'])
    if payload['metric'] not in ('envios_por_servicio', 'envios_por_estado', 'evolucion_mensual', 'sucursales_por_departamento'):
        return error('invalid_metric', 'Seleccione una métrica disponible.')
    return create_job(request, 'dashboard', payload)


def _name_branches(panels, source):
    candidates = [(panel, column) for panel in panels if 'sucursales' in panel.get('source_tables', [])
                  and 'nombre_sucursal' not in panel['columns']
                  for column in panel['columns'] if column in ('sucursal_codigo', 'codigo_sucursal', 'codigoSucursal')]
    if not candidates:
        return
    names, points = {}, {}
    with source.stream('SELECT "codigoSucursal", "puntoVenta", municipio FROM assistant.sucursales') as stream:
        for branch in stream.rows:
            name = str(branch['municipio'] or '').strip()
            if name:
                code, point = str(branch['codigoSucursal']), str(branch['puntoVenta'])
                names.setdefault(code, set()).add(name)
                points.setdefault((code, point), set()).add(name)
    for panel, column in candidates:
        original_labels = ['Sin dato' if row[column] is None else str(row[column]) for row in panel['rows']]
        rows = []
        for row in panel['rows']:
            code = str(row[column])
            point_column = next((key for key in ('punto_venta', 'puntoVenta') if key in row), None)
            matches = points.get((code, str(row[point_column])), set()) if point_column else names.get(code, set())
            name = next(iter(matches)) if len(matches) == 1 else f'Sucursal sin nombre (código {code})'
            rows.append({('nombre_sucursal' if key == column else key): (name if key == column else value)
                         for key, value in row.items()})
        panel['columns'] = ['nombre_sucursal' if key == column else key for key in panel['columns']]
        panel['rows'] = rows
        chart = panel.get('chart')
        if chart and chart.get('labels') == original_labels:
            panel['chart'] = {**chart, 'labels': [row['nombre_sucursal'] for row in rows]}


def result_data(job, page, panel_index=0, panel_pages=None):
    metadata = job.panels or [{'index': 0, 'title': job.title, 'answer': job.answer, 'columns': job.columns,
        'row_count': job.row_count, 'source_tables': job.source_tables, 'sql': job.sql, 'filters': job.filters,
        'chart': job.chart or None, 'status': job.status}]
    if panel_index < 0 or panel_index >= len(metadata):
        raise DataError('invalid_panel', 'El panel solicitado no existe.')
    pages = {panel_index: page, **(panel_pages or {})}
    if any(index < 0 or index >= len(metadata) for index in pages):
        raise DataError('invalid_panel', 'El panel solicitado no existe.')
    panels = []
    ready = job.status in ('ok', 'no_matches', 'empty_table')
    for index, panel in enumerate(metadata):
        current_page = pages.get(index, 1)
        if current_page < 1 or current_page > max(1, (panel['row_count'] + jobs.PAGE_SIZE - 1) // jobs.PAGE_SIZE):
            raise DataError('invalid_page', 'La página solicitada no existe.')
        rows = jobs.page_rows(job.id, current_page, index) if ready else []
        panels.append({**panel, 'page': current_page, 'rows': rows,
                       'has_more': current_page * jobs.PAGE_SIZE < panel['row_count']})
    if ready and any(set(panel['columns']) & {'sucursal_codigo', 'codigo_sucursal', 'codigoSucursal'} for panel in panels):
        source = DemoSource() if job.demo else get_source()
        if source.demo == job.demo:
            _name_branches(panels, source)
    selected = panels[panel_index]
    return {**selected, 'id': str(job.id), 'status': job.status,
        'title': job.title if panel_index == 0 else selected['title'],
        'primary_title': selected['title'], 'answer': job.answer if panel_index == 0 else selected.get('answer', ''),
        'source_tables': job.source_tables if panel_index == 0 else selected['source_tables'],
        'error': job.error or None, 'created_at': job.created_at.isoformat(), 'demo': job.demo,
        'response_type': job.response_type if panel_index == 0 else 'answer',
        'analysis': job.analysis if panel_index == 0 else {}, 'panels': panels if panel_index == 0 else [],
        'panel_index': panel_index}


def get_panel(request):
    try:
        value = int(request.GET.get('panel', '0'))
    except (ValueError, TypeError):
        raise DataError('invalid_panel', 'El panel debe ser un número entero válido.')
    if not 0 <= value <= 5:
        raise DataError('invalid_panel', 'El panel solicitado no existe.')
    return value


def get_panel_pages(request):
    raw = request.GET.get('panel_pages')
    if not raw:
        return None
    if len(raw) > 150 or 'panel' in request.GET:
        raise DataError('invalid_page', 'La selección de páginas del informe no es válida.')
    pages = {}
    for item in raw.split(','):
        if not re.fullmatch(r'[0-5]:[1-9][0-9]{0,11}', item):
            raise DataError('invalid_page', 'La selección de páginas del informe no es válida.')
        index, page = map(int, item.split(':'))
        if index in pages:
            raise DataError('invalid_page', 'No se puede repetir un panel en la selección.')
        pages[index] = page
    return pages


def get_page(request):
    try:
        value = int(request.GET.get('page', '1'))
    except (ValueError, TypeError):
        raise DataError('invalid_page', 'La página debe ser un número entero positivo.')
    if value < 1 or value > 2**40:
        raise DataError('invalid_page', 'La página no es válida.')
    return value


@api_view()
def result_view(request, job_id):
    job = owned_job(request, job_id)
    if job is None:
        return error('not_found', 'El resultado no existe en esta sesión.', 404)
    if jobs.expired(job):
        jobs.cancel(job.id)
        return error('expired', 'El resultado venció. Vuelva a ejecutar la consulta.', 410)
    jobs.touch(job.id)
    page, panel, pages = get_page(request), get_panel(request), get_panel_pages(request)
    result = result_data(job, page, panel, pages)
    public = public_result(result)
    if not request.user.is_superuser:
        result = public
    if (job.kind == 'chat' and job.conversation_id and job.status not in ('queued', 'running')
            and page == 1 and panel == 0 and not pages):
        result['history_proof'] = issue_proof(job, public)
    return JsonResponse(result)


@api_view('POST')
def cancel_view(request, job_id):
    job = owned_job(request, job_id)
    if job is None:
        return error('not_found', 'El resultado no existe en esta sesión.', 404)
    jobs.cancel(job.id)
    job.refresh_from_db()
    return JsonResponse({'id': str(job.id), 'status': job.status})


@api_view()
def pdf_view(request, job_id):
    if not config_value('SKILL_PDF'):
        return error('disabled', 'El administrador desactivó la exportación PDF.', 403)
    job = owned_job(request, job_id)
    if job is None:
        return error('not_found', 'El resultado no existe en esta sesión.', 404)
    if jobs.expired(job):
        return error('expired', 'El resultado venció. Vuelva a consultar antes de exportar.', 410)
    if job.response_type == 'help' or job.status not in ('ok', 'no_matches', 'empty_table'):
        return error('result_not_ready', 'Espere un resultado verificado para exportarlo.')
    result = result_data(job, get_page(request), get_panel(request), get_panel_pages(request))
    if not request.user.is_superuser:
        result = public_result(result)
    response = HttpResponse(render_pdf(result), content_type='application/pdf')
    title = slugify(result['title'])[:90].strip('-') or 'reporte'
    response['Content-Disposition'] = f'attachment; filename="bolipost-{title}-{job.created_at:%Y-%m-%d}.pdf"'
    return response


@api_view()
def export_view(request, job_id, extension):
    from .exports import export_file
    if not config_value('SKILL_' + extension.upper()):
        return error('disabled', 'El administrador desactivó esta exportación.', 403)
    job = owned_job(request, job_id)
    if job is None:
        return error('not_found', 'El resultado no existe en esta sesión.', 404)
    if jobs.expired(job):
        return error('expired', 'El resultado venció. Vuelva a consultar antes de exportar.', 410)
    if job.response_type == 'help' or job.status not in ('ok', 'no_matches', 'empty_table'):
        return error('result_not_ready', 'Espere un resultado verificado para exportarlo.')
    panels = job.panels or [{'index': 0, 'title': job.title, 'columns': job.columns, 'row_count': job.row_count}]
    index = get_panel(request)
    if index >= len(panels):
        return error('invalid_panel', 'El panel solicitado no existe.')
    if extension == 'csv' or 'panel' in request.GET:
        panels = [panels[index]]
    title = slugify(job.title)[:90].strip('-') or 'reporte'
    return export_file(job, panels, extension, f'bolipost-{title}-{job.created_at:%Y-%m-%d}.{extension}')
