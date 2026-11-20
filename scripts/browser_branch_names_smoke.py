"""Branch labels in current and restored results; synthetic API, no provider calls."""
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from browser_smoke import EDGE, credentials


def main():
    output = Path(__file__).resolve().parents[1] / '.runtime' / 'qa' / 'branch-names'
    output.mkdir(parents=True, exist_ok=True)
    username, password = credentials()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=EDGE)
        context = browser.new_context(permissions=['clipboard-read', 'clipboard-write'])
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://127.0.0.1:8000/accounts/login/')
        page.locator('#id_username').fill(username)
        page.locator('#id_password').fill(password)
        page.get_by_role('button', name='Ingresar').click()
        expect(page.locator('#workspace')).to_be_visible()
        uid = json.loads(page.locator('#user-id').text_content())
        headers = {'Content-Type': 'application/json', 'X-Bolipost-User': str(uid)}
        job_id = '00000000-0000-0000-0000-000000000068'
        old = {'id': job_id, 'status': 'ok', 'title': 'Envíos por sucursal · demostración',
               'columns': ['sucursal_codigo', 'punto_venta', 'total_envios', 'peso_total'],
               'rows': [{'sucursal_codigo': 0, 'punto_venta': 0, 'total_envios': 12, 'peso_total': '1.250'},
                        {'sucursal_codigo': 8, 'punto_venta': 0, 'total_envios': 7, 'peso_total': '0.500'}],
               'row_count': 2, 'page': 1, 'has_more': False, 'panels': [], 'demo': True,
               'source_tables': ['sucursales', 'paquetes_ems'],
               'chart': {'kind': 'bar', 'labels': ['0', '8'], 'values': [12, 7], 'label': 'Envíos'}}
        named = {**old, 'columns': ['nombre_sucursal', *old['columns'][1:]],
                 'rows': [{'nombre_sucursal': name, **{key: value for key, value in row.items() if key != 'sucursal_codigo'}}
                          for name, row in zip(['LA PAZ', 'TRINIDAD'], old['rows'])],
                 'chart': {**old['chart'], 'labels': ['LA PAZ', 'TRINIDAD']}}
        responses = []

        def result(route):
            responses.append(route.request.url)
            route.fulfill(headers=headers, body=json.dumps(old if len(responses) == 1 else named))

        page.route('**/api/chat/', lambda route: route.fulfill(status=202, headers=headers,
                   body=json.dumps({'id': job_id, 'status': 'queued'})))
        page.route('**/api/results/**', result)
        page.locator('#question').fill('Resumen por sucursal')
        page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
        for restored in (False, True):
            if restored:
                page.set_viewport_size({'width': 1440, 'height': 1000})
                page.locator('#new-chat').click()
                page.locator('#history-list .history-item > button').first.click()
            table = page.locator('#messages table')
            expect(table.locator('thead')).to_contain_text('Sucursal')
            expect(table.locator('tbody')).to_contain_text('LA PAZ')
            expect(table.locator('tbody')).to_contain_text('TRINIDAD')
            expect(table.locator('tbody tr')).to_have_count(2)
            assert page.locator('#messages canvas').evaluate('(c) => JSON.stringify(Chart.getChart(c).data.labels)') == '["LA PAZ","TRINIDAD"]'
            page.get_by_role('button', name='Copiar resultado', exact=True).click()
            copied = page.evaluate('navigator.clipboard.readText()')
            assert 'LA PAZ' in copied and 'TRINIDAD' in copied and '1.250' in copied
            for width in (1440, 390):
                page.set_viewport_size({'width': width, 'height': 1000})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(output / f'branches-{width}-restored-{restored}.png'))
        assert len(responses) >= 3
        assert not errors, errors
        browser.close()
    print('PASS: branch names in table/chart/copy, old history refreshed, totals preserved, desktop and mobile')


if __name__ == '__main__':
    main()
