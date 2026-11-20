"""Browser QA: simulated Groq, actual demo SQL/API/PDF, no live provider claim."""
import json
import os
from pathlib import Path
import sys
import traceback
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
import httpx
from django.conf import settings
from django.test import Client, override_settings
from playwright.sync_api import sync_playwright, expect
from pypdf import PdfReader

BASE = 'http://127.0.0.1:8000'
OUT = ROOT / '.runtime' / 'qa'
EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'


def credentials():
    fields = {}
    for line in (ROOT / '.runtime' / 'local-access.txt').read_text(encoding='utf-8-sig').splitlines():
        if ':' in line:
            key, value = line.split(':', 1)
            fields[key.strip().lower()] = value.strip()
    return fields['usuario'], fields['contraseña']


def seed_report(session_cookie, identity, payload, composer_fails=False):
    # The authenticated browser session stays in memory; it is never printed or persisted.
    client = Client(HTTP_HOST='127.0.0.1')
    client.cookies[settings.SESSION_COOKIE_NAME] = session_cookie
    queries = [
        {'title': 'Total EMS', 'sql': 'SELECT COUNT(*) AS total FROM assistant.paquetes_ems'},
        {'title': 'EMS por ciudad', 'sql': 'SELECT ciudad, COUNT(*) AS total FROM assistant.paquetes_ems GROUP BY ciudad ORDER BY ciudad', 'chart': {'kind': 'bar', 'label_column': 'ciudad', 'value_column': 'total', 'label': 'Envíos EMS'}},
        {'title': 'EMS por estado', 'sql': 'SELECT estado_id, COUNT(*) AS total FROM assistant.paquetes_ems GROUP BY estado_id ORDER BY estado_id', 'chart': {'kind': 'bar', 'label_column': 'estado_id', 'value_column': 'total', 'label': 'Envíos por estado'}},
        {'title': 'Evolución mensual EMS', 'sql': "SELECT DATE_TRUNC('month', created_at::timestamp) AS mes, COUNT(*) AS total FROM assistant.paquetes_ems GROUP BY mes ORDER BY mes", 'chart': {'kind': 'line', 'label_column': 'mes', 'value_column': 'total', 'label': 'Envíos por mes'}},
        {'title': 'Detalle EMS para revisar páginas', 'sql': 'SELECT id, codigo FROM assistant.paquetes_ems UNION ALL SELECT id, codigo FROM assistant.paquetes_ems'}]
    calls = []

    def handle(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            content = {'intent': 'dashboard', 'title': 'Dashboard EMS · proveedor simulado · datos de demostración', 'queries': queries}
        else:
            content = {'paragraphs': [
                {'kind': 'value', 'references': [{'panel': 0, 'row': 0, 'column': 'total'}]},
                {'kind': 'value', 'references': [{'panel': 1, 'row': 0, 'column': 'ciudad'}, {'panel': 1, 'row': 0, 'column': 'total'}]},
                {'kind': 'comparison', 'references': [{'panel': 2, 'row': 0, 'column': 'total'}, {'panel': 2, 'row': 1, 'column': 'total'}]}]}
        if composer_fails and len(calls) > 1:
            content = {'paragraphs': []}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(content)}}]})

    real_client = httpx.Client
    with override_settings(JOBS_EAGER=True, DATA_MODE='demo', GROQ_API_KEY='qa-simulated-provider'), patch('postal.ai.httpx.Client', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw)):
        response = client.post('/api/chat/', payload, secure=True, content_type='application/json',
                               HTTP_X_BOLIPOST_USER=identity)
    assert response.status_code == 202
    assert len(calls) == (3 if composer_fails else 2)
    return response.json()['id']


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'provider': 'Simulated Groq via MockTransport; no live model call.', 'data': 'Real DemoSource SQL, persisted server result, real result and PDF HTTP endpoints.', 'checks': [], 'failures': [], 'screenshots': []}
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=EDGE)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, permissions=['clipboard-read', 'clipboard-write'])
        page = context.new_page()
        page.set_default_timeout(12000)
        page.on('pageerror', lambda error: errors.append(str(error)))

        def check(name, fn):
            try:
                fn()
                report['checks'].append(name)
                print('PASS: ' + name, flush=True)
            except Exception as exc:
                report['failures'].append({'check': name, 'type': type(exc).__name__, 'detail': str(exc)[:400]})
                print('FAIL: ' + name + ' (' + type(exc).__name__ + f', line {traceback.extract_tb(exc.__traceback__)[-1].lineno})', flush=True)

        def screenshot(name):
            expect(page.locator('#announcement')).to_be_hidden(timeout=6000)
            page.locator('#question').blur()
            page.evaluate('scrollTo(0, 0)')
            path = OUT / name
            page.screenshot(path=str(path), full_page=True)
            report['screenshots'].append(str(path))

        try:
            username, password = credentials()
            page.goto(BASE + '/accounts/login/')
            page.locator('#id_username').fill(username)
            page.locator('#id_password').fill(password)
            page.get_by_role('button', name='Ingresar').click()
            expect(page.locator('#workspace')).to_be_visible()
            expect(page.locator('#connection-state')).not_to_have_text('Comprobando conexión…')
            identity = json.loads(page.locator('#api-identity').text_content())
            session_cookie = next(cookie['value'] for cookie in context.cookies() if cookie['name'] == settings.SESSION_COOKIE_NAME)
            api_headers = {'X-Bolipost-User': identity}
            job_id = None
            composer_fails = False

            def route_chat(route):
                nonlocal job_id
                with ThreadPoolExecutor(max_workers=1) as pool:
                    job_id = pool.submit(seed_report, session_cookie, identity,
                                         route.request.post_data_json, composer_fails).result()
                route.fulfill(status=202, headers={**api_headers, 'Content-Type': 'application/json'},
                              body=json.dumps({'id': job_id, 'status': 'queued'}))
            page.route('**/api/chat/', route_chat)
            page.locator('#question').fill('Crea un dashboard EMS con resumen, ciudades, estados, evolución mensual y detalle.')
            page.locator('#chat-form').get_by_role('button', name='Consultar').click()
            expect(page.locator('#messages .result-card')).to_have_count(1)
            result = context.request.get(f'{BASE}/api/results/{job_id}/', headers=api_headers).json()
            assert result['status'] == 'ok', result.get('error')
            assert result['analysis']['generated'] and result['demo']
            assert len(result['panels']) == 5
            root_card = page.locator('#messages > .message > .result-card')
            secondary = root_card.locator('.report-panel')

            def narrative():
                expect(root_card.locator(':scope > .result-head .analysis-label')).to_have_count(0)
                paragraphs = root_card.locator(':scope > .result-head .result-narrative p')
                expect(paragraphs.first).to_contain_text('80')
                expect(root_card.locator(':scope > .table-scroll')).to_contain_text('80')
                assert 'simulado' in root_card.text_content()
                assert 'Fuente:' not in root_card.text_content()
                assert 'Origen:' not in root_card.text_content() and 'Filtros:' not in root_card.text_content()
            check('respuesta con explicación, datos y título', narrative)

            def panels_charts():
                expect(secondary).to_have_count(4)
                expect(root_card.locator('table')).to_have_count(5)
                expect(root_card.locator('canvas')).to_have_count(2)
                assert result['panels'][3]['rows'][0]['mes'] == '2026-10-01 00:00:00'
                expect(root_card.locator(':scope > .table-scroll tbody tr')).to_have_count(1)
                for panel, metadata in zip([root_card, *[secondary.nth(i) for i in range(4)]], result['panels']):
                    assert metadata['title'] in panel.text_content()
                for index in [1, 2, 3]:
                    chart = secondary.nth(index-1).locator('canvas')
                    if chart.count():
                        values = chart.evaluate('(canvas) => Chart.getChart(canvas).data.datasets[0].data')
                        assert values == result['panels'][index]['chart']['values']
                    else:
                        expected_value = page.evaluate('(n) => new Intl.NumberFormat("es-BO", {maximumFractionDigits:2}).format(n)', result['panels'][index]['chart']['values'][0])
                        expect(secondary.nth(index-1).locator('.chart-single strong')).to_have_text(expected_value)
            check('cinco paneles sin duplicar principal; gráficos e indicador coinciden con SQL', panels_charts)

            def single_point():
                assert secondary.nth(2).locator('canvas').evaluate('(canvas) => Chart.getChart(canvas).data.datasets[0].pointRadius > 0'), 'Una serie lineal de un punto necesita un marcador visible.'
            check('serie lineal con un único valor conserva un punto visible', single_point)

            def copy_all():
                root_card.locator('xpath=following-sibling::div[contains(@class,"result-actions")]').get_by_role('button', name='Copiar informe').click()
                copied = page.evaluate('navigator.clipboard.readText()')
                for panel in result['panels']:
                    assert panel['title'] in copied
                assert '80' in copied and 'BO-DEMO-' in copied
            check('copia informe completo con narrativa y todos los paneles', copy_all)

            detail = secondary.nth(3)
            def paginate():
                expect(root_card.locator('.pagination')).to_have_count(0)
                assert '80' in root_card.locator(':scope > .table-scroll').text_content()
                assert '1:1,2:1,3:1,4:1' in root_card.locator('xpath=following-sibling::div[contains(@class,"result-actions")]//a').get_attribute('href').replace('%3A', ':').replace('%2C', ',')
                expected = context.request.get(f'{BASE}/api/results/{job_id}/?panel=4&page=1', headers=api_headers).json()
                expect(detail.locator('tbody tr')).to_have_count(len(expected['rows']))
                first = detail.locator('tbody tr').first.inner_text()
                assert str(expected['rows'][0]['id']) in first and expected['rows'][0]['codigo'] in first
            check('informe sin barra de paginación conserva datos y enlace PDF', paginate)

            def pdf_scope():
                expected = context.request.get(f'{BASE}/api/results/{job_id}/?panel=4&page=1', headers=api_headers).json()
                full_href = root_card.locator('xpath=following-sibling::div[contains(@class,"result-actions")]//a').get_attribute('href')
                full = context.request.get(BASE + full_href, headers=api_headers)
                assert full.status == 200 and full.body().startswith(b'%PDF-')
                full_path = OUT / 'ai-dashboard-full.pdf'
                full_path.write_bytes(full.body())
                text = '\n'.join(p.extract_text() for p in PdfReader(full_path).pages)
                for panel in result['panels']:
                    assert panel['title'] in text
                assert 'simulado' in text
                for forbidden in ('Alcance:', 'Consulta:', 'Página de resultados', 'filas exportadas', 'Origen:', 'Filtros de la consulta'):
                    assert forbidden not in text
                assert expected['rows'][0]['codigo'] in text
                # The continuous report exposes one export action; individual export remains an API capability.
                selected = context.request.get(f'{BASE}/api/results/{job_id}/pdf/?panel=4&page=2', headers=api_headers)
                selected_path = OUT / 'ai-dashboard-selected-panel.pdf'
                selected_path.write_bytes(selected.body())
                selected_text = '\n'.join(p.extract_text() for p in PdfReader(selected_path).pages)
                assert 'Detalle EMS para revisar páginas' in selected_text
                assert 'EMS por ciudad' not in selected_text
                selected_data = context.request.get(f'{BASE}/api/results/{job_id}/?panel=4&page=2', headers=api_headers).json()
                assert selected_data['rows'][0]['codigo'] in selected_text
                with page.expect_download() as downloaded:
                    page.locator('#messages .pdf-download').click()
                download = downloaded.value
                assert download.suggested_filename.startswith('bolipost-')
                assert str(job_id) not in download.suggested_filename
                download.save_as(OUT / 'report-download.pdf')
                expect(page.locator('#messages .report-export-status')).to_have_text('PDF listo. Revisa tus descargas.')
                downloaded_text = '\n'.join(p.extract_text() for p in PdfReader(OUT / 'report-download.pdf').pages)
                assert 'Alcance:' not in downloaded_text and expected['rows'][0]['codigo'] in downloaded_text
                for width, theme in [(1440, 'light'), (390, 'light'), (390, 'dark')]:
                    page.set_viewport_size({'width': width, 'height': 1000})
                    page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                    export = page.locator('#messages .result-icon-actions')
                    export.scroll_into_view_if_needed()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert export.evaluate('(node) => node.scrollWidth <= node.clientWidth')
                    page.screenshot(path=str(OUT / f'pdf-download-{width}-{theme}.png'))
                page.set_viewport_size({'width': 1440, 'height': 1000})
                page.evaluate('document.documentElement.dataset.theme = "light"')
                pending = []
                def expired_pdf(route):
                    pending.append(route)
                page.route('**/pdf/**', expired_pdf)
                page.locator('#messages .pdf-download').click()
                expect(page.locator('#messages .pdf-download')).to_have_attribute('aria-busy', 'true')
                expect(page.locator('#messages .pdf-download')).to_have_text('Preparando PDF…')
                page.locator('#messages .pdf-download').evaluate('(node) => node.click()')
                assert len(pending) == 1
                pending[0].fulfill(status=410, headers={**api_headers, 'Content-Type': 'application/json'},
                    body=json.dumps({'error': {'code': 'expired', 'message': 'El resultado venció. Vuelva a consultar antes de exportar.'}}))
                expect(page.locator('#messages .report-export-status')).to_contain_text('El resultado venció.')
                expect(page.locator('#messages .pdf-download')).not_to_have_attribute('aria-busy', 'true')
                page.unroute('**/pdf/**', expired_pdf)
            check('PDF HTTP real completo y panel individual respetan alcance visible', pdf_scope)

            def layout():
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert root_card.locator('canvas').first.bounding_box()['width'] > 100
            check('escritorio 1440 sin desbordamiento', layout)
            screenshot('ai-dashboard-desktop.png')
            page.set_viewport_size({'width': 390, 'height': 844})
            check('móvil 390 sin desbordamiento', layout)
            screenshot('ai-dashboard-mobile.png')
            page.set_viewport_size({'width': 1440, 'height': 1000})

            def restore():
                page.locator('#new-chat').click()
                page.locator('#history-list .history-item > button').first.click()
                expect(page.locator('#messages .result-card')).to_have_count(1)
                expect(root_card.locator('canvas')).to_have_count(2)
                expect(detail.locator('.pagination')).to_have_count(0)
                expect(root_card.locator(':scope > a')).to_have_count(0)
                expect(page.locator('#messages .result-icon-actions a')).to_have_count(1)
                expect(root_card.locator('.pagination')).to_have_count(0)
                assert 'Resultado guardado en este navegador' not in root_card.text_content()
            check('historial restaura narrativa, gráficos, páginas e iconos de exportación', restore)
            screenshot('ai-dashboard-restored.png')

            def fallback():
                nonlocal composer_fails
                composer_fails = True
                page.locator('#new-chat').click()
                page.locator('#question').fill('Genera un dashboard EMS; comprueba el resultado si falla la explicación.')
                page.locator('#chat-form').get_by_role('button', name='Consultar').click()
                expect(page.locator('#messages .result-card')).to_have_count(1)
                expect(root_card.locator('.analysis-label')).to_have_count(0)
                expect(root_card.locator('p.result-meta')).to_contain_text('la explicación de IA no superó la validación')
                fallback_data = context.request.get(f'{BASE}/api/results/{job_id}/', headers=api_headers).json()
                assert fallback_data['analysis']['generated'] is False
                expect(root_card.locator('table')).to_have_count(5)
                expect(root_card.locator('canvas')).to_have_count(2)
                expect(root_card.locator(':scope > .table-scroll')).to_contain_text('80')
            check('fallo del compositor conserva datos y avisa sin atribuir análisis IA', fallback)
            check('sin errores JavaScript', lambda: assert_no_errors(errors))
        finally:
            browser.close()
            (OUT / 'report-smoke.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    assert not report['failures'], 'Browser checks failed; inspect report-smoke.json.'
    print('Browser report QA complete: ' + str(len(report['checks'])) + ' checks. Provider simulated; no live IA verification.')


def assert_no_errors(errors):
    assert not errors, errors


if __name__ == '__main__':
    run()
