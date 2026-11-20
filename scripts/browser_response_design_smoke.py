"""Response hierarchy, honest single metrics and copy feedback; synthetic API data."""
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from browser_smoke import EDGE, credentials


def main():
    out = Path('.runtime/qa/response-design')
    out.mkdir(parents=True, exist_ok=True)
    username, password = credentials()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=EDGE)
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
        job = '00000000-0000-0000-0000-000000000086'
        result = {'id': job, 'status': 'ok', 'title': 'Envíos registrados en La Paz',
                  'columns': ['total_envios'], 'rows': [{'total_envios': 12480}],
                  'row_count': 1, 'page': 1, 'has_more': False, 'panels': [], 'demo': True}
        page.route('**/api/chat/', lambda r: r.fulfill(status=202, headers=headers, body=json.dumps({'id': job, 'status': 'queued'})))
        page.route('**/api/results/**', lambda r: r.fulfill(headers=headers, body=json.dumps(result)))

        def submit():
            page.set_viewport_size({'width': 1440, 'height': 960})
            page.locator('#new-chat').click()
            page.locator('#question').fill('Consulta de demostración')
            page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
            expect(page.locator('#messages .result-card h2')).to_have_text(result['title'])

        submit()
        metric = page.locator('.result-metric')
        expect(metric.locator('dd')).to_have_text('12.480')
        expect(metric.locator('dt')).not_to_be_empty()
        copy = page.get_by_role('button', name='Copiar resultado', exact=True)
        copy.click()
        expect(copy).to_have_attribute('data-copied', 'true')
        assert '12480' in page.evaluate('navigator.clipboard.readText()')
        expect(copy).not_to_have_attribute('data-copied', 'true', timeout=5000)
        for theme in ('light', 'dark'):
            page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
            for width in (1440, 768, 390, 320):
                page.set_viewport_size({'width': width, 'height': 960})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(out / f'metric-{theme}-{width}.png'))

        result['rows'][0]['total_envios'] = 0
        submit()
        expect(metric.locator('dd')).to_have_text('0')
        page.locator('#new-chat').click()
        page.locator('.history-item > button').first.click()
        expect(metric.locator('dd')).to_have_text('0')

        result.update(has_more=True, row_count=2)
        submit()
        expect(metric).to_have_count(0)
        expect(page.locator('#messages table')).to_be_visible()

        result.update(has_more=False, row_count=1, columns=['total'], rows=[{'total': '0.004'}])
        submit()
        expect(metric.locator('dd')).to_have_text('0.004')

        clarification = '¿De qué año necesitas el informe?'
        result.update(status='error', title='Completa tu consulta', columns=[], rows=[],
                      answer=clarification, error={'code': 'clarification', 'message': clarification})
        submit()
        state = page.locator('#messages .result-state')
        expect(state).to_have_text(clarification)
        assert 'error-text' not in (state.get_attribute('class') or '')
        assert page.locator('#messages').inner_text().count(clarification) == 1
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(out / 'clarification-mobile.png'))

        result.update(answer='', error={'code': 'query_failed', 'message': 'No se pudo ejecutar la consulta.'})
        submit()
        expect(state).to_have_class('result-state error-text')

        result.update(status='ok', title='Movimientos por departamento', answer='', error=None,
                      has_more=False, columns=['departamento', 'cantidad'], row_count=3,
                      rows=[{'departamento': 'La Paz', 'cantidad': 12480},
                            {'departamento': 'Santa Cruz', 'cantidad': 8560},
                            {'departamento': '<script>alert(1)</script>', 'cantidad': 0}])
        submit()
        expect(page.locator('#messages tbody tr')).to_have_count(3)
        expect(page.locator('#messages tbody')).to_contain_text('<script>alert(1)</script>')
        expect(page.locator('#messages script')).to_have_count(0)
        for theme in ('light', 'dark'):
            page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
            for width in (1440, 390):
                page.set_viewport_size({'width': width, 'height': 960})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(out / f'table-{theme}-{width}.png'))
        assert not errors, errors
        browser.close()
    print('PASS: single metrics, zero, partial data, copy feedback, history, clarification, safe text, themes and 4 widths')


if __name__ == '__main__':
    main()
