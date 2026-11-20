"""Review saved conversations with the chat renderer in an isolated database."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

from playwright.sync_api import sync_playwright, expect
from browser_system_management_smoke import ROOT, EDGE


def main():
    out = ROOT / '.runtime/qa/chat-inspect'
    out.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = str(probe.getsockname()[1])
    base = 'http://127.0.0.1:' + port
    password = secrets.token_urlsafe(24)
    row = {'id': 60, 'nombre': 'Ana de prueba', 'rol': None, 'sucursal_id': 1,
           'codigo_sucursal': 0, 'punto_venta': 0, 'nombre_sucursal': 'LA PAZ',
           'departamento': 'LA PAZ', 'observacion': '<img src=x onerror=alert(1)>'}
    result = {'id': str(uuid.uuid4()), 'status': 'ok', 'title': 'Detalle del personal',
              'answer': 'Texto repetido con fuentes que el chat omite cuando hay datos.',
              'columns': list(row), 'rows': [row], 'row_count': 1, 'page': 1,
              'has_more': False, 'panels': []}
    table = {**result, 'title': 'Personal por sucursal', 'columns': ['nombre', 'departamento'],
             'rows': [{'nombre': 'Ana de prueba', 'departamento': 'LA PAZ'}] * 12,
             'row_count': 12}
    messages = [{'kind': 'question', 'text': 'Dame los datos del personal de La Paz'},
                {'kind': 'result', 'result': table},
                {'kind': 'question', 'text': 'Datos completos de Ana'},
                {'kind': 'result', 'result': result},
                {'kind': 'result', 'result': {'status': 'error', 'title': 'Consulta pendiente',
                    'error': {'code': 'clarification', 'message': 'Indica la sucursal.'}}}]
    errors, requests = [], []
    with tempfile.TemporaryDirectory(prefix='inspect-qa-', dir=ROOT / '.runtime') as folder:
        with (out / 'server.log').open('w', encoding='utf-8') as log:
            server = subprocess.Popen([sys.executable, str(ROOT / 'scripts/browser_system_management_smoke.py'),
                '--serve', folder, port], cwd=ROOT,
                env={**os.environ, 'SYSTEM_QA_PASSWORD': password}, stdout=log, stderr=log)
            try:
                for _ in range(150):
                    try:
                        urllib.request.urlopen(base + '/accounts/login/', timeout=1)
                        break
                    except Exception:
                        if server.poll() is not None:
                            raise RuntimeError('QA server exited; see server.log')
                        time.sleep(.15)
                with sync_playwright() as play:
                    browser = play.chromium.launch(headless=True, executable_path=EDGE)
                    context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                    page = context.new_page()
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base + '/accounts/login/')
                    page.locator('#id_username').fill('qa-admin')
                    page.locator('#id_password').fill(password)
                    page.locator('button[type=submit]').click()
                    expect(page.locator('#question')).to_be_enabled()
                    uid = json.loads(page.locator('#user-id').text_content())
                    csrf = next(c['value'] for c in context.cookies() if c['name'] == 'csrftoken')
                    chat_id = str(uuid.uuid4())
                    response = context.request.post(base + f'/api/conversations/{chat_id}/save/',
                        headers={'X-CSRFToken': csrf, 'X-Bolipost-User': str(uid)},
                        data={'title': 'Personal de La Paz · Revisión', 'messages': messages, 'revision': 0})
                    assert response.status == 200, response.text()
                    page.on('request', lambda request: requests.append(request.url))
                    page.goto(base + f'/system/chats/{chat_id}/')
                    transcript = page.locator('#inspect-messages')
                    expect(transcript.locator('.question-message')).to_have_count(2)
                    expect(transcript.locator('tbody tr')).to_have_count(12)
                    expect(transcript.locator('.record-fields dd')).to_have_text([
                        '60', 'Ana de prueba', '—', '1', '0', '0', 'LA PAZ', 'LA PAZ', row['observacion']])
                    expect(transcript.locator('img')).to_have_count(0)
                    expect(transcript.locator('.result-card[data-state=clarification]')).to_contain_text('Indica la sucursal.')
                    expect(transcript.locator('.result-narrative')).to_have_count(0)
                    expect(transcript.locator('button, .pdf-download, .question-actions')).to_have_count(0)
                    for theme in ('light', 'dark'):
                        page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
                        for width in (1440, 768, 390, 320):
                            page.set_viewport_size({'width': width, 'height': 1000})
                            page.evaluate('document.fonts.ready')
                            page.wait_for_timeout(400)
                            if width == 1440:
                                assert page.locator('#system-sidebar').evaluate('(node) => Math.abs(node.getBoundingClientRect().width - 280) < 1'), page.locator('#system-sidebar').evaluate('(node) => ({width:node.getBoundingClientRect().width,state:document.documentElement.dataset.adminNav,variable:getComputedStyle(node).getPropertyValue("--system-sidebar-width"),animations:node.getAnimations().map(a=>a.playState)})')
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (theme, width)
                            page.screenshot(path=str(out / f'inspect-{theme}-{width}.png'), full_page=True, animations='disabled')
                    assert not [url for url in requests if '/api/' in url], requests
                    # Administrative history and trash stay scoped to the selected account.
                    page.get_by_role('link', name='Volver a conversaciones').click()
                    expect(page).to_have_url(base + f'/system/?view=chats&user={uid}&trash=0#chats')
                    expect(page.get_by_role('heading', name='Conversaciones de qa-admin')).to_be_visible()
                    expect(page.locator('.chat-account-dashboard')).to_be_visible()
                    expect(page.locator('.chat-account-metrics>div')).to_have_count(4)
                    assert int(page.locator('.chat-account-metrics dd').last.get_attribute('data-number')) > 0
                    for theme in ('light', 'dark'):
                        page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
                        for width in (1440, 768, 390, 320):
                            page.set_viewport_size({'width': width, 'height': 1000})
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (theme, width)
                            assert page.locator('.chat-account-dashboard').evaluate('el => el.scrollWidth <= el.clientWidth')
                            page.screenshot(path=str(out / f'account-dashboard-{theme}-{width}.png'), full_page=True, animations='disabled')
                    page.get_by_role('link', name='Cambiar usuario', exact=False).click()
                    expect(page.get_by_role('heading', name='Seleccionar usuario')).to_be_visible()
                    expect(page.get_by_role('link', name='Ver resumen de qa-admin')).to_be_visible()
                    expect(page.get_by_role('link', name='Ver resumen de qa-user')).to_be_visible()
                    expect(page.locator('.chat-history-tabs')).to_have_count(0)
                    for theme in ('light', 'dark'):
                        page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
                        for width in (1440, 768, 390, 320):
                            page.set_viewport_size({'width': width, 'height': 1000})
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (theme, width)
                            assert page.locator('.chat-account-list').evaluate('(node) => node.scrollWidth <= node.clientWidth')
                            page.screenshot(path=str(out / f'accounts-{theme}-{width}.png'), full_page=True, animations='disabled')
                    page.locator('#chat-account-search').fill('qa-user')
                    page.locator('.chat-picker button[type=submit]').click()
                    expect(page.locator('.chat-account-option')).to_have_count(1)
                    page.get_by_role('link', name='Ver resumen de qa-user').click()
                    expect(page.locator('#chats')).to_contain_text('Esta cuenta todavía no tiene conversaciones')
                    expect(page.locator('#chats')).not_to_contain_text('Personal de La Paz')
                    page.goto(base + f'/system/?view=chats&user={uid}&trash=0')
                    page.once('dialog', lambda dialog: dialog.accept())
                    page.get_by_role('button', name='Enviar a papelera', exact=True).click()
                    expect(page.get_by_role('link', name='Historial 0', exact=True)).to_be_visible()
                    page.get_by_role('link', name='Papelera 1', exact=True).click()
                    expect(page.locator('#chats')).to_contain_text('Personal de La Paz')
                    page.get_by_role('button', name='Restaurar', exact=True).click()
                    expect(page).to_have_url(base + f'/system/?view=chats&user={uid}&trash=1#chats')
                    expect(page.get_by_role('link', name='Historial 1', exact=True)).to_be_visible()
                    expect(page.locator('#chats')).to_contain_text('La papelera de esta cuenta está vacía.')
                    assert not errors, errors
                    browser.close()
            finally:
                server.terminate()
                server.wait(timeout=10)
    print('PASS: saved chat renderer; account directory, scoped history/trash, empty account, move/restore and return navigation; both themes at 1440/768/390/320px')


if __name__ == '__main__':
    main()
