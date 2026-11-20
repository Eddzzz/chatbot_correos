"""Exercise each saved skill through the running chat UI and real read-only PostgreSQL."""
import json
import os
import re
from pathlib import Path
import sys
import time
import argparse
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.contrib.auth import get_user_model, SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from django.utils import timezone
from django.db import close_old_connections
from postal.data import get_source
from postal.models import AssistantSkill, QueryJob, AIUsage
from playwright.sync_api import sync_playwright, expect

BASE = 'http://127.0.0.1:8000'
OUT = ROOT / '.runtime/qa/system-skills/real-chat'
CASES = [
    ('statistics', 'Estadística descriptiva',
     'Calcula la estadística descriptiva de todos los paquetes EMS sin filtros de fecha: número de registros, peso promedio, peso mínimo y peso máximo. Devuelve esos cuatro valores calculados sobre todos los registros, no sobre una muestra; no incluyas otras métricas.',
     'SELECT COUNT(*) AS total, AVG(peso) AS promedio, MIN(peso) AS minimo, MAX(peso) AS maximo FROM assistant.paquetes_ems', None),
    ('trends', 'Tendencias en el tiempo',
     'Muestra la evolución mensual del número de paquetes EMS desde el 1 de junio de 2026 inclusive hasta el 1 de octubre de 2026 exclusivo. Incluye una tabla con mes y cantidad, orden cronológico y una gráfica de líneas. No atribuyas causas.',
     "SELECT DATE_TRUNC('month', created_at) AS mes, COUNT(*) AS cantidad FROM assistant.paquetes_ems WHERE created_at >= '2026-06-01' AND created_at < '2026-10-01' GROUP BY DATE_TRUNC('month', created_at) ORDER BY mes", 'line'),
    ('comparisons', 'Comparaciones por servicio',
     'Compara el número total de registros de paquetes EMS y certificado, sin filtros de fecha. Cuenta cada servicio por separado en su propia tabla y devuelve servicio y cantidad. No mezcles eventos con paquetes.',
     "SELECT 'EMS' AS servicio, COUNT(*) AS cantidad FROM assistant.paquetes_ems UNION ALL SELECT 'Certificado' AS servicio, COUNT(*) AS cantidad FROM assistant.paquetes_certi", None),
    ('rankings', 'Rankings y concentración',
     'Dame las cinco ciudades con más paquetes EMS registrados, sin filtros de fecha, incluyendo ciudad nula si la hubiera. Agrupa por el campo ciudad tal como está guardado, sin unir sucursales; muestra ciudad y cantidad. Ordena cantidad descendente y ciudad ascendente en caso de empate. No calcules porcentajes.',
     'SELECT ciudad, COUNT(*) AS cantidad FROM assistant.paquetes_ems GROUP BY ciudad ORDER BY cantidad DESC, ciudad ASC LIMIT 5', None),
    ('percentages', 'Distribuciones y porcentajes',
     'Distribuye todos los paquetes EMS por estado_id, sin filtros de fecha. Devuelve estado_id, cantidad y porcentaje sobre el total completo de paquetes EMS, incluyendo los estados nulos. Redondea el porcentaje a dos decimales. No unas otras tablas ni excluyas categorías.',
     'SELECT estado_id, COUNT(*) AS cantidad, ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM assistant.paquetes_ems), 2) AS porcentaje FROM assistant.paquetes_ems GROUP BY estado_id ORDER BY estado_id', None),
    ('charts', 'Gráficas de barras y líneas',
     'Haz una gráfica de barras y su tabla del número de paquetes EMS por estado_id, sin filtros de fecha. Agrupa directamente por estado_id, incluyendo nulos; no unas otras tablas ni mezcles eventos. La métrica es cantidad de registros.',
     'SELECT estado_id, COUNT(*) AS cantidad FROM assistant.paquetes_ems GROUP BY estado_id ORDER BY estado_id', 'bar'),
    ('outliers', 'Variaciones y valores atípicos',
     'Analiza variaciones inusuales en el volumen mensual de paquetes EMS desde el 1 de junio de 2026 inclusive hasta el 1 de octubre de 2026 exclusivo. Primero presenta la tabla de los cuatro meses con mes y cantidad. Identifica el mes de mayor y menor volumen según esa tabla. Explica que un extremo observado no demuestra una anomalía estadística ni su causa; no inventes umbrales ni pronósticos.',
     "SELECT DATE_TRUNC('month', created_at) AS mes, COUNT(*) AS cantidad FROM assistant.paquetes_ems WHERE created_at >= '2026-06-01' AND created_at < '2026-10-01' GROUP BY DATE_TRUNC('month', created_at) ORDER BY mes", None),
    ('data-quality', 'Calidad y cobertura de datos',
     'Revisa la calidad de todos los paquetes EMS sin filtros de fecha. Devuelve una fila con total de registros y los conteos de valores NULL de peso, ciudad y codigo, usando respectivamente los alias total, peso_nulo, ciudad_nula y codigo_nulo. Cuenta solo NULL, no cadenas vacías ni ceros. No devuelvas códigos individuales, no alteres datos y no interpretes los nulos como cero.',
     'SELECT COUNT(*) AS total, SUM(CASE WHEN peso IS NULL THEN 1 ELSE 0 END) AS peso_nulo, SUM(CASE WHEN ciudad IS NULL THEN 1 ELSE 0 END) AS ciudad_nula, SUM(CASE WHEN codigo IS NULL THEN 1 ELSE 0 END) AS codigo_nulo FROM assistant.paquetes_ems', None),
]


def database_call(function):
    # Playwright owns an event loop on the main thread; keep Django ORM off it.
    def run():
        try:
            return function()
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(run).result()


def normalized(value):
    if isinstance(value, (int, float, Decimal)):
        return round(float(value), 2)
    if hasattr(value, 'isoformat'):
        return value.isoformat()[:7]
    if isinstance(value, str):
        value = value.strip().casefold()
        if re.fullmatch(r'-?\d+(?:\.\d+)?', value):
            return round(float(value), 2)
        if len(value) >= 10 and value[4:5] == '-' and value[7:8] == '-':
            return value[:7]
        return value
    return value


def row_matches(expected, actual):
    available = [normalized(value) for value in actual.values()]
    for value in expected.values():
        value = normalized(value)
        if isinstance(value, float):
            match = next((index for index, candidate in enumerate(available)
                          if isinstance(candidate, float) and abs(candidate - value) <= .02), None)
        else:
            match = next((index for index, candidate in enumerate(available) if candidate == value), None)
        if match is None:
            return False
        available.pop(match)
    return True


def reference_matches(key, expected, panels):
    if key == 'comparisons':
        # Separate source-labelled panels are equivalent to a service-labelled table.
        return [any(row_matches({'cantidad': row['cantidad']}, actual)
                    for panel in panels
                    if ('paquetes_ems' if row['servicio'] == 'EMS' else 'paquetes_certi') in panel.get('source_tables', [])
                    for actual in panel.get('rows', [])) for row in expected]
    rows = [row for panel in panels for row in panel.get('rows', [])]
    return [any(row_matches(row, actual) for actual in rows) for row in expected]


def run():
    parser=argparse.ArgumentParser()
    parser.add_argument('--skills', nargs='*', choices=[case[0] for case in CASES])
    parser.add_argument('--out', default=str(OUT))
    args=parser.parse_args()
    selected=[case for case in CASES if not args.skills or case[0] in args.skills]
    output=Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    source = get_source()
    assert source.demo is False, 'This audit requires real PostgreSQL.'
    skills = list(AssistantSkill.objects.all())
    original = {skill.pk: skill.enabled for skill in skills}
    by_key = {skill.preset_key: skill for skill in skills if skill.preset_key}
    user = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    session = SessionStore()
    session[SESSION_KEY] = str(user.pk)
    session[BACKEND_SESSION_KEY] = 'django.contrib.auth.backends.ModelBackend'
    session[HASH_SESSION_KEY] = user.get_session_auth_hash()
    session.save()
    report = {'started': timezone.now().isoformat(), 'method': 'Real browser chat UI, live configured AI, actual PostgreSQL read-only source; independent SQL references.',
              'original_states': original, 'cases': [], 'states_restored': False}
    def save():
        (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    try:
        with sync_playwright() as play:
            browser = play.chromium.launch(headless=True, executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
            context = browser.new_context(viewport={'width':1440, 'height':1000}, reduced_motion='reduce')
            context.add_cookies([{'name':'sessionid', 'value':session.session_key, 'url':BASE}])
            page = context.new_page()
            page.set_default_timeout(15000)
            admin = context.new_page()
            for key, label, question, reference, chart_kind in selected:
                print('START ' + key, flush=True)
                item = {'skill': key, 'name': label, 'question': question, 'reference_sql': reference, 'failures': []}
                report['cases'].append(item)
                save()
                try:
                    with source.stream(reference) as stream:
                        expected = list(stream.rows)
                    item['expected'] = expected
                    # State changes are isolated in time and restored in finally.
                    database_call(lambda: (AssistantSkill.objects.update(enabled=False),
                        AssistantSkill.objects.filter(pk=by_key[key].pk).update(enabled=True)))
                    admin.goto(BASE + '/system/?view=skills')
                    expect(admin.locator(f'[data-skill-key="{key}"] .skills-status')).to_have_text('Activa')
                    page.goto(BASE + '/')
                    expect(page.locator('#question')).to_be_visible()
                    page.locator('#new-chat').click()
                    page.locator('#question').fill(question)
                    start = time.monotonic()
                    with page.expect_response(lambda response: '/api/chat/' in response.url and response.request.method == 'POST', timeout=30000) as sent:
                        page.locator('#chat-form .send').click()
                    response = sent.value
                    item['http_status'] = response.status
                    payload = response.json()
                    assert response.status == 202, payload
                    job_id = payload['id']
                    item['job_id'] = job_id
                    result = None
                    for _ in range(280):
                        result = context.request.get(BASE + '/api/results/' + job_id + '/?page=1').json()
                        if result.get('status') in ('ok','error','cancelled','no_matches','empty_table'):
                            break
                        page.wait_for_timeout(850)
                    item['seconds'] = round(time.monotonic() - start, 2)
                    item['result'] = result
                    if result.get('status') != 'ok':
                        item['failures'].append('El chat no completó la consulta correctamente.')
                    if result.get('demo') is not False:
                        item['failures'].append('No se confirmó demo=false.')
                    item['reference_rows_matched'] = reference_matches(key, expected, result.get('panels', []))
                    if not all(item['reference_rows_matched']):
                        item['failures'].append('Hay filas o cifras que no coinciden con el SQL de referencia independiente.')
                    kinds = [panel.get('chart', {}).get('kind') for panel in result.get('panels', []) if panel.get('chart')]
                    if chart_kind and chart_kind not in kinds:
                        item['failures'].append('No generó la gráfica solicitada: ' + chart_kind)
                    item['conversation_id'] = database_call(lambda: str(QueryJob.objects.get(pk=job_id).conversation_id))
                    item['provider_usage'] = database_call(lambda: list(AIUsage.objects.filter(job_id=job_id).values('provider','model','stage','total_tokens')))
                    if not item['provider_usage']:
                        item['failures'].append('No se registró uso real del proveedor.')
                    if result.get('analysis', {}).get('warning'):
                        item['analysis_warning'] = result['analysis']['warning']
                    page.wait_for_timeout(1600)
                    page.screenshot(path=str(output / (key + '.png')), full_page=True)
                except Exception as exc:
                    item['failures'].append(type(exc).__name__ + ': ' + str(exc)[:400])
                item['passed'] = not item['failures']
                save()
                print(json.dumps({'skill':key, 'passed':item['passed'], 'failures':item['failures'], 'seconds':item.get('seconds')}, ensure_ascii=True), flush=True)
            browser.close()
    finally:
        for pk, enabled in original.items():
            AssistantSkill.objects.filter(pk=pk).update(enabled=enabled)
        session.delete()
        report['states_restored'] = all(AssistantSkill.objects.get(pk=pk).enabled == enabled for pk, enabled in original.items())
        report['finished'] = timezone.now().isoformat()
        report['passed'] = len(report['cases']) == len(selected) and all(item.get('passed') for item in report['cases'])
        save()
    print('REPORT ' + str(output / 'results.json'), flush=True)


if __name__ == '__main__':
    run()
