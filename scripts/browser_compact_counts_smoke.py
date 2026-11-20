"""Wide full-data results: synthetic records in a real browser, no provider calls."""
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from browser_smoke import EDGE, credentials


def main():
    out = Path(__file__).resolve().parents[1] / '.runtime' / 'qa' / 'compact-counts'
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
        names = ['EMS en Oruro', 'CERTI en Oruro', 'ORDI en Oruro', 'INT con destino Oruro', 'CONTRATO con origen o destino Oruro']
        values = [266, 24, 565, 0, 4479]
        panels = [dict(index=i, title=name, status='ok', columns=['total_envios'], rows=[{'total_envios':value}], row_count=1, page=1, has_more=False, chart=None) for i,(name,value) in enumerate(zip(names,values))]
        result = dict(panels[0], id=job_id, title='Cantidad de paquetes en Oruro (actual)', panels=panels, answer='', analysis={'warning':'Los datos se verificaron, pero no se pudo generar la explicación de IA: Groq limitó temporalmente las solicitudes.'})
        page.route('**/api/chat/', lambda route: route.fulfill(status=202, headers=headers, body=json.dumps({'id': job_id, 'status': 'queued'})))
        page.route('**/api/results/**', lambda route: route.fulfill(status=200, headers=headers, body=json.dumps(result)))
        page.locator('#question').fill('Hola, dime cuántos paquetes hay en Oruro actualmente')
        page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
        report = page.locator('#messages .result-card')
        expect(report.locator('.compact-results tbody tr')).to_have_count(5)
        expect(report.locator('.report-panels')).to_have_count(0)
        expect(report.locator('.compact-results tbody th')).to_have_text(names)
        expect(report.locator('.compact-results tbody td')).to_have_text([str(v) for v in values])
        expect(report.locator('.result-notice')).to_have_count(0)
        expect(report).not_to_contain_text(result['analysis']['warning'])
        for width in (1440, 768, 390, 320):
            page.set_viewport_size({'width': width, 'height': 1000})
            for theme in ('light', 'dark'):
                page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                assert report.evaluate('(node) => node.scrollWidth <= node.clientWidth')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.evaluate('document.documentElement.dataset.theme = "light"')
            page.locator('#announcement').wait_for(state='hidden')
            page.locator('#conversation').evaluate('(node) => node.scrollTop = 0')
            page.screenshot(path=str(out / f'compact-counts-{width}.png'))
        page.get_by_role('button', name='Copiar informe', exact=True).click()
        copied = page.evaluate('navigator.clipboard.readText()')
        assert all(name in copied and str(value) in copied for name,value in zip(names,values))
        expect(page.get_by_role('link', name='Descargar PDF')).to_have_attribute('href', f'/api/results/{job_id}/pdf/?page=1&panel_pages=0%3A1%2C1%3A1%2C2%3A1%2C3%3A1%2C4%3A1')
        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.locator('#new-chat').click()
        page.locator('.history-item > button').first.click()
        expect(report.locator('.compact-results tbody tr')).to_have_count(5)
        assert report.bounding_box()['height'] < 520
        assert not errors, errors
        browser.close()
    print('PASS: compact counts hide explanation warnings and retain titles, zero values, copy, PDF, history and responsive themes')


if __name__ == '__main__':
    main()
