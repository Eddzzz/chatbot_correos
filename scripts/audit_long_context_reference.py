"""Independent read-only queries for the nine-question conversation audit."""
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from django.core.serializers.json import DjangoJSONEncoder
from postal.data import get_source
from postal.geography import coverage, normalized_name

source = get_source()
reference = {'method': 'Read-only SQL independent of model plans; destination membership counted in Python using the configured geographic catalog', 'queries': {}}


def read(name, sql, params=(), store=True):
    with source.stream(sql, params) as result:
        rows = list(result.rows)
    reference['queries'][name] = {'sql': sql, 'params': params, 'row_count': len(rows)}
    if store:
        reference['queries'][name]['rows'] = rows
    return rows


certificates = read('certificados_agosto_septiembre',
    'SELECT id, codigo, cuidad, peso, tipo, fk_estado, servicio_id, created_at, updated_at FROM assistant.paquetes_certi WHERE created_at >= %s AND created_at < %s ORDER BY id',
    ['2026-08-01', '2026-10-01'], store=False)
reference['geography'] = {}
for month in ('08', '09'):
    period = [row for row in certificates if str(row['created_at']).startswith('2026-' + month)]
    for location in ('La Paz', 'Sucre', 'Villa Nube Postal'):
        terms = {normalized_name(name) for name in coverage(location)}
        def belongs(city):
            return any(part in terms for part in re.split(r'\s*-\s*', normalized_name(city or '')))
        selected = [row for row in period if belongs(row['cuidad'])]
        reference['geography'][month + '_' + location] = {
            'total': len(selected), 'by_city': dict(Counter(row['cuidad'] for row in selected)),
            'first_three': selected[:3]}
    service = [row for row in period if row['servicio_id'] == 12]
    reference['queries']['servicio12_' + month] = {
        'method': 'Filter certificados_agosto_septiembre by month and servicio_id=12',
        'total': len(service), 'by_state_id': dict(Counter(str(row['fk_estado']) for row in service)),
        'unassigned_state': sum(row['fk_estado'] is None for row in service)}

read('servicios', 'SELECT id, nombre_servicio FROM assistant.servicio ORDER BY id')
read('estados', 'SELECT id, nombre_estado FROM assistant.estados ORDER BY id')
for code in ('RR000842522BO', 'RT348773815DE', 'UN123369397SE', 'QX999999999ZZ'):
    read('ficha_' + code, 'SELECT id, codigo, cuidad, peso, tipo, fk_estado, servicio_id, created_at, updated_at FROM assistant.paquetes_certi WHERE codigo = %s ORDER BY id', [code])
    read('historial_' + code, 'SELECT ec.codigo, ec.created_at AS fecha_movimiento, e.nombre_evento FROM assistant.eventos_certi ec LEFT JOIN assistant.eventos e ON ec.evento_id = e.id WHERE ec.codigo = %s ORDER BY ec.created_at, ec.id', [code])

for month in ('06', '07', '08'):
    params = ['2026-' + month + '-01', '2026-' + month + '-08']
    read('ems_total_' + month, 'SELECT COUNT(*) AS total_movimientos FROM assistant.eventos_ems WHERE created_at >= %s AND created_at < %s', params)
    read('ems_departamentos_' + month,
         "WITH asociaciones AS (SELECT p.codigo, COUNT(DISTINCT COALESCE(NULLIF(TRIM(s.departamento), ''), 'Sin departamento')) AS grupos, "
         "MIN(COALESCE(NULLIF(TRIM(s.departamento), ''), 'Sin departamento')) AS departamento "
         "FROM assistant.paquetes_ems p LEFT JOIN assistant.users u ON p.user_id = u.id LEFT JOIN assistant.sucursales s ON u.sucursal_id = s.id GROUP BY p.codigo) "
         "SELECT CASE WHEN a.grupos = 1 THEN a.departamento ELSE 'Sin departamento' END AS departamento, COUNT(*) AS total_movimientos "
         "FROM assistant.eventos_ems e LEFT JOIN asociaciones a ON e.codigo = a.codigo WHERE e.created_at >= %s AND e.created_at < %s "
         "GROUP BY CASE WHEN a.grupos = 1 THEN a.departamento ELSE 'Sin departamento' END ORDER BY departamento", params)

for family in ('ems', 'certi', 'contrato', 'ordi'):
    read('todos_servicios_agosto_' + family,
         f'SELECT COUNT(*) AS total_movimientos FROM assistant.eventos_{family} WHERE created_at >= %s AND created_at < %s',
         ['2026-08-01', '2026-08-08'])

read('ordinarios_lapaz_septiembre',
     'SELECT id, codigo, ciudad, created_at FROM assistant.paquetes_ordi WHERE created_at >= %s AND created_at < %s ORDER BY id',
     ['2026-09-01', '2026-10-01'])
out = ROOT / 'output/chat-context-9turns-2026-11-11/reference.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(reference, cls=DjangoJSONEncoder, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'geography_totals': {key: value['total'] for key, value in reference['geography'].items()},
                  'service12': {month: reference['queries']['servicio12_' + month]['total'] for month in ('08', '09')},
                  'ems': {month: reference['queries']['ems_total_' + month]['rows'] for month in ('06', '07', '08')},
                  'reference': str(out)}, ensure_ascii=True))
