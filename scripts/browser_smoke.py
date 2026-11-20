"""Current chat UI smoke with real auth/API/PDF and simulated report generation."""
import json
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.runtime/qa'
BASE = 'http://127.0.0.1:8000'
EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'


def credentials():
    fields = {}
    for line in (ROOT / '.runtime/local-access.txt').read_text(encoding='utf-8-sig').splitlines():
        if ':' in line:
            key, value = line.split(':', 1)
            fields[key.strip().lower()] = value.strip()
    return fields['usuario'], fields['contraseña']


def manage_user(username, password=None):
    env = dict(os.environ, QA_USERNAME=username, QA_PASSWORD=password or '')
    code = ("import os;from django.contrib.auth import get_user_model;U=get_user_model();"
            + ("U.objects.create_user(os.environ['QA_USERNAME'],password=os.environ['QA_PASSWORD'])"
               if password else "U.objects.filter(username=os.environ['QA_USERNAME']).delete()"))
    result = subprocess.run([sys.executable, 'manage.py', 'shell', '-c', code], cwd=ROOT,
                            env=env, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('No se pudo preparar o limpiar la cuenta temporal de QA.')


def run():
    from browser_report_smoke import seed_report
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'checks': [], 'failures': [], 'screenshots': [],
              'scope': 'Current chat UI; real auth/result/PDF APIs; seeded demo report with simulated AI.'}
    username, password = credentials()
    qa_user, qa_password = 'qa_session_' + uuid.uuid4().hex[:10], uuid.uuid4().hex
    created_user = False
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=EDGE)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, permissions=['clipboard-read', 'clipboard-write'])
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(type(error).__name__))

        def passed(name):
            report['checks'].append(name)
            print('PASS: ' + name, flush=True)

        def login(tab, user, secret):
            tab.goto(BASE + '/accounts/login/')
            tab.locator('#id_username').fill(user)
            tab.locator('#id_password').fill(secret)
            tab.get_by_role('button', name='Ingresar').click()
            expect(tab.locator('#question')).to_be_enabled()
            expect(tab.locator('#connection-state')).not_to_have_text('Comprobando conexión…')

        def theme(value):
            if not page.locator('#theme-toggle').is_visible():
                page.locator('#menu-toggle').click()
            for _ in range(3):
                if page.locator('#theme-toggle').get_attribute('data-value') == value:
                    break
                page.locator('#theme-toggle').click()
            expect(page.locator('html')).to_have_attribute('data-theme', value)
            if page.locator('#menu-close').is_visible():
                page.locator('#menu-close').click()

        try:
            login(page, username, password)
            passed('autenticación e inicialización del chat')
            uid = json.loads(page.locator('#user-id').text_content())
            identity = json.loads(page.locator('#api-identity').text_content())
            headers = {'X-Bolipost-User': identity}
            status = context.request.get(BASE + '/api/status/', headers=headers)
            assert status.status == 200
            if status.json()['data_mode'] == 'demo':
                expect(page.locator('#environment-notice')).to_be_visible()
            else:
                expect(page.locator('#environment-notice')).to_be_hidden()
            expect(page.locator('#view-chat')).to_be_visible()
            expect(page.locator('.navigation [data-view]')).to_have_count(0)
            passed('entorno identificado y menú actual')
            catalog = context.request.get(BASE + '/api/catalog/', headers=headers)
            assert catalog.status == 200
            tables = catalog.json()['tables']
            users = next(table for table in tables if table['name'] == 'users')
            assert not {'name', 'email', 'ci', 'password'} & {column['name'] for column in users['columns']}
            passed('catálogo por API y campos sensibles restringidos')
            cookie = next(item['value'] for item in context.cookies() if item['name'] == 'sessionid')
            def route_chat(route):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    job_id = pool.submit(seed_report, cookie, identity, route.request.post_data_json).result()
                route.fulfill(status=202, headers={**headers, 'Content-Type': 'application/json'},
                              body=json.dumps({'id': job_id, 'status': 'queued'}))
            page.route('**/api/chat/', route_chat)
            question = 'Informe de prueba del menú actual'
            page.locator('#question').fill(question)
            page.get_by_role('button', name='Consultar', exact=True).click()
            card = page.locator('#messages .result-card')
            expect(card.locator('table')).to_have_count(5)
            expect(card.locator('canvas')).to_have_count(2)
            assert '/c/' in page.url
            passed('chat, informe persistido, tablas, gráficos y URL')
            page.get_by_role('button', name='Copiar informe', exact=True).click()
            assert 'BO-DEMO-' in page.evaluate('navigator.clipboard.readText()')
            with page.expect_download() as downloaded:
                page.get_by_role('link', name='Descargar PDF', exact=False).click()
            path = OUT / 'current-ui-report.pdf'
            downloaded.value.save_as(path)
            assert path.read_bytes().startswith(b'%PDF-')
            passed('copia y descarga PDF real')
            for width in (1440, 390):
                page.set_viewport_size({'width': width, 'height': 1000})
                for value in ('light', 'dark'):
                    theme(value)
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    expect(page.locator('#chat-form')).to_be_visible()
                    screenshot = OUT / f'current-ui-{width}-{value}.png'
                    page.screenshot(path=str(screenshot))
                    report['screenshots'].append(str(screenshot))
            passed('menú móvil y ambos temas sin desbordamiento')
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.locator('#new-chat').click()
            page.locator('#history-search').fill(question)
            page.locator('.history-item > button').first.click()
            expect(card.locator('table')).to_have_count(5)
            page.reload()
            expect(card.locator('table')).to_have_count(5)
            page.once('dialog', lambda dialog: dialog.accept())
            page.locator('.history-delete').click()
            expect(page.locator('.history-item')).to_have_count(0)
            page.locator('#history-search').fill('')
            passed('historial: buscar, restaurar, recargar y eliminar')
            manage_user(qa_user, qa_password)
            created_user = True
            other = context.new_page()
            other.goto(BASE + '/')
            other.locator('#logout-form').evaluate('(form) => form.submit()')
            other.wait_for_url(BASE + '/accounts/login/')
            login(other, qa_user, qa_password)
            new_uid = json.loads(other.locator('#user-id').text_content())
            assert uid != new_uid
            page.unroute('**/api/chat/')
            page.locator('#question').fill('Consulta desde la cuenta anterior')
            with page.expect_response('**/save/') as rejected:
                page.get_by_role('button', name='Consultar', exact=True).click()
            assert rejected.value.status in (403, 409)
            page.wait_for_function("uid => JSON.parse(document.querySelector('#user-id')?.textContent || 'null') === uid", arg=new_uid)
            expect(page.locator('#question')).to_be_enabled()
            expect(page.locator('#history-list')).not_to_contain_text(question)
            other.close()
            passed('cambio de cuenta invalida la pestaña anterior y aísla historial')
            assert not errors, errors
            passed('sin errores JavaScript')
        except Exception as error:
            report['failures'].append({'type': type(error).__name__, 'detail': str(error)[:700]})
        finally:
            browser.close()
            if created_user:
                manage_user(qa_user)
            (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Smoke: {len(report['checks'])} checks passed; {len(report['failures'])} failures.")
    return bool(report['failures'])


if __name__ == '__main__':
    raise SystemExit(run())
