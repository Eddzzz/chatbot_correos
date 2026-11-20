"""Real model plans, PostgreSQL execution and independent geographic aggregate checks."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

import postal.ai as ai
from postal.data import get_source
from postal.geography import department_for, normalized_name


CASES = [
    ('todos_tarija_oruro', 'Compara la cantidad de paquetes con destino a Tarija y Oruro en los cinco servicios, sin fechas.',
     ['Tarija', 'Oruro'], None, 'COUNT(*)', ''),
    ('ems_paz_santa_cruz', 'Compara cuántos paquetes EMS tienen destino a La Paz y Santa Cruz, sin fechas.',
     ['La Paz', 'Santa Cruz'], ['paquetes_ems'], 'COUNT(*)', ''),
    ('contrato_cochabamba_potosi', 'Compara los paquetes CONTRATO con destino a Cochabamba y Potosí creados en septiembre de 2026.',
     ['Cochabamba', 'Potosí'], ['paquetes_contrato'], 'COUNT(*)', "p.created_at >= '2026-09-01' AND p.created_at < '2026-10-01'"),
    ('certi_beni_pando', 'Compara los paquetes certificados con destino a Beni y Pando creados del 1 al 7 de junio de 2026, ambos inclusive.',
     ['Beni', 'Pando'], ['paquetes_certi'], 'COUNT(*)', "p.created_at >= '2026-06-01' AND p.created_at < '2026-06-08'"),
    ('ems_tres_departamentos', 'Compara la cantidad de paquetes EMS con destino a Chuquisaca, Tarija y Oruro, sin fechas.',
     ['Chuquisaca', 'Tarija', 'Oruro'], ['paquetes_ems'], 'COUNT(*)', ''),
    ('peso_origen_paz_santa_cruz', 'Compara el peso total registrado de los paquetes EMS con origen en La Paz y Santa Cruz, sin fechas. Usa SUM(peso), no cantidad de paquetes ni destino.',
     ['La Paz', 'Santa Cruz'], ['paquetes_ems'], 'SUM(p.peso)', ''),
    ('continuacion_paz_potosi', 'Ahora compara esa misma carga con Potosí; conserva La Paz, el servicio y el periodo anterior.',
     ['La Paz', 'Potosí'], ['paquetes_ems'], 'COUNT(*)', ''),
]
FIELDS = {'paquetes_ems': 'ciudad', 'paquetes_certi': 'cuidad', 'paquetes_contrato': 'destino',
          'paquetes_int': 'destino', 'paquetes_ordi': 'ciudad'}


def main():
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'output' / ('model-department-comparisons-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    folder.mkdir(parents=True, exist_ok=True)
    source = get_source()
    assert not source.demo, 'This audit requires the PostgreSQL backup.'
    results = json.loads((folder / 'results.json').read_text(encoding='utf-8')) if (folder / 'results.json').exists() else []
    traffic = []
    original_call = ai._call_json
    original_client = ai.httpx.Client
    model_responses = []

    def observe(payload):
        value = original_call(payload)
        model_responses.append(value)
        return value

    def record(response):
        request = json.loads(response.request.content)
        traffic.append({'host': response.request.url.host, 'status': response.status_code,
                        'model': request.get('model'),
                        'limits': {key: value for key, value in response.headers.items()
                                   if key.startswith('x-ratelimit-') or key == 'retry-after'}})

    def client(**kwargs):
        return original_client(**kwargs, event_hooks={'response': [record]})

    for name, question, locations, services, aggregate, dates in CASES:
        if any(row['case'] == name and row['status'] == 'passed' for row in results):
            continue
        start = len(traffic)
        model_responses.clear()
        entry = {'case': name, 'question': question}
        try:
            context = None
            if name == 'continuacion_paz_potosi':
                prior = next(row for row in results if row['case'] == 'ems_paz_santa_cruz' and row['status'] == 'passed')
                raw = prior['model_responses'][-1]
                query = raw.get('queries', [raw])[0]
                context = {'question': prior['question'], 'total_rows': 1,
                           'source_tables': ['paquetes_ems'],
                           'comparison': {**query['comparison'], 'base_sql': query['sql']}}
                entry['context'] = context
            # Route selection and production transport stay real; only observations are added.
            with patch.object(ai, '_call_json', side_effect=observe), patch.object(ai.httpx, 'Client', side_effect=client):
                plan = ai.plan_question(question, context, source.catalog())
            queries = plan.get('queries', [plan])
            expected_services = services or list(FIELDS)
            assert len(queries) == len(expected_services), 'Wrong number of services'
            seen, panels = set(), []
            for query in queries:
                descriptor = query.get('comparison')
                assert descriptor, 'Model did not produce a department comparison'
                assert [department_for(p) for p in descriptor['locations']] == [department_for(p) for p in locations]
                _, tables = ai.validate_ai_sql(query['sql'])
                family = next(table for table in tables if table.startswith('paquetes_'))
                assert family in expected_services and family not in seen, 'Wrong service or duplicate panel'
                seen.add(family)
                with source.stream(query['sql']) as stream:
                    rows = list(stream.rows)
                assert len(rows) == 1
                field = 'origen' if name.startswith('peso_origen') else FIELDS[family]
                expected = {}
                for location in locations:
                    sql = f"SELECT {aggregate} AS total FROM assistant.{family} p WHERE p.{field} = '{location}'"
                    if dates:
                        sql += ' AND ' + dates
                    with source.stream(ai._normalize_location_filters(sql)) as stream:
                        value = next(stream.rows)['total']
                    label = normalized_name(department_for(location)).replace(' ', '_')
                    expected[label] = value
                assert rows[0] == expected, f'Aggregate mismatch: {rows[0]} != {expected}'
                panels.append({'service': family, 'rows': rows, 'independent_expected': expected, 'sql': query['sql']})
            entry.update(status='passed', panels=panels)
        except Exception as exc:
            entry.update(status='blocked' if isinstance(exc, ai.PlanningError) and exc.code in ('provider_busy', 'provider_credit') else 'failed',
                         error_code=getattr(exc, 'code', type(exc).__name__), error=str(exc))
        entry['model_responses'] = list(model_responses)
        entry['traffic'] = traffic[start:]
        results.append(entry)
        (folder / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        print(name, entry['status'], entry.get('error_code', ''), flush=True)
        if entry['status'] == 'blocked':
            break
        # Pace real calls to avoid filling the provider's token window.
        if name != CASES[-1][0]:
            time.sleep(45)
    print('Evidence:', folder, flush=True)
    latest = {row['case']: row for row in results}
    summary = {state: sum(row['status'] == state for row in latest.values()) for state in ('passed', 'failed', 'blocked')}
    lines = ['# Comparaciones departamentales con el modelo real', '',
             'Planificador de producción, transporte HTTP real y respaldo PostgreSQL de solo lectura. '
             'Cada resultado aprobado coincide con consultas independientes del agregado, servicio, fechas y dirección solicitados.', '',
             '| Caso | Último estado |', '|---|---|']
    lines += [f"| {name} | {latest.get(name, {}).get('status', 'pending')} |" for name, *_ in CASES]
    lines += ['', 'Los intentos bloqueados por cuota quedan en results.json y no cuentan como aprobados. '
              'Las respuestas del modelo y los metadatos HTTP se conservan sin claves. '
              'Esta campaña comprueba planes y datos; no comprueba visualmente el navegador ni evalúa la redacción del analista.', '',
              'Resumen de últimos estados: ' + json.dumps(summary, ensure_ascii=False)]
    (folder / 'informe.md').write_text('\n'.join(lines), encoding='utf-8')
    print('Summary:', summary, flush=True)


if __name__ == '__main__':
    main()
