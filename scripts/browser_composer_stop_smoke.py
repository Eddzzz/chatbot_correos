"""Verify composer cancellation and an unframed thinking mascot without provider calls."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from browser_smoke import credentials, EDGE

OUT = Path(__file__).resolve().parents[1] / '.runtime/qa/composer-stop'
BASE = 'http://127.0.0.1:8012'

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=EDGE)
        page = browser.new_page(viewport={'width':1440, 'height':900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(BASE + '/accounts/login/')
        username, password = credentials()
        page.locator('#id_username').fill(username)
        page.locator('#id_password').fill(password)
        page.get_by_role('button', name='Ingresar').click()
        expect(page.locator('#workspace')).to_be_visible()
        uid = json.loads(page.locator('#user-id').text_content())
        headers = {'Content-Type':'application/json', 'X-Bolipost-User':str(uid)}
        job = '00000000-0000-0000-0000-000000000077'
        cancelled = []
        state = {'status':'running', 'columns':[], 'rows':[], 'row_count':0}
        page.route('**/api/chat/', lambda route: route.fulfill(status=202, headers=headers, body=json.dumps({'id':job, 'status':'queued'})))
        def result(route):
            if '/cancel/' in route.request.url:
                cancelled.append(route.request.method)
                route.fulfill(headers=headers, body=json.dumps({'id':job, 'status':'cancelled'}))
            else:
                route.fulfill(headers=headers, body=json.dumps({'id':job, **state}))
        page.route('**/api/results/**', result)
        page.locator('#question').fill('Consulta de prueba de cancelacion')
        page.locator('.send').click()
        expect(page.locator('.pending-label')).to_be_visible()
        stop = page.get_by_role('button', name='Detener consulta', exact=True)
        expect(stop).to_be_enabled()
        assert page.locator('.send').get_attribute('type') == 'button'
        assert page.locator('.result-actions button').count() == 0
        assert page.locator('.thinking-state').evaluate('(n) => getComputedStyle(n.parentElement).backgroundColor') == 'rgba(0, 0, 0, 0)'
        page.screenshot(path=str(OUT/'desktop-thinking.png'))
        stop.click()
        expect(page.locator('#messages')).to_contain_text('La consulta fue cancelada.')
        assert cancelled == ['POST']
        expect(page.get_by_role('button', name='Consultar', exact=True)).to_be_enabled()
        assert page.locator('.send').get_attribute('type') == 'submit'
        page.set_viewport_size({'width':390, 'height':844})
        page.locator('#question').fill('Otra consulta de prueba')
        page.locator('.send').click()
        expect(page.locator('.pending-label')).to_be_visible()
        page.screenshot(path=str(OUT/'mobile-thinking.png'))
        state.update(status='error', error={'message':'Error de prueba'})
        expect(page.get_by_role('button', name='Consultar', exact=True)).to_be_enabled()
        expect(page.locator('#messages')).to_contain_text('Error de prueba')
        # Stop before the server has returned a job id; cancel the late job too.
        held = []
        page.route('**/api/chat/', lambda route: held.append(route))
        page.locator('#question').fill('Cancelar antes de recibir identificador')
        page.locator('.send').click()
        expect(page.get_by_role('button', name='Detener consulta', exact=True)).to_be_enabled()
        page.get_by_role('button', name='Detener consulta', exact=True).click()
        expect(page.get_by_role('button', name='Consultar', exact=True)).to_be_enabled()
        assert held
        held[0].fulfill(status=202, headers=headers, body=json.dumps({'id':job, 'status':'queued'}))
        page.wait_for_function("document.querySelector('.send').type === 'submit'")
        for _ in range(20):
            if len(cancelled) == 2:
                break
            page.wait_for_timeout(50)
        assert cancelled == ['POST', 'POST']
        assert not errors, errors
        browser.close()
    print('OK: detener desde enviar, POST cancelacion, restauracion tras cancelar/error, fondo transparente, escritorio/movil, sin errores JS.')

if __name__ == '__main__':
    main()

