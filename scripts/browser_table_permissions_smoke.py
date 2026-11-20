"""Permission UI checks in a temporary application database and config."""
import json
import os
import re
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'


def run():
    out = ROOT / '.runtime/qa/table-permissions'
    out.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = str(probe.getsockname()[1])
    base = 'http://127.0.0.1:' + port
    password = secrets.token_urlsafe(24)
    with tempfile.TemporaryDirectory(prefix='table-browser-', dir=ROOT / '.runtime') as folder:
        with (out / 'browser-server.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen([sys.executable, str(ROOT / 'scripts/browser_system_management_smoke.py'), '--serve', folder, port],
                cwd=ROOT, env={**os.environ, 'SYSTEM_QA_PASSWORD': password}, stdout=log, stderr=log,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                for _ in range(100):
                    try:
                        urllib.request.urlopen(base + '/accounts/login/', timeout=1)
                        break
                    except Exception:
                        if process.poll() is not None:
                            raise RuntimeError('Temporary UI server failed')
                        time.sleep(.15)
                with sync_playwright() as play:
                    browser = play.chromium.launch(headless=True, executable_path=EDGE)
                    context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base + '/accounts/login/')
                    page.locator('#id_username').fill('qa-admin')
                    page.locator('#id_password').fill(password)
                    page.locator('button[type=submit]').click()
                    page.wait_for_url(base + '/')
                    page.goto(base + '/system/?view=tables')
                    expect(page.get_by_role('heading', name='Permisos de tablas', exact=True)).to_be_visible()
                    tabs = page.get_by_role('navigation', name='Estado de las tablas')
                    expect(tabs.get_by_role('link', name=re.compile('^Permitidas'))).to_have_attribute('aria-current', 'page')
                    expect(page.locator('.table-permission-scroll tbody tr')).to_have_count(16)
                    expect(page.get_by_role('button', name='Permitir auditoria', exact=True)).to_have_count(0)
                    tabs.get_by_role('link', name=re.compile('^No permitidas')).click()
                    expect(page.locator('.table-permission-scroll tbody tr')).to_have_count(106)
                    page.locator('#table-search').fill('auditoria')
                    page.get_by_role('button', name='Filtrar', exact=True).click()
                    native_dialogs = []
                    def reject_native(dialog):
                        native_dialogs.append(dialog.message)
                        dialog.dismiss()
                    page.on('dialog', reject_native)
                    confirmation = page.locator('#table-confirmation')
                    def confirm(label):
                        expect(confirmation).to_be_visible()
                        confirmation.get_by_role('button', name=label, exact=True).click()
                    page.get_by_role('button', name='Permitir auditoria', exact=True).click()
                    expect(confirmation.get_by_role('heading')).to_have_text('¿Permitir la tabla auditoria?')
                    expect(confirmation.get_by_role('button', name='Cancelar')).to_be_focused()
                    confirm('Cancelar')
                    expect(page.get_by_role('button', name='Permitir auditoria', exact=True)).to_be_visible()
                    page.get_by_role('button', name='Permitir auditoria', exact=True).click()
                    confirm('Permitir tabla')
                    expect(page.locator('.system-feedback')).to_contain_text('permitida')
                    expect(page.get_by_role('button', name='Permitir auditoria', exact=True)).to_have_count(0)
                    tabs.get_by_role('link', name=re.compile('^Permitidas')).click()
                    page.reload()
                    expect(page.get_by_role('button', name='Bloquear auditoria', exact=True)).to_be_visible()
                    page.get_by_role('button', name='Bloquear auditoria', exact=True).click()
                    expect(confirmation.get_by_role('heading')).to_have_text('¿Bloquear la tabla auditoria?')
                    page.set_viewport_size({'width': 390, 'height': 844})
                    page.evaluate("document.documentElement.dataset.theme = 'dark'")
                    assert confirmation.evaluate('dialog => dialog.scrollWidth <= dialog.clientWidth')
                    page.screenshot(path=str(out / 'table-confirmation-dark-390.png'))
                    page.set_viewport_size({'width': 1440, 'height': 1000})
                    page.keyboard.press('Escape')
                    expect(confirmation).not_to_be_visible()
                    expect(page.get_by_role('button', name='Bloquear auditoria', exact=True)).to_be_focused()
                    page.get_by_role('button', name='Bloquear auditoria', exact=True).click()
                    confirm('Bloquear tabla')
                    expect(page.locator('.system-feedback')).to_contain_text('bloqueada')
                    page.goto(base + '/system/?view=tables&permission=allowed&q=users')
                    page.get_by_role('link', name='Editar campos de users', exact=True).click()
                    editor = page.get_by_role('dialog', name='Editar campos de users', exact=True)
                    expect(editor).to_be_visible()
                    expect(editor.locator('[name=columns][value=password]')).to_be_disabled()
                    expect(editor.locator('[name=columns][value=email]')).not_to_be_checked()
                    for theme in ('light', 'dark'):
                        for width in (1440, 390):
                            page.set_viewport_size({'width': width, 'height': 1000})
                            page.evaluate('(theme) => { document.documentElement.dataset.theme = theme; }', theme)
                            page.screenshot(path=str(out / f'field-editor-{theme}-{width}.png'))
                            assert editor.evaluate('dialog => dialog.scrollWidth <= dialog.clientWidth'), (theme, width)
                    page.set_viewport_size({'width': 1440, 'height': 1000})
                    editor.locator('[name=columns][value=email]').check()
                    editor.get_by_role('button', name='Guardar campos', exact=True).click()
                    confirm('Cancelar')
                    expect(editor).to_be_visible()
                    expect(editor.locator('[name=columns][value=email]')).to_be_checked()
                    editor.get_by_role('link', name='Cancelar', exact=True).click()
                    expect(editor).not_to_be_visible()
                    expect(page.get_by_role('link', name='Editar campos de users', exact=True)).to_be_focused()
                    page.get_by_role('link', name='Editar campos de users', exact=True).click()
                    expect(editor.locator('[name=columns][value=email]')).not_to_be_checked()
                    editor.locator('[name=columns][value=email]').check()
                    editor.get_by_role('button', name='Guardar campos', exact=True).click()
                    confirm('Guardar campos')
                    expect(page.locator('.system-feedback')).to_contain_text('Campos de users guardados')
                    page.get_by_role('link', name='Editar campos de users', exact=True).click()
                    expect(editor.locator('[name=columns][value=email]')).to_be_checked()
                    editor.locator('[name=columns][value=name]').uncheck()
                    editor.get_by_role('button', name='Guardar campos', exact=True).click()
                    confirm('Guardar campos')
                    user_row = page.locator('.table-permission-scroll tbody tr')
                    expect(user_row.locator('.protected-fields').get_by_text('name', exact=True)).to_have_count(1)
                    expect(user_row.locator('.authorized-fields').get_by_text('email', exact=True)).to_have_count(1)
                    page.goto(base + '/system/?view=tables&permission=allowed')
                    expect(tabs.get_by_role('link', name=re.compile('^Permitidas'))).to_have_attribute('aria-current', 'page')
                    expect(page.get_by_role('button', name='Bloquear paquetes_ems', exact=True)).to_be_visible()
                    row = page.locator('.table-permission-scroll tbody tr').filter(has=page.get_by_role('button', name='Bloquear paquetes_ordi', exact=True))
                    row.locator('.authorized-fields summary').click()
                    expect(row.locator('.authorized-fields .table-field-list li')).to_have_count(12)
                    contained = row.locator('.table-permission-columns').evaluate('''cell => {
                        const bounds = cell.getBoundingClientRect();
                        return [...cell.querySelectorAll('.authorized-fields li')].every(tag => {
                            const box = tag.getBoundingClientRect();
                            return box.left >= bounds.left && box.right <= bounds.right;
                        });
                    }''')
                    assert contained, 'Expanded field tags overflow their column'
                    row.screenshot(path=str(out / 'expanded-fields.png'))
                    page.evaluate('window.scrollTo(0, 0)')
                    for theme in ('light', 'dark'):
                        for width in (1440, 390):
                            page.set_viewport_size({'width': width, 'height': 1000})
                            page.evaluate('(theme) => { localStorage.setItem("bolipost-theme", theme); document.documentElement.dataset.theme = theme; }', theme)
                            page.screenshot(path=str(out / f'{theme}-{width}.png'))
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (theme, width)
                            if width == 390:
                                row.screenshot(path=str(out / f'expanded-fields-{theme}-390.png'))
                                assert row.locator('.table-permission-columns').evaluate('cell => cell.scrollWidth <= cell.clientWidth'), 'Mobile fields overflow'
                                page.evaluate('window.scrollTo(0, 0)')
                    assert not errors, errors
                    assert not native_dialogs, native_dialogs
                    browser.close()
                (out / 'browser-check.json').write_text(json.dumps({'passed': True, 'checks': [
                    'separate allowed/blocked views', 'allowed by default', 'search', 'allow', 'block', 'persistence',
                    'field editor authorizes and protects', 'confirmations accept/cancel', 'credentials stay locked',
                    'field tags stay in column', 'light/dark', 'desktop/mobile']}), encoding='utf-8')
                print('PASS: permissions UI, persistence, filters, light/dark and desktop/mobile')
            finally:
                process.terminate()
                process.wait(timeout=15)


if __name__ == '__main__':
    run()
