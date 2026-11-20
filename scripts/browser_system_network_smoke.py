"""Network settings checks in Edge with a temporary database and config."""
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
    out = ROOT / '.runtime/qa/system-network'
    out.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = str(probe.getsockname()[1])
    base = 'http://127.0.0.1:' + port
    password = secrets.token_urlsafe(24)
    errors = []
    with tempfile.TemporaryDirectory(prefix='network-qa-', dir=ROOT / '.runtime') as folder:
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
                    page.goto(base + '/system/?view=network')
                    expect(page.locator('.network-workspace')).to_be_visible()
                    expect(page.locator('.network-config')).to_have_count(0)
                    expect(page.locator('.network-summary')).to_have_count(3)
                    for theme in ('light', 'dark'):
                        page.evaluate('(t) => document.documentElement.dataset.theme = t', theme)
                        for width in (1440, 1024, 768, 390, 320):
                            page.set_viewport_size({'width': width, 'height': 1000})
                            page.evaluate('() => { document.activeElement.blur(); scrollTo(0, 0); }')
                            page.wait_for_timeout(300)
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (theme, width)
                            page.screenshot(path=str(out / f'network-{theme}-{width}.png'), full_page=True, animations='disabled')
                    page.set_viewport_size({'width':1440,'height':1000})
                    page.get_by_role('link',name='Editar conexiones de IA',exact=True).click()
                    expect(page.locator('#id_AI_TIMEOUT')).to_be_visible()
                    expect(page.locator('#id_DB_CONNECT_TIMEOUT')).to_have_count(0)
                    for width in (1440,390,320):
                        page.set_viewport_size({'width':width,'height':1000})
                        page.evaluate('()=>{document.activeElement.blur();scrollTo(0,0)}')
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        page.screenshot(path=str(out/f'network-editor-{width}.png'),full_page=True,animations='disabled')
                    page.set_viewport_size({'width':1440,'height':1000})
                    page.locator('#id_AI_TIMEOUT').fill('180')
                    expect(page.locator('#network-dirty')).to_have_text('Cambios sin guardar')
                    page.get_by_role('link',name='Cancelar',exact=True).click()
                    expect(page.locator('.network-config')).to_have_count(0)
                    page.get_by_role('link',name='Editar conexiones de IA',exact=True).click()
                    expect(page.locator('#id_AI_TIMEOUT')).to_have_value('120')
                    page.locator('#id_AI_TIMEOUT').fill('180')
                    page.get_by_role('button',name='Guardar cambios',exact=True).click()
                    expect(page.locator('.network-config')).to_have_count(0)
                    expect(page.locator('.network-summary')).to_contain_text(['Demostración','180 s','10 s'])
                    page.get_by_role('link',name='Editar conexión PostgreSQL',exact=True).click()
                    expect(page.locator('#id_AI_TIMEOUT')).to_have_count(0)
                    page.locator('#id_DB_CONNECT_TIMEOUT').fill('30')
                    page.get_by_role('button',name='Restablecer tiempos',exact=True).click()
                    expect(page.locator('#id_DB_CONNECT_TIMEOUT')).to_have_value('10')
                    page.get_by_role('link',name='Cancelar',exact=True).click()
                    page.get_by_role('link',name='Editar origen postal',exact=True).click()
                    url = page.locator('#id_BUSINESS_DATABASE_URL')
                    url.fill('postgresql://qa:private-draft@localhost/postal')
                    page.get_by_role('button',name='Mostrar',exact=True).click()
                    expect(url).to_have_attribute('type','text')
                    page.get_by_role('button',name='Comprobar conexión guardada',exact=True).click()
                    expect(page.locator('.network-result')).to_contain_text('Conexión correcta',timeout=20000)
                    expect(url).to_have_value('postgresql://qa:private-draft@localhost/postal')
                    page.get_by_role('link',name='Cancelar',exact=True).click()
                    context=browser.new_context(java_script_enabled=False)
                    context.add_cookies(page.context.cookies())
                    basic=context.new_page()
                    basic.goto(base+'/system/?view=network')
                    expect(basic.locator('.network-config')).to_have_count(0)
                    basic.get_by_role('link',name='Editar conexiones de IA',exact=True).click()
                    basic.locator('#id_AI_TIMEOUT').fill('200')
                    basic.get_by_role('button',name='Guardar cambios',exact=True).click()
                    expect(basic.locator('.network-config')).to_have_count(0)
                    basic.get_by_role('link',name='Editar conexiones de IA',exact=True).click()
                    expect(basic.locator('#id_AI_TIMEOUT')).to_have_value('200')
                    context.close()
                    assert not errors, errors
                    browser.close()
                (out / 'result.json').write_text(json.dumps({'passed': True, 'errors': errors,
                    'widths': [1440, 1024, 768, 390, 320], 'themes': ['light', 'dark']}, indent=2), encoding='utf-8')
                print('Network browser checks passed; screenshots in ' + str(out))
            finally:
                process.terminate()
                process.wait(timeout=15)


if __name__ == '__main__':
    run()
