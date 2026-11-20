"""Service comparisons retain every value in one readable, responsive table."""
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from browser_smoke import EDGE, credentials


def main():
    out = Path(__file__).resolve().parents[1] / '.runtime/qa/service-comparison'
    out.mkdir(parents=True, exist_ok=True)
    username, password = credentials()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=EDGE)
        page = browser.new_page(permissions=['clipboard-read', 'clipboard-write'])
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://127.0.0.1:8000/accounts/login/')
        page.locator('#id_username').fill(username)
        page.locator('#id_password').fill(password)
        page.get_by_role('button', name='Ingresar').click()
        expect(page.locator('#workspace')).to_be_visible()
        uid = json.loads(page.locator('#user-id').text_content())
        headers = {'Content-Type': 'application/json', 'X-Bolipost-User': str(uid)}
        job_id = '00000000-0000-0000-0000-000000000089'
        services = ['EMS', 'CERTI', 'CONTRATO', 'INT', 'ORDI']
        values = [(350, 266), (0, 24), (3189, 2720), (13, 1), (0, 565)]
        panels = [dict(index=i, title='Comparación ' + service, status='ok',
                       columns=['tarija', 'oruro'], rows=[dict(zip(['tarija', 'oruro'], pair))],
                       row_count=1, page=1, has_more=False, chart=None)
                  for i, (service, pair) in enumerate(zip(services, values))]
        result = dict(panels[0], id=job_id, title='Comparación de carga entre Tarija y Oruro',
                      panels=panels, answer='', analysis={'warning': 'Explicación no disponible.'})
        page.route('**/api/chat/', lambda route: route.fulfill(status=202, headers=headers, body=json.dumps({'id': job_id, 'status': 'queued'})))
        page.route('**/api/results/**', lambda route: route.fulfill(status=200, headers=headers, body=json.dumps(result)))

        def submit():
            page.locator('#question').fill('Compara la carga con Oruro')
            page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')

        submit()
        report = page.locator('#messages .result-card')
        table = report.locator('.service-comparison')
        expect(table.locator('tbody th')).to_have_text(services)
        expect(table.locator('thead th')).to_have_text(['Servicio', 'Tarija', 'Oruro'])
        expect(report.locator('table')).to_have_count(1)
        expect(report.locator('.report-panels')).to_have_count(0)
        expected = [page.evaluate('(n) => new Intl.NumberFormat("es-BO").format(n)', n) for pair in values for n in pair]
        expect(table.locator('tbody td')).to_have_text(expected)
        bars = table.locator('.comparison-fill')
        assert bars.nth(2).evaluate('(node) => node.style.width') == '0%'
        assert bars.nth(3).evaluate('(node) => node.style.width') == '100%'
        for width in (1440, 768, 390, 320):
            page.set_viewport_size({'width': width, 'height': 1000})
            for theme in ('light', 'dark'):
                page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                assert report.evaluate('(node) => node.scrollWidth <= node.clientWidth')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.locator('#conversation').evaluate('(node) => node.scrollTop = 0')
                page.screenshot(path=str(out / f'{width}-{theme}.png'))
        page.get_by_role('button', name='Copiar informe', exact=True).click()
        copied = page.evaluate('navigator.clipboard.readText()')
        assert all(str(value) in copied for pair in values for value in pair)
        expect(page.get_by_role('link', name='Descargar PDF')).to_have_attribute('href', f'/api/results/{job_id}/pdf/?page=1&panel_pages=0%3A1%2C1%3A1%2C2%3A1%2C3%3A1%2C4%3A1')
        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.locator('#new-chat').click()
        page.locator('.history-item > button').first.click()
        expect(table.locator('tbody th')).to_have_text(services)
        # Partial or incompatible panels must keep their original presentation.
        for change in ({'has_more': True},
                       {'columns': ['tarija', 'otro'], 'rows': [{'tarija': 0, 'otro': 565}]},
                       {'rows': [{'tarija': -1, 'oruro': 565}]}):
            page.locator('#new-chat').click()
            original = panels[-1].copy()
            panels[-1].update(change)
            submit()
            expect(report.locator('.report-panels')).to_be_visible()
            expect(table).to_have_count(0)
            panels[-1].clear()
            panels[-1].update(original)
        assert not errors, errors
        browser.close()
    print('PASS: service comparison values, zeros, scales, themes, mobile, copy, PDF, history and fallback')


if __name__ == '__main__':
    main()
