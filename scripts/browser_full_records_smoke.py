"""Wide full-data results: synthetic records in a real browser, no provider calls."""
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from browser_smoke import EDGE, credentials


def main():
    out = Path(__file__).resolve().parents[1] / '.runtime' / 'qa' / 'full-records'
    out.mkdir(parents=True, exist_ok=True)
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
        job_id = '00000000-0000-0000-0000-000000000088'
        rows = [dict(id=48, name='Ana de Demostración', rol_id=None, sucursal_id=3,
                     rol=None, codigoSucursal=2, puntoVenta=0, sucursal='COCHABAMBA',
                     observacion='<img src=x onerror=alert(1)>' + 'TextoLargo' * 25),
                dict(id=47, name='Silvia de Demostración', rol_id=None, sucursal_id=3,
                     rol=None, codigoSucursal=2, puntoVenta=0, sucursal='COCHABAMBA',
                     observacion='Segundo registro')]
        result = dict(id=job_id, status='ok', title='Datos completos del personal en Cochabamba',
                      columns=list(rows[0]), rows=rows, row_count=2, page=1, has_more=False,
                      panels=[], answer='')
        page.route('**/api/chat/', lambda route: route.fulfill(status=202, headers=headers, body=json.dumps({'id': job_id, 'status': 'queued'})))
        page.route('**/api/results/**', lambda route: route.fulfill(status=200, headers=headers, body=json.dumps(result)))
        page.locator('#question').fill('Datos completos del personal en Cochabamba')
        page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
        report = page.locator('#messages .result-card')
        expect(report.locator('.record-list > li')).to_have_count(2)
        expect(report.locator('table')).to_have_count(0)
        for index, row in enumerate(rows):
            fields = report.locator('.record-fields').nth(index)
            expect(fields.locator('dt')).to_have_count(len(row))
            expect(fields.locator('dd')).to_have_text(['—' if value is None else str(value) for value in row.values()])
        expect(report.locator('img')).to_have_count(0)
        for width in (1440, 768, 390, 320):
            page.set_viewport_size({'width': width, 'height': 1000})
            for theme in ('light', 'dark'):
                page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                assert report.evaluate('(node) => node.scrollWidth <= node.clientWidth')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.evaluate('document.documentElement.dataset.theme = "light"')
            page.locator('#announcement').wait_for(state='hidden')
            page.locator('#conversation').evaluate('(node) => node.scrollTop = 0')
            page.screenshot(path=str(out / f'full-records-{width}.png'))
        page.get_by_role('button', name='Copiar resultado', exact=True).click()
        copied = page.evaluate('navigator.clipboard.readText()')
        assert all(row['name'] in copied and row['observacion'] in copied for row in rows)
        expect(page.get_by_role('link', name='Descargar PDF')).to_have_attribute('href', f'/api/results/{job_id}/pdf/?page=1')
        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.locator('#new-chat').click()
        page.locator('.history-item > button').first.click()
        expect(report.locator('.record-list > li')).to_have_count(2)
        assert not errors, errors
        browser.close()
    print('PASS: full records retain all values, copy, PDF and history; no overflow at 1440/768/390/320px in both themes')


if __name__ == '__main__':
    main()
