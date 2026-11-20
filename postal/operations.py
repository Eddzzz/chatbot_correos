"""Operaciones postales que solo utilizan columnas y fuentes autorizadas."""
from itertools import islice
from datetime import date
import re
from .data import DataError
from .geography import normalized_name
import secrets

SERVICES = {
    'EMS': ('paquetes_ems', 'eventos_ems'),
    'CERTIFICADO': ('paquetes_certi', 'eventos_certi'),
    'CONTRATO': ('paquetes_contrato', 'eventos_contrato'),
    'INTERNACIONAL': ('paquetes_int', None),
    'ORDINARIO': ('paquetes_ordi', 'eventos_ordi'),
    'EMS_FORMULARIO': ('paquetes_ems_formulario', None),
}


def _available(catalog):
    return {t['name']: set(t['allowed_columns']) for t in catalog if t.get('queryable')}


def location_count_report(question, catalog, previous=None):
    """Resolve simple destination counts and their geographic comparisons locally."""
    from .ai import _normalize_location_filters
    from .geography import department_for
    import sqlglot
    from sqlglot import exp

    def count_request(text):
        text = ' '.join(normalized_name(text).split()).strip(' ¿?¡!.')
        match = re.fullmatch(
            r'(?:hola[, ]+)?(?:quiero que me digas |dime |dame |muestrame )?'
            r'cuantos (?:paquetes|envios)(?: (ems|certi|certificado|contrato|int|internacional|ordi|ordinario))?'
            r'(?: tengo| hay| tenemos)? en (.+)', text)
        if not match or not department_for(match[2]):
            return None
        service = (match[1] or '').upper()
        service = {'CERTI': 'CERTIFICADO', 'INT': 'INTERNACIONAL', 'ORDI': 'ORDINARIO'}.get(service, service)
        return department_for(match[2]), [name for name in SERVICES
            if name != 'EMS_FORMULARIO' and (not service or name == service)]

    request = ' '.join(normalized_name(question).split()).strip(' ¿?¡!.')
    comparison = re.fullmatch(r'(?:puedes )?compar(?:a|ar)(?: la carga| los paquetes| los envios)? con (.+)', request)
    target = None
    if comparison:
        if previous is None or not department_for(comparison[1]):
            return None
        target = department_for(comparison[1])
        filters = previous.filters
        if filters.get('Criterio') == 'Destino (cobertura departamental)':
            base = (filters['Destino base'], filters['Servicios'])
        else:
            base = count_request(previous.question)
            if base:
                from .context import compress_context
                from .policy import QueryRejected, validate_ai_sql
                compact = compress_context(question, {'sql': previous.sql, 'report_panels': previous.panels},
                                           normalize_location_sql=_normalize_location_filters)
                if not compact.get('sql'):
                    return None
                def same_location(node):
                    if isinstance(node, exp.Paren):
                        return same_location(node.this)
                    if isinstance(node, exp.Or):
                        return same_location(node.this) and same_location(node.expression)
                    if not isinstance(node, exp.EQ):
                        return False
                    field, value = node.this, node.expression
                    return (isinstance(field, exp.Column) and field.name in ('ciudad', 'cuidad', 'destino', 'origen')
                            and isinstance(value, exp.Literal) and value.is_string
                            and department_for(value.this) == base[0])
                # Only migrate simple legacy counts; never discard dates, states or other filters.
                for panel in compact.get('report_panels') or [{'sql': compact['sql']}]:
                    try:
                        tree, _ = validate_ai_sql(panel.get('sql', compact['sql']))
                    except QueryRejected:
                        return None
                    if (not isinstance(tree, exp.Select) or len(tree.expressions) != 1
                            or not isinstance(tree.expressions[0].unalias(), exp.Count)
                            or any(tree.args.get(key) for key in ('group', 'having', 'limit', 'offset', 'joins'))
                            or tree.find(exp.Subquery) or tree.args.get('with_')
                            or not tree.args.get('where')):
                        return None
                    counted = tree.expressions[0].unalias().this
                    if not (isinstance(counted, exp.Star) or isinstance(counted, exp.Column) and counted.name == 'id'):
                        return None
                    if not same_location(tree.args['where'].this):
                        return None
                # Legacy AI reports are recomputed with the same destination criterion.
                names = [name for name in base[1] if SERVICES[name][0] in previous.source_tables]
                base = (base[0], names)
    else:
        base = count_request(question)
    if not base or not base[1]:
        return None
    place, services = base
    available = _available(catalog)
    fields = {'EMS': 'ciudad', 'CERTIFICADO': 'cuidad', 'CONTRATO': 'destino',
              'INTERNACIONAL': 'destino', 'ORDINARIO': 'ciudad'}
    if any(not {'id', fields[name]} <= available.get(SERVICES[name][0], set()) for name in services):
        return None
    filters = {'Criterio': 'Destino (cobertura departamental)', 'Destino base': place, 'Servicios': services}
    queries = []
    for name in services:
        def count(location):
            normalized = _normalize_location_filters(
                f'SELECT COUNT(p.id) AS total_envios FROM assistant.{SERVICES[name][0]} p '
                f'WHERE p.{fields[name]} = {exp.Literal.string(location).sql(dialect="postgres")}')
            predicate = sqlglot.parse_one(normalized, read='postgres').args['where'].this
            # Factor the repeated location expression to keep large departments within the SQL size limit.
            def location_column(node):
                if (isinstance(node, exp.Lower) and isinstance(node.this, exp.Trim)
                        and isinstance(node.this.this, exp.Column)
                        and node.this.this.table == 'p' and node.this.this.name == fields[name]):
                    return exp.column('ubicacion', table='p')
                return node
            predicate = predicate.transform(location_column).sql(dialect='postgres')
            return (f'SELECT COUNT(p.id) AS total_envios FROM '
                    f'(SELECT id, LOWER(TRIM({fields[name]})) AS ubicacion '
                    f'FROM assistant.{SERVICES[name][0]}) p WHERE {predicate}')
        sql = count(place)
        if target:
            left = exp.to_identifier(normalized_name(place).replace(' ', '_'), quoted=True).sql()
            right_name = normalized_name(target).replace(' ', '_')
            if target == place:
                right_name += '_comparado'
            right = exp.to_identifier(right_name, quoted=True).sql()
            sql = (f'SELECT a.total_envios AS {left}, b.total_envios AS {right} '
                   f'FROM ({sql}) a CROSS JOIN ({count(target)}) b')
        queries.append({'title': name, 'sql': sql, 'filters': filters, 'chart': None})
    title = f'Paquetes con destino a {place.title()}'
    if target:
        title = f'Comparación de paquetes: {place.title()} y {target.title()}'
    return {'intent': 'report', 'title': title, 'queries': queries,
            'answer': 'Conteos por servicio según el destino registrado, con cobertura departamental. '
                      'Todos los servicios usan el mismo criterio de destino; los totales se recalculan '
                      'desde el respaldo y no indican la ubicación física actual de los paquetes.'}


def package_sample(question, catalog, source, cancellation, context_questions=()):
    """Select an existing package record without requiring an AI generation."""
    request = ' '.join(normalized_name(question).split()).strip(' ¿?¡!.')
    short = ('aleatorio', 'al azar', 'cualquiera', 'uno aleatorio')
    if request in short:
        request = next((text for question in reversed(context_questions)
                        if (text := ' '.join(normalized_name(question).split()).strip(' ¿?¡!.')) not in short), '')
        if not request:
            return None
    match = re.fullmatch(
        r'(?:dame|dime|muestrame|muestra|necesito|quiero) (?:un|algun|cualquier) '
        r'(?:codigo|numero de guia) de (?:un )?(?:paquete|envio)'
        r'(?: (?:del? servicio )?(ems|certi|certificado|contrato|int|internacional|ordi|ordinario))?'
        r'(?: (?:aleatorio|al azar|cualquiera|real|existente))?', request)
    if not match:
        return None
    service = {'CERTI': 'CERTIFICADO', 'INT': 'INTERNACIONAL', 'ORDI': 'ORDINARIO'}.get(
        (match[1] or '').upper(), (match[1] or '').upper())
    available = _available(catalog)
    choices = [(name, table) for name, (table, _) in SERVICES.items()
               if name != 'EMS_FORMULARIO' and (not service or name == service)
               and {'id', 'codigo'} <= available.get(table, set())]
    if not choices:
        raise DataError('unavailable', 'No hay fuentes autorizadas de códigos de paquete para ese servicio.')
    counts = []
    for name, table in choices:
        with source.stream(f"SELECT COUNT(*) AS total FROM assistant.{table} "
                           "WHERE codigo IS NOT NULL AND TRIM(codigo) <> ''", cancellation=cancellation) as stream:
            counts.append(int(next(stream.rows)['total']))
    total = sum(counts)
    offset = secrets.randbelow(total) if total else 0
    selected = choices[0]
    for choice, count in zip(choices, counts):
        if offset < count:
            selected = choice
            break
        offset -= count
    name, table = selected
    return {'intent': 'answer', 'title': 'Código de paquete existente' if total else 'Sin códigos disponibles',
            'answer': (f'Código seleccionado al azar de los registros existentes del servicio {name}.' if total
                       else 'No se encontraron paquetes con códigos no vacíos en los servicios autorizados.'),
            'queries': [{'title': 'Código de paquete existente',
                         'sql': f"SELECT '{name}' AS servicio, codigo FROM assistant.{table} "
                                "WHERE codigo IS NOT NULL AND TRIM(codigo) <> '' ORDER BY id LIMIT 1 OFFSET %s",
                         'params': [offset], 'filters': {'Servicio': name, 'Selección': 'Aleatoria'}}]}


def movement_report(question, catalog, context_questions=()):
    """Count dated history events once, using only verified package/branch associations."""
    request = ' '.join(question.casefold().split()).rstrip('.!?')

    def grouped(text):
        return (re.search(r'\bmovimientos?\b', text, re.I) and re.search(r'\bpaquetes?\b', text, re.I)
                and re.search(r'\bpor\s+departamentos?\b', text, re.I))

    months = ('enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre')
    def service_change(text):
        return re.fullmatch(r'(?:ahora )?(?:solo|solamente) (?:ems|certi|certificado|contrato|ordi|ordinario|int|internacional)(?:[,;]?\s+(?:mant[eé]n|conserva).*)?', text)

    def month_change(text):
        return re.fullmatch(r'cambia(?: (?:[uú]nicamente|solo))? el mes a (' + '|'.join(months) + r')(?:[;,]\s*conserva.*)?', text)

    def continuation(text):
        return (re.fullmatch(r'(?:(?:de|del)\s+)?(?:a[ñn]o\s+)?[12]\d{3}|todo|todos|todos los datos|movimientos? de paquetes|m[aá]s detalles', text)
                or service_change(text) or month_change(text))

    modifiers = []
    if grouped(request):
        root = request
    elif continuation(request):
        history = [' '.join(text.casefold().split()).rstrip('.!?') for text in context_questions]
        root_index = next((index for index in reversed(range(len(history))) if grouped(history[index])), None)
        if root_index is None:
            return None
        root, modifiers = history[root_index], [*history[root_index + 1:], request]
        if not all(continuation(text) for text in modifiers):
            return None
    else:
        return None
    if not root or re.search(r'\b(?:solo|solamente|[uú]nicamente|exclusivamente)\b.*\b(?:mis|m[ií]os|hice|registr[eé])\b', root):
        return None
    service_request = next((text for text in reversed(modifiers) if service_change(text)), root)
    for text in modifiers:
        change = month_change(text)
        if change:
            root = re.sub(r'(primera\s+semana\s+de\s+)\w+', lambda match: match[1] + change[1], root)
    week = re.search(r'\bprimera\s+semana\s+de\s+(\w+)\b', root)
    if not week or week[1] not in months:
        return None
    year = next((match[0] for text in reversed([*context_questions, question])
                 if (match := re.search(r'\b[12]\d{3}\b', text))), None)
    if not year:
        raise DataError('clarification', f'¿De qué año necesitas la primera semana de {week[1]}?')
    start, end = date(int(year), months.index(week[1]) + 1, 1), date(int(year), months.index(week[1]) + 1, 8)
    available = _available(catalog)
    relations = {table['name']: table.get('relations', []) for table in catalog}

    def linked(table, column, target):
        return any(not relation.get('inferred') and relation['column'] == column and relation['table'] == target
                   and relation['target'] == 'id' for relation in relations.get(table, []))

    service_patterns = {'EMS': r'\bems\b', 'CERTIFICADO': r'\b(?:certi|certificado)\b',
                        'CONTRATO': r'\bcontrato\b', 'ORDINARIO': r'\b(?:ordi|ordinario)\b',
                        'INTERNACIONAL': r'\b(?:int|internacional)\b'}
    requested = [name for name, pattern in service_patterns.items() if re.search(pattern, service_request)]
    families, unavailable = [], []
    for service, (packages, events) in SERVICES.items():
        if service == 'EMS_FORMULARIO' or requested and service not in requested:
            continue
        if not events or not {'id', 'codigo', 'created_at'} <= available.get(events, set()):
            if packages in available:
                unavailable.append(service)
            continue
        branch = ('user_id' in available.get(packages, set()) and {'id', 'sucursal_id'} <= available.get('users', set())
                  and {'id', 'departamento'} <= available.get('sucursales', set())
                  and linked(packages, 'user_id', 'users') and linked('users', 'sucursal_id', 'sucursales'))
        families.append((service, packages if 'codigo' in available.get(packages, set()) else None, events, branch))
    if not families:
        raise DataError('unavailable', 'No hay historial de movimientos autorizado para los servicios solicitados.')

    def query(selected):
        packages_sql, events_sql = [], []
        for service, packages, events, branch in selected:
            if packages:
                department = "COALESCE(NULLIF(TRIM(s.departamento), ''), 'Sin departamento')" if branch else "'Sin departamento'"
                joins = ' LEFT JOIN assistant.users u ON p.user_id = u.id LEFT JOIN assistant.sucursales s ON u.sucursal_id = s.id' if branch else ''
                packages_sql.append(f"SELECT '{service}' AS servicio, p.codigo, {department} AS departamento FROM assistant.{packages} p{joins}")
            events_sql.append(f"SELECT '{service}' AS servicio, e.codigo FROM assistant.{events} e WHERE e.created_at >= %s AND e.created_at < %s")
        # One association per service/code prevents duplicate package rows multiplying events.
        destination_ctes = ("paquetes AS (" + ' UNION ALL '.join(packages_sql) + "), "
            "asociaciones AS (SELECT servicio, codigo, CASE WHEN COUNT(DISTINCT departamento) = 1 THEN MIN(departamento) "
            "ELSE 'Sin departamento' END AS departamento FROM paquetes GROUP BY servicio, codigo), ") if packages_sql else ''
        department = "COALESCE(a.departamento, 'Sin departamento')" if packages_sql else "'Sin departamento'"
        association_join = ' LEFT JOIN asociaciones a ON m.servicio = a.servicio AND m.codigo = a.codigo' if packages_sql else ''
        sql = ("WITH " + destination_ctes + "movimientos AS (" + ' UNION ALL '.join(events_sql) + "), "
               f"conteos AS (SELECT m.servicio, {department} AS departamento, COUNT(*) AS total_movimientos, "
               "COUNT(DISTINCT NULLIF(TRIM(m.codigo), '')) AS codigos_con_movimientos FROM movimientos m" + association_join +
               f" GROUP BY m.servicio, {department}) "
               "SELECT departamento, CAST(SUM(total_movimientos) AS BIGINT) AS total_movimientos, "
               "CAST(SUM(codigos_con_movimientos) AS BIGINT) AS codigos_con_movimientos "
               "FROM conteos GROUP BY departamento ORDER BY total_movimientos DESC, departamento")
        return {'sql': sql, 'params': [value for _ in selected for value in (start.isoformat(), end.isoformat())],
                'chart': {'kind': 'bar', 'label_column': 'departamento', 'value_column': 'total_movimientos', 'label': 'Movimientos'},
                'filters': {'Inicio': start.isoformat(), 'Fin exclusivo': end.isoformat(), 'Fecha': 'Fecha del evento'}}

    queries = [{'title': 'Total de movimientos por departamento', **query(families)}]
    queries.extend({'title': f'Movimientos {service} por departamento', **query([family])}
                   for family in families for service in [family[0]])
    note = ('Cada movimiento es un evento del historial ocurrido en el periodo. El departamento corresponde a la sucursal '
            'asociada al paquete; si falta sucursal o departamento, o la asociación por código es ambigua, se muestra «Sin departamento». '
            'La ciudad y el destino no se usan para deducirlo.')
    if unavailable:
        note += ' Sin historial de movimientos disponible: ' + ', '.join(unavailable) + '.'
    return {'intent': 'report', 'title': f'Movimientos de paquetes por departamento · 1 al 7 de {week[1]} de {year}',
            'answer': f'Se cuentan los eventos registrados del 1 al 7 de {week[1]} de {year}, no los registros de paquetes.',
            'note': note, 'queries': queries}


def service_status_report(question, catalog, *, previous_dashboard=False):
    request = ' '.join(question.casefold().split()).rstrip('.!?')
    branch = re.fullmatch(r'(?:de )?(?:la )?sucu(?:rs|r)al (?:de )?([^\W\d_]+(?: [^\W\d_]+){0,7})', request) if previous_dashboard else None
    if previous_dashboard and not branch:
        return None
    municipality = branch[1] if branch else None
    is_dashboard = bool(municipality) or request == 'crea un dashboard con envíos por servicio, por estado y su evolución mensual'
    if request == 'resume los envíos por servicio postal':
        totals = dashboard_plan('envios_por_servicio', catalog, include_ems_forms=False)
        totals['filters'] = {'Periodo': 'Todo el respaldo', 'Exclusión': 'Formularios asociados a EMS'}
        return {'intent': 'summary', 'title': 'Resumen de envíos por servicio', 'queries': [totals],
                'answer': 'El conteo agrupa los registros de todo el respaldo por familia postal. Los formularios asociados a EMS se excluyen para evitar doble conteo.'}
    if not is_dashboard and request not in (
        'genera un reporte de envíos por servicio y por estado, con sus fuentes y filtros',
        'genera un reporte de envíos por servicio y por estado',
    ):
        return None

    available = _available(catalog)
    totals, states, dates = [], [], []
    relations = {item['name']: item.get('relations', []) for item in catalog}

    def linked(table, field, target):
        return any(r['column'] == field and r['table'] == target and r['target'] == 'id' for r in relations.get(table, []))

    if municipality and not ('sucursal_id' in available.get('users', set())
                             and 'municipio' in available.get('sucursales', set())
                             and linked('users', 'sucursal_id', 'sucursales')):
        raise DataError('unavailable', 'No hay una relación autorizada entre usuarios y sucursales.')
    for service, (table, _) in SERVICES.items():
        if service == 'EMS_FORMULARIO' or table not in available:
            continue
        source = f'FROM assistant.{table} p'
        where = ''
        if municipality:
            if 'user_id' not in available[table] or not linked(table, 'user_id', 'users'):
                continue
            source += ' JOIN assistant.users u ON p.user_id = u.id JOIN assistant.sucursales s ON u.sucursal_id = s.id'
            where = ' WHERE LOWER(TRIM(s.municipio)) = %s'
        field = next((name for name in ('estado_id', 'estados_id', 'fk_estado') if name in available[table]), None)
        totals.append(f"SELECT '{service}' AS servicio, COUNT(*) AS cantidad {source}{where}")
        if 'created_at' in available[table]:
            dates.append(f'SELECT p.created_at {source}{where}')
        if not field:
            states.append(f"SELECT '{service}' AS servicio, NULL AS estado_id, 'Campo no disponible' AS estado, COUNT(*) AS cantidad {source}{where}")
            continue
        has_state_link = {'id', 'nombre_estado'} <= available.get('estados', set()) and linked(table, field, 'estados')
        label = "COALESCE(e.nombre_estado, 'Sin nombre registrado')" if has_state_link else "'ID sin equivalencia verificada'"
        join = f' LEFT JOIN assistant.estados e ON p.{field} = e.id' if has_state_link else ''
        group = f'p.{field}, e.nombre_estado' if has_state_link else f'p.{field}'
        states.append(f"SELECT '{service}' AS servicio, p.{field} AS estado_id, {label} AS estado, COUNT(*) AS cantidad {source}{join}{where} GROUP BY {group}")
    if not totals:
        raise DataError('unavailable', 'No hay fuentes autorizadas de envíos.')

    filters = {'Periodo': 'Todo el respaldo', 'Fecha, sucursal y estado': 'Sin filtro',
               'Exclusión': 'Formularios EMS, por su relación con envíos EMS'}
    if municipality:
        filters = {'Periodo': 'Todo el respaldo', 'Municipio de la sucursal': municipality.title(),
                   'Vínculo': 'Sucursal del usuario asociado al envío', 'Fecha y estado': 'Sin filtro'}
    service_totals = {'title': 'Total por servicio', 'filters': filters,
                      'sql': ' UNION ALL '.join(totals) + ' ORDER BY cantidad DESC',
                      'chart': {'kind': 'bar', 'label_column': 'servicio', 'value_column': 'cantidad', 'label': 'Envíos'}}
    if is_dashboard:
        by_state = {
            'title': 'Envíos por estado', 'filters': filters,
            'sql': 'SELECT estado, SUM(cantidad) AS cantidad FROM (' + ' UNION ALL '.join(states) + ') datos GROUP BY estado ORDER BY cantidad DESC',
            'chart': {'kind': 'bar', 'label_column': 'estado', 'value_column': 'cantidad', 'label': 'Envíos'},
        }
        monthly = dashboard_plan('evolucion_mensual', catalog, include_ems_forms=False)
        monthly['filters'] = {**filters, 'Fecha de registro': 'Se requiere una fecha registrada'}
        answer = 'El dashboard cubre todo el respaldo histórico. Los estados internacionales sin equivalencia confirmada se agrupan aparte. La evolución mensual cuenta los envíos por fecha de registro.'
        if municipality:
            service_totals['params'] = [municipality] * len(totals)
            by_state['params'] = [municipality] * len(states)
            monthly['sql'] = "SELECT DATE_TRUNC('month', created_at) AS mes, COUNT(*) AS cantidad FROM (" + ' UNION ALL '.join(dates) + ") datos WHERE created_at IS NOT NULL GROUP BY DATE_TRUNC('month', created_at) ORDER BY mes"
            monthly['params'] = [municipality] * len(dates)
            answer = f'El filtro usa el municipio {municipality.title()} de la sucursal del usuario asociado al envío. Se incluyen los servicios con esa relación declarada y los registros que se pudieron vincular a una sucursal. La evolución mensual usa la fecha de registro.'
        return {'intent': 'dashboard', 'title': 'Dashboard de envíos',
                'answer': answer,
                'queries': [service_totals, by_state, monthly]}
    return {
        'intent': 'report', 'title': 'Envíos por servicio y por estado',
        'answer': 'Se cuenta una fila por envío registrado en cada familia postal. Los estados corresponden al respaldo histórico. El servicio internacional conserva su identificador de estado porque el catálogo no declara su equivalencia con la tabla de estados.',
        'queries': [
            service_totals,
            {'title': 'Desglose por servicio y estado', 'filters': filters,
             'sql': ' UNION ALL '.join(states) + ' ORDER BY servicio, cantidad DESC, estado_id'},
        ],
    }


def validate_tracking_codes(codes):
    if not isinstance(codes, list) or not 1 <= len(codes) <= 6:
        raise DataError('invalid_input', 'Introduzca entre uno y seis códigos de envío.')
    result = []
    for code in codes:
        if (not isinstance(code, str) or not code.strip() or len(code) > 100
                or not re.fullmatch(r'[A-Za-z0-9._ /-]+', code)):
            raise DataError('invalid_input', 'Cada código debe tener hasta 100 caracteres y usar letras, números, espacios, punto, guion o barra.')
        if code.strip() not in result:
            result.append(code.strip())
    return result


def tracking_question(question):
    match = re.fullmatch(r'(?:rastrea|rastrear|rastree)\s+(?:(?:los?\s+)?(?:c[oó]digos?|env[ií]os?|paquetes?)\s*:?\s*)?(.+)',
                         question.strip().rstrip('.'), re.I | re.S)
    if not match:
        return None
    raw = match[1].strip()
    # Leave natural-language questions to the planner; recognize explicit code lists only.
    if not re.fullmatch(r'[A-Za-z0-9._ /,;\s-]+', raw) or not any(char.isdigit() for char in raw):
        return None
    codes = re.split(r'[,;\n]+', raw) if re.search(r'[,;\n]', raw) else raw.split()
    if any(not any(char.isdigit() for char in code) for code in codes):
        return None
    return validate_tracking_codes(codes)


def tracking_report(codes, service, source, cancellation):
    codes = validate_tracking_codes(codes)
    return {'intent': 'report', 'title': 'Rastreo de varios envíos',
            'answer': 'Cada panel corresponde a un código. Los códigos ambiguos requieren precisar el servicio; '
                      'los códigos sin coincidencias se indican por separado. El rastreo es histórico, no en tiempo real.',
            'queries': [tracking_plan(code, service, source, cancellation) for code in codes]}


def tracking_plan(code, service, source, cancellation):
    available = _available(source.catalog())
    families = [(name, table, events) for name, (table, events) in SERVICES.items()
                if table in available and {'id', 'codigo', 'created_at'} <= available[table]
                and (service is None or name == service)]
    if not families:
        raise DataError('unavailable', 'El servicio solicitado no tiene datos de rastreo autorizados.')
    candidates_sql = ' UNION ALL '.join(
        f"SELECT '{name}' AS servicio, codigo, id AS registro_id, created_at AS fecha_registro FROM assistant.{table} WHERE codigo = %s"
        for name, table, _ in families)
    params = [code] * len(families)
    with source.stream(candidates_sql, params, cancellation) as stream:
        candidates = list(islice(stream.rows, 2))
    base = {'sql': candidates_sql, 'title': f'Rastreo: {code}', 'params': params,
            'filters': {'codigo': code, 'servicio': service}, 'chart': None,
            'answer': 'No se encontraron envíos con ese código en las fuentes autorizadas del respaldo.'}
    if len(candidates) > 1:
        base['filters']['choose_service'] = True
        base['answer'] = 'El código tiene varios registros. Elija un servicio para precisar el rastreo. Si se repite dentro del mismo servicio, no se atribuyen movimientos a un registro específico sin una relación verificable.'
        return base
    if not candidates:
        return base
    selected = candidates[0]['servicio']
    _, events = SERVICES[selected]
    table = SERVICES[selected][0]
    sql = f"SELECT '{selected}' AS servicio, codigo, created_at AS fecha, 'Registro del envío' AS movimiento FROM assistant.{table} WHERE codigo = %s"
    params = [code]
    note = 'Estado histórico del respaldo; no es seguimiento en tiempo real.'
    if events in available and 'eventos' in available:
        sql += f" UNION ALL SELECT '{selected}' AS servicio, e.codigo, e.created_at AS fecha, v.nombre_evento AS movimiento FROM assistant.{events} e JOIN assistant.eventos v ON v.id = e.evento_id WHERE e.codigo = %s"
        params.append(code)
        note += ' Los movimientos se asocian por código dentro del servicio; el esquema no declara una clave foránea entre evento y paquete.'
    else:
        note += ' Este servicio no dispone de una relación autorizada de movimientos.'
    base.update(sql=sql + ' ORDER BY fecha', params=params, answer=note,
                filters={'codigo': code, 'servicio': selected, 'historico': True})
    return base


def dashboard_plan(metric, catalog, *, include_ems_forms=True):
    available = _available(catalog)
    families = [(name, table) for name, (table, _) in SERVICES.items()
                if table in available and (include_ems_forms or name != 'EMS_FORMULARIO')]
    if metric == 'sucursales_por_departamento':
        if 'sucursales' not in available:
            raise DataError('unavailable', 'No hay una fuente autorizada de sucursales.')
        return {'sql': 'SELECT departamento, COUNT(*) AS cantidad FROM assistant.sucursales GROUP BY departamento ORDER BY cantidad DESC',
                'title': 'Sucursales por departamento', 'filters': {},
                'chart': {'kind': 'bar', 'label_column': 'departamento', 'value_column': 'cantidad', 'label': 'Sucursales'}}
    if not families:
        raise DataError('unavailable', 'No hay fuentes autorizadas de envíos.')
    if metric == 'envios_por_servicio':
        sql = ' UNION ALL '.join(f"SELECT '{name}' AS servicio, COUNT(*) AS cantidad FROM assistant.{table}" for name, table in families)
        title, label, kind = 'Envíos por servicio', 'servicio', 'bar'
    elif metric == 'envios_por_estado':
        parts = []
        for _, table in families:
            field = next((f for f in ('estado_id', 'estados_id', 'fk_estado') if f in available[table]), None)
            if field:
                parts.append(f"SELECT COALESCE(CAST({field} AS TEXT), 'Sin estado') AS estado FROM assistant.{table}")
        if not parts:
            raise DataError('unavailable', 'No existen campos de estado compatibles.')
        sql = 'SELECT estado, COUNT(*) AS cantidad FROM (' + ' UNION ALL '.join(parts) + ') datos GROUP BY estado ORDER BY cantidad DESC'
        title, label, kind = 'Envíos por identificador de estado', 'estado', 'bar'
    elif metric == 'evolucion_mensual':
        parts = [f'SELECT created_at FROM assistant.{table}' for _, table in families if 'created_at' in available[table]]
        if not parts:
            raise DataError('unavailable', 'No hay fechas compatibles para una evolución temporal.')
        sql = "SELECT DATE_TRUNC('month', created_at) AS mes, COUNT(*) AS cantidad FROM (" + ' UNION ALL '.join(parts) + ") datos WHERE created_at IS NOT NULL GROUP BY DATE_TRUNC('month', created_at) ORDER BY mes"
        title, label, kind = 'Envíos registrados por mes', 'mes', 'line'
    else:
        raise DataError('invalid_metric', 'Seleccione una métrica disponible.')
    return {'sql': sql, 'title': title, 'filters': {'metrica': metric},
            'chart': {'kind': kind, 'label_column': label, 'value_column': 'cantidad', 'label': 'Envíos'}}
