"""Real event report through authenticated browser/API/PDF, without model calls."""
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from pypdf import PdfReader
from browser_smoke import EDGE, credentials


def main():
    output = Path(__file__).resolve().parents[1] / '.runtime' / 'qa' / 'movement-report'
    output.mkdir(parents=True, exist_ok=True)
    username, password = credentials()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=EDGE)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, permissions=['clipboard-read', 'clipboard-write'])
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://127.0.0.1:8000/accounts/login/')
        page.locator('#id_username').fill(username)
        page.locator('#id_password').fill(password)
        page.get_by_role('button', name='Ingresar').click()
        expect(page.locator('#workspace')).to_be_visible()
        expect(page.locator('#connection-state')).not_to_have_text('Comprobando conexión…')
        uid = json.loads(page.locator('#user-id').text_content())
        page.locator('#question').fill('hola quiero que me des el movimiento de paquetes que hice en la temporada la primera semana de junio por departamentos')
        page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
        expect(page.locator('#messages .result-state')).to_have_text('¿De qué año necesitas la primera semana de junio?', timeout=15000)
        page.locator('#question').fill('2026')
        with page.expect_response('**/api/chat/') as created:
            page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
        job_id = created.value.json()['id']
        report = page.locator('#messages .result-card').last
        expect(report.locator('table').first).to_contain_text('Total de movimientos', timeout=30000)
        expect(report.locator('table').first).to_contain_text('Sin departamento')
        expect(report.locator('.result-meta').first).to_contain_text('Cada movimiento es un evento')
        data = context.request.get(f'http://127.0.0.1:8000/api/results/{job_id}/', headers={'X-Bolipost-User': str(uid)}).json()
        panels = data['panels']
        assert sum(row['total_movimientos'] for row in panels[0]['rows']) == sum(row['total_movimientos'] for panel in panels[1:] for row in panel['rows'])
        assert all(any(source.startswith('eventos_') for source in panel['source_tables']) for panel in panels)
        assert all('total_envios' not in panel['columns'] for panel in panels)
        assert 'INTERNACIONAL' in data['analysis']['note']
        page.get_by_role('button', name='Copiar informe', exact=True).click()
        copied = page.evaluate('navigator.clipboard.readText()')
        assert 'Sin departamento' in copied and 'Total de movimientos' in copied
        with page.expect_download() as downloaded:
            page.locator('#messages .pdf-download').last.click()
        path = output / 'movimientos-junio-2026.pdf'
        downloaded.value.save_as(path)
        text = '\n'.join(pdf_page.extract_text() for pdf_page in PdfReader(path).pages)
        assert 'Sin departamento' in text and 'Total de movimientos' in text
        for forbidden in ('Alcance:', 'Página de resultados', 'filas exportadas', 'Filtros de la consulta aplicados.'):
            assert forbidden not in text
        for width, theme in [(1440, 'light'), (390, 'light'), (390, 'dark')]:
            page.set_viewport_size({'width': width, 'height': 1000})
            page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            report.locator('.result-head').first.scroll_into_view_if_needed()
            page.screenshot(path=str(output / f'movements-{width}-{theme}.png'))
        assert not errors, errors
        browser.close()
    print('PASS: real event SQL, missing-year followup, Sin departamento, service totals, copy, real PDF, desktop/mobile/dark')


if __name__ == '__main__':
    main()
