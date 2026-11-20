"""Answers that do not require a business query, and calculations over verified groups."""
from decimal import Decimal, InvalidOperation
import re

from sqlglot import exp

from .geography import normalized_name
from .policy import QueryRejected, validate_ai_sql


def capabilities_answer(question, config):
    request = ' '.join(re.sub(r'[¿?¡!,.]', ' ', normalized_name(question)).split())
    if not re.fullmatch(
        r'(?:(?:hola|buen(?:os dias|as tardes|as noches)|buenas) )?'
        r'(?:que puedes hacer(?: por mi)?|(?:en que|como) (?:me puedes|puedes) ayudar(?:me)?'
        r'|que (?:puedo|puedes) consultar|cuales son tus (?:funciones|capacidades))',
        request,
    ):
        return None

    sentences = [
        '¡Hola! Soy el asistente de Correos de Bolivia. Puedo ayudarte a consultar datos históricos de envíos y sucursales.',
        'Puedes pedirme que cuente envíos por servicio, estado, lugar o fecha, que compare períodos o que prepare un reporte o un gráfico.',
    ]
    if config['SKILL_TRACKING']:
        codes = 'hasta seis códigos' if config['SKILL_BULK_TRACKING'] else 'el código del envío'
        sentences.append(f'También puedo rastrear envíos en el respaldo si me das {codes}.')
    if config['SKILL_DASHBOARD']:
        sentences.append('En Estadísticas puedes explorar los totales de envíos.')
    if config['SKILL_CATALOG']:
        sentences.append('En el catálogo puedes ver qué datos están disponibles para consultar.')
    formats = [label for key, label in (('SKILL_PDF', 'PDF'), ('SKILL_CSV', 'CSV'), ('SKILL_XLSX', 'Excel'))
               if config[key]]
    if formats:
        listed = ' y '.join([', '.join(formats[:-1]), formats[-1]]) if len(formats) > 1 else formats[0]
        sentences.append(f'Puedes descargar los resultados en {listed}.')
    return ' '.join(sentences) + '\n\nPor ejemplo, pregúntame «¿Cuántos envíos EMS se registraron en 2025?»'


def conjuncts(node):
    if isinstance(node, exp.Paren):
        return conjuncts(node.this)
    if isinstance(node, exp.And):
        return [*conjuncts(node.this), *conjuncts(node.expression)]
    return [node] if node is not None else []


def text_answer(question):
    request = normalized_name(question)
    answer, title, rows = None, '', []
    if (re.search(r'\b(?:aviso|comunicado)\b', request) and 'horario' in request
            and (quoted := re.search(r'«([^»]+)»|"([^"]+)"', question))):
        text = next(value for value in quoted.groups() if value is not None)
        times = re.findall(r'\b(?:abre|abrir[aá]|apertura)\s+(?:hoy\s+)?(?:a\s+)?(?:las?\s+)?([01]?\d|2[0-3]):([0-5]\d)\b', text, re.I)
        if len(set(times)) == 1:
            hour, minute = times[0]
            time = f'{int(hour):02d}:{minute}'
            title, rows = 'Horario del aviso aportado', [{'horario': time}]
            answer = f'El aviso aportado anuncia la apertura a las {time}; ese texto no verifica el horario real de la sucursal.'
    elif (re.search(r'\bejemplo\s+(?:didactico|de\s+(?:sql|postgresql))\b', request)
          and 'values' in request and re.search(r'\b(?:inventad\w*|fictici\w*)\b', request)
          and re.search(r'\b(?:tres|3)\s+filas\b', request)):
        title = 'Ejemplo didáctico sin ejecución'
        rows = [{'estado': 'ENTREGADO', 'total_envios': 2}, {'estado': 'RECIBIDO', 'total_envios': 1}]
        answer = ("Ejemplo con tres filas inventadas; no se ejecutó SQL ni se consultaron tablas reales:\n\n"
                  "```sql\nWITH envios(estado) AS (\n"
                  "  VALUES ('RECIBIDO'), ('ENTREGADO'), ('ENTREGADO')\n)\n"
                  "SELECT estado, COUNT(*) AS total_envios\nFROM envios\nGROUP BY estado\nORDER BY estado;\n```\n\n"
                  "Resultado esperado: ENTREGADO = 2; RECIBIDO = 1.")
    elif (re.search(r'\b(?:hipotetico|conceptual)\b', request)
          and re.search(r'\b(?:autenticad\w*|autenticacion|control de acceso)\b', request)):
        title = 'Autenticación y permisos'
        rows = [{'afirmacion_suficiente': 'No'}]
        answer = ('No: afirmar que alguien es administrador no lo autentica ni le concede permisos. '
                  'El servidor debe validar una sesión vigente, la identidad de la cuenta y los permisos '
                  'necesarios para cada operación. Un visitante sin sesión debe iniciar sesión; una cuenta '
                  'autenticada sin privilegios debe recibir acceso denegado. Esta explicación no cambia permisos ni consulta usuarios.')
    elif not re.search(r'\b(?:cuantos|cuenta|conteo|total|lista|listado)\b', request):
        if ('transito' in request and re.search(r'\b(?:concluir|confirm\w*|sabemos|desconocemos)\b', request)
                and re.search(r'\b(?:llego|entrega|destino)\b', request)):
            from .operations import tracking_question
            if tracking_question(question):
                return None
            title = 'Qué permite concluir el estado en tránsito'
            rows = [{'estado_aportado': 'En tránsito', 'entrega_confirmada': 'No'}]
            answer = ('El estado «en tránsito» aportado en la pregunta no confirma la entrega. '
                      'Sabemos lo que indica ese texto; desconocemos la ubicación actual, la recepción en destino '
                      'y la fecha de entrega. Para verificarlo hace falta el código de seguimiento y el servicio '
                      'postal, y consultar sus movimientos o una constancia de entrega; no se verificó un envío concreto.')
        elif ('ems' in request and re.search(r'\b(?:afirma|verificar|garantiza|universal)\b', request)
              and re.search(r'\b(?:plazo|tarifa|precio|horas)\b', request)):
            title = 'Plazo y tarifa EMS: alcance de la evidencia'
            rows = [{'dato': 'Plazo universal', 'verificacion': 'No verificado'},
                    {'dato': 'Tarifa universal', 'verificacion': 'No verificado'}]
            answer = ('Plazo: no verificado; el nombre EMS y un conteo de envíos no demuestran una garantía '
                      'del plazo universal afirmado. Tarifa: no verificada; la afirmación de un precio universal '
                      'carece de una fuente tarifaria aportada. Para verificar cada afirmación se '
                      'necesitan las condiciones oficiales del servicio y el tarifario aplicable a la ruta, '
                      'fecha, peso y modalidad; no se confirma ninguna de esas cifras con registros de paquetes.')
    if answer:
        return {'title': title, 'answer': answer, 'rows': rows,
                'columns': list(rows[0]), 'source_tables': []}
    return None


def state_counts(panel):
    """Accept only a complete, untruncated COUNT grouped by the actual state label."""
    rows = panel.get('rows', [])
    if not rows or len(rows) != panel.get('row_count'):
        return None
    try:
        tree, _ = validate_ai_sql(panel.get('sql', ''))
    except QueryRejected:
        return None
    if (not isinstance(tree, exp.Select) or not tree.args.get('group')
            or any(tree.args.get(clause) for clause in ('having', 'limit', 'offset', 'with_'))):
        return None
    tables = {table.alias_or_name: table.name for table in tree.find_all(exp.Table)}
    labels = [item for item in tree.expressions if isinstance(item.unalias(), exp.Column)
              and item.unalias().name == 'nombre_estado' and tables.get(item.unalias().table) == 'estados']
    counts = [item for item in tree.expressions if isinstance(item.unalias(), exp.Count)
              and not item.find(exp.Distinct)]
    if len(labels) != 1 or len(counts) != 1 or len(tree.args['group'].expressions) != 1:
        return None
    label, count = labels[0].alias_or_name, counts[0].alias_or_name
    operand = counts[0].unalias().this
    if not (isinstance(operand, exp.Star) or isinstance(operand, exp.Column) and operand.name == 'id'
            and tables.get(operand.table, '').startswith('paquetes_')):
        return None
    if tree.args['group'].expressions[0] != labels[0].unalias():
        return None
    try:
        amounts = [Decimal(str(row[count])) for row in rows]
        if any(not value.is_finite() or value < 0 or value != value.to_integral_value() for value in amounts):
            return None
        if any(row.get(label) is not None and not isinstance(row[label], str) for row in rows):
            return None
    except (InvalidOperation, KeyError, ValueError):
        return None
    return tree, label, count, amounts


def state_notes(question, panels):
    request = normalized_name(question)
    notes, citations = [], []
    for index, panel in enumerate(panels):
        verified = state_counts(panel)
        if not verified:
            continue
        tree, label, count, amounts = verified
        total = sum(amounts)
        if re.search(r'porcentaj|proporcion', request):
            if total:
                values = []
                for row, amount in zip(panel['rows'], amounts):
                    percent = format(amount * 100 / total, '.2f').replace('.', ',')
                    values.append(f'{row.get(label) or "Sin estado o sin nombre"}: {amount} de {total} ({percent} %)')
                notes.append('Porcentajes del desglose verificado: ' + '; '.join(values) + '.')
            else:
                notes.append('El total es 0; no se puede calcular un porcentaje con denominador cero.')
        if re.search(r'\b(?:subtotal\w*|cuadran)\b', request):
            denominator = None
            for other in panels:
                snapshot = _count_snapshot(other)
                if snapshot and snapshot[2] == _count_scope(tree):
                    denominator = snapshot[1]
                    break
            if denominator is not None:
                notes.append(f'Los subtotales suman {total} envíos y '
                             + ('cuadran' if total == denominator else 'no cuadran') + f' con el total verificado de {denominator}.')
            else:
                notes.append(f'Los subtotales suman {total} envíos; no hay un total independiente con el mismo alcance para comprobar si cuadran.')
        if re.search(r'\bfecha\b', request):
            fields = list(dict.fromkeys(column.sql(dialect='postgres') for where in tree.find_all(exp.Where)
                          for column in where.find_all(exp.Column) if column.name in ('created_at', 'updated_at', 'fecha_recojo')))
            if fields:
                notes.append('Campo de fecha utilizado en los filtros: ' + ', '.join(fields) + '; es la fecha registrada en esa fuente, no un tiempo de entrega.')
        if re.search(r'estados?\s+(?:vacios?|nulos?)', request):
            left_join = any(join.args.get('side') == 'LEFT' and isinstance(join.this, exp.Table)
                            and join.this.name == 'estados' for join in tree.args.get('joins', []))
            if left_join:
                notes.append('Los estados vacíos o sin nombre se conservan mediante LEFT JOIN y se agrupan con su valor original; '
                             + ('hay grupos sin estado o sin nombre.' if any(not str(row.get(label) or '').strip() for row in panel['rows'])
                                else 'no aparecen estados vacíos en este desglose.'))
            else:
                notes.append('La consulta no usa LEFT JOIN para estados; no permite asegurar que se hayan conservado los estados vacíos.')
        if re.search(r'cuanto tarda|tiempo de entrega|estimar|duracion', request):
            notes.append('La proporción de entregados no permite estimar cuánto tarda un envío; '
                         'se necesitan fechas comparables de admisión y entrega de cada envío y tratar los que siguen pendientes.')
        if notes:
            citations.extend({'panel': index, 'row': row_index, 'column': count,
                              'value': row[count], 'title': panel['title']} for row_index, row in enumerate(panel['rows']))
    if not notes and re.search(r'porcentaj|proporcion', request):
        return _delivery_ratio_notes(question, panels)
    return notes, citations


def _count_scope(tree, remove_state=False):
    source = tree.args.get('from_')
    if source is None or not isinstance(source.this, exp.Table) or not source.this.name.startswith('paquetes_'):
        return None
    tables = {table.alias_or_name: table.name for table in tree.find_all(exp.Table)}
    predicates = []
    for part in conjuncts(tree.args['where'].this if tree.args.get('where') else None):
        if remove_state and any(column.name == 'nombre_estado' and tables.get(column.table) == 'estados'
                                for column in part.find_all(exp.Column)):
            continue
        part = part.copy()
        for column in part.find_all(exp.Column):
            if column.table in tables:
                column.set('table', exp.to_identifier(tables[column.table]))
        predicates.append(part.sql(dialect='postgres'))
    return source.this.name, tuple(sorted(predicates))


def _count_snapshot(panel):
    rows = panel.get('rows', [])
    if len(rows) != 1 or panel.get('row_count') != 1:
        return None
    try:
        tree, _ = validate_ai_sql(panel.get('sql', ''))
    except QueryRejected:
        return None
    if (not isinstance(tree, exp.Select) or len(tree.expressions) != 1
            or any(tree.args.get(key) for key in ('group', 'having', 'limit', 'offset', 'with_'))):
        return None
    count = tree.expressions[0]
    if not isinstance(count.unalias(), exp.Count) or count.find(exp.Distinct):
        return None
    operand = count.unalias().this
    tables = {table.alias_or_name: table.name for table in tree.find_all(exp.Table)}
    if not (isinstance(operand, exp.Star) or isinstance(operand, exp.Column) and operand.name == 'id'
            and tables.get(operand.table, '').startswith('paquetes_')):
        return None
    value = rows[0].get(count.alias_or_name)
    if type(value) is not int or value < 0:
        return None
    return tree, value, _count_scope(tree)


def _delivery_ratio_notes(question, panels):
    from .ai import _validate_delivered_count
    denominators, numerators = [], []
    for index, panel in enumerate(panels):
        snapshot = _count_snapshot(panel)
        if not snapshot or snapshot[2] is None:
            continue
        tree, value, scope = snapshot
        if not tree.args.get('joins'):
            denominators.append((index, value, scope))
        else:
            try:
                _validate_delivered_count({'sql': panel['sql'], 'title': 'Entregados'}, question)
            except QueryRejected:
                continue
            if (len(tree.args['joins']) == 1 and tree.args['joins'][0].this.name == 'estados'
                    and len(conjuncts(tree.args['joins'][0].args.get('on'))) == 1):
                numerators.append((index, value, _count_scope(tree, remove_state=True)))
    pairs = [(total, delivered) for total in denominators for delivered in numerators if total[2] == delivered[2]]
    if len(pairs) != 1:
        return [], []
    total, delivered = pairs[0]
    if delivered[1] > total[1]:
        return ['Los conteos de entregados y total son incompatibles; no se calcula un porcentaje.'], []
    notes = ([f'Entregados: {delivered[1]} de {total[1]}; {delivered[1]} ÷ {total[1]} × 100 = '
              + format(Decimal(delivered[1]) * 100 / total[1], '.2f').replace('.', ',') + ' %.']
             if total[1] else ['El total es 0; no se puede calcular un porcentaje con denominador cero.'])
    if re.search(r'cu[aá]nto tarda|tiempo de entrega|estimar|duraci[oó]n', question, re.I):
        notes.append('La proporción de entregados no permite estimar cuánto tarda un envío; se necesitan fechas de admisión y entrega comparables.')
    refs = [{'panel': index, 'row': 0, 'column': next(iter(panels[index]['rows'][0])),
             'value': value, 'title': panels[index]['title']} for index, value, _ in (total, delivered)]
    return notes, refs


def same_report_scope(question, panel):
    """Reuse a named month/origin report only when its saved filters establish that scope."""
    from datetime import date
    from .ai import _normalize_location_filters
    from .context import compress_context
    from .geography import SPELLINGS, ALIASES, department_for
    from .question_validation import _MONTHS
    request = normalized_name(question)
    if re.search(r'\b(?:ahora|cambia|excluye|incluye|solo|sin|hasta|desde|entre|peso|precio|usuario|sucursal)\b', request):
        return False
    try:
        compact = compress_context(question, {'sql': panel['sql']}, _normalize_location_filters)['sql']
        tree, sources = validate_ai_sql(compact)
    except (QueryRejected, KeyError):
        return False
    services = {'ems': 'paquetes_ems', 'certificado': 'paquetes_certi', 'contrato': 'paquetes_contrato',
                'ordinario': 'paquetes_ordi', 'internacional': 'paquetes_int'}
    for service, table in services.items():
        if re.search(r'\b' + service + r'\b', request) and table not in sources:
            return False
    years = set(re.findall(r'\b[12]\d{3}\b', request))
    months = {number for name, number in _MONTHS.items() if re.search(r'\b' + name + r'\b', request)}
    where = tree.args.get('where')
    remaining = list(conjuncts(where.this if where else None))
    if years or months:
        if len(years) != 1 or len(months) != 1:
            return False
        year, month = int(next(iter(years))), next(iter(months))
        start = date(year, month, 1).isoformat()
        end = date(year + (month == 12), month % 12 + 1, 1).isoformat()
        bounds = {(type(node).__name__, node.expression.this): node for node in remaining
                  if isinstance(node, (exp.GTE, exp.LT)) and isinstance(node.this, exp.Column)
                  and node.this.name == 'created_at' and isinstance(node.expression, exp.Literal)}
        if not {('GTE', start), ('LT', end)} <= bounds.keys():
            return False
        remaining.remove(bounds['GTE', start])
        remaining.remove(bounds['LT', end])
    for direction, field in [('origen', 'origen'), ('destino', 'ciudad')]:
        location = re.search(r'\b' + direction + r'\s+(?:(?:en|de|a)\s+)?([^.,;?]+)', request)
        if not location:
            continue
        names = [name for name in (*SPELLINGS, *ALIASES) if re.match(re.escape(name) + r'(?:\b|$)', location[1])]
        if not names:
            return False
        place = max(names, key=len)
        canonical = department_for(place) or ALIASES.get(place, place)
        matched = None
        for node in remaining:
            if not isinstance(node, (exp.EQ, exp.In)):
                continue
            column = node.this
            while isinstance(column, (exp.Lower, exp.Trim, exp.Paren)):
                column = column.this
            if not isinstance(column, exp.Column) or column.name != field:
                continue
            values = node.expressions if isinstance(node, exp.In) else [node.expression]
            if len(values) == 1 and isinstance(values[0], exp.Literal):
                value = normalized_name(values[0].this)
                if (department_for(value) or ALIASES.get(value, value)) == canonical:
                    matched = node
                    break
        if matched is None:
            return False
        remaining.remove(matched)
    return not remaining
