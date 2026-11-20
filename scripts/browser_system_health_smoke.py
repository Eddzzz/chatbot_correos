"""Check the health screen with an isolated database in Edge."""
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

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'


def run():
    out = ROOT / '.runtime/qa/system-health'
    out.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = str(probe.getsockname()[1])
    base = 'http://127.0.0.1:' + port
    password = secrets.token_urlsafe(24)
    errors = []
    with tempfile.TemporaryDirectory(prefix='health-qa-', dir=ROOT / '.runtime') as folder:
        with (out / 'server.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen([sys.executable, str(ROOT / 'scripts/browser_system_management_smoke.py'),
                '--serve', folder, port], cwd=ROOT, env={**os.environ, 'SYSTEM_QA_PASSWORD': password},
                stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                for _ in range(100):
                    try:
                        urllib.request.urlopen(base + '/accounts/login/', timeout=1)
                        break
                    except Exception:
                        if process.poll() is not None:
                            raise RuntimeError('QA server failed; see server.log')
                        time.sleep(.15)
                with sync_playwright() as play:
                    browser = play.chromium.launch(headless=True, executable_path=EDGE)
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base + '/accounts/login/')
                    page.locator('#id_username').fill('qa-admin')
                    page.locator('#id_password').fill(password)
                    page.locator('button[type=submit]').click()
                    page.wait_for_url(base + '/')
                    page.goto(base + '/system/?view=health')
                    expect(page.locator('.health-summary>div')).to_have_count(4)
                    expect(page.locator('.health-table tbody tr')).to_have_count(2)
                    for theme in ('light', 'dark'):
                        page.evaluate('(t) => document.documentElement.dataset.theme = t', theme)
                        for width in (1920, 1587, 1440, 1280, 1100, 1024, 768, 701, 700, 390, 320):
                            page.set_viewport_size({'width': width, 'height': 1000})
                            page.wait_for_timeout(650)
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (theme, width)
                            assert page.locator('.health-workspace').evaluate('n => n.scrollWidth <= n.clientWidth'), (theme, width)
                            assert page.locator('.health-table-wrap').evaluate('n => n.scrollWidth <= n.clientWidth'), (theme, width, 'table overflows')
                            page.screenshot(path=str(out / f'health-{theme}-{width}.png'), full_page=True)
                    page.set_viewport_size({'width': 1440, 'height': 1000})
                    page.get_by_role('link', name='Ver conversaciones de qa-user', exact=True).click()
                    expect(page.locator('#system-view-title')).to_have_text('Conversaciones')
                    page.goto(base + '/system/?view=health')
                    page.get_by_role('button', name='Comprobar conexión DB', exact=True).click()
                    expect(page.locator('.health-panel [role=status]')).to_be_visible()
                    page.on('dialog', lambda dialog: dialog.accept())
                    page.get_by_role('button', name='Limpiar caché vencida', exact=True).click()
                    expect(page.locator('.system-feedback')).to_contain_text('Caché limpiada')
                    browser.close()
                assert not errors, errors
                (out / 'result.json').write_text(json.dumps({'themes': 2, 'widths': 11,
                    'checks': ['summary', 'users', 'layout', 'conversations', 'database check', 'cleanup'],
                    'errors': errors}, indent=2), encoding='utf-8')
                print('Health browser checks passed:', out)
            finally:
                process.terminate()
                process.wait(timeout=10)


if __name__ == '__main__':
    run()
