"""Exercise agent settings in Edge against an isolated database and config file."""
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
    out = ROOT / '.runtime/qa/system-agents'
    out.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = str(probe.getsockname()[1])
    base = 'http://127.0.0.1:' + port
    password = secrets.token_urlsafe(24)
    errors = []
    with tempfile.TemporaryDirectory(prefix='agents-qa-', dir=ROOT / '.runtime') as folder:
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
                    page = browser.new_page(viewport={'width': 1440, 'height': 1100})
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base + '/accounts/login/')
                    page.locator('#id_username').fill('qa-admin')
                    page.locator('#id_password').fill(password)
                    page.locator('button[type=submit]').click()
                    page.wait_for_url(base + '/')
                    page.goto(base + '/system/?view=agents')
                    expect(page.locator('textarea, input[type=checkbox], input[type=number], input[type=range]')).to_have_count(0)
                    expect(page.locator('[data-save]')).to_have_count(0)
                    for theme in ('light', 'dark'):
                        page.evaluate('(t)=>document.documentElement.dataset.theme=t',theme)
                        for width in (1440,768,390,320):
                            page.set_viewport_size({'width':width,'height':1100})
                            page.evaluate('()=>{document.activeElement.blur();scrollTo(0,0)}')
                            page.wait_for_timeout(350)
                            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(theme,width)
                            page.screenshot(path=str(out/f'readonly-{theme}-{width}.png'),full_page=True,animations='disabled')
                    page.set_viewport_size({'width':1440,'height':1100})
                    page.get_by_role('link',name='Editar planificador',exact=True).click()
                    planner=page.locator('#id_PLANNER_INSTRUCTIONS')
                    save=page.locator('[data-save]')
                    expect(save).to_be_disabled()
                    expect(page.locator('#id_ANALYST_INSTRUCTIONS, #id_AI_MAX_TOKENS')).to_have_count(0)
                    page.get_by_role('button',name='Fechas y sucursales',exact=True).click()
                    assert 'Prioriza' in planner.input_value()
                    page.get_by_role('button',name='Fechas y sucursales',exact=True).click()
                    assert planner.input_value().count('Prioriza')==1
                    planner.fill('x'*4000)
                    page.get_by_role('button',name='Fechas y sucursales',exact=True).click()
                    expect(planner).to_have_value('x'*4000)
                    expect(page.locator('[data-save-state]')).to_contain_text('supera los 4.000')
                    page.get_by_role('link',name='Cancelar',exact=True).click()
                    expect(page.locator('textarea')).to_have_count(0)
                    page.get_by_role('link',name='Editar planificador',exact=True).click()
                    expect(planner).to_have_value('')
                    planner.fill('Instrucción conservada al desactivar.')
                    page.locator('#id_PLANNER_ENABLED').uncheck()
                    expect(planner).to_have_attribute('readonly','')
                    expect(page.locator('[data-preview-planner]')).to_contain_text('Inactivo')
                    save.click()
                    expect(page.locator('[data-save]')).to_have_count(0)
                    expect(page.locator('.agent-editor').first).to_contain_text('Instrucción conservada')
                    page.get_by_role('link',name='Editar analista',exact=True).click()
                    expect(page.locator('#id_PLANNER_INSTRUCTIONS')).to_have_count(0)
                    page.locator('#id_ANALYST_INSTRUCTIONS').fill('Resume los resultados.')
                    page.locator('[data-save]').click()
                    page.get_by_role('link',name='Editar presupuesto',exact=True).click()
                    expect(page.locator('textarea,input[type=checkbox]')).to_have_count(0)
                    page.locator('[data-tokens="6000"]').click()
                    expect(page.locator('#id_AI_MAX_TOKENS')).to_have_value('6000')
                    expect(page.locator('#agent-token-range')).to_have_value('6000')
                    expect(page.locator('[data-tokens="6000"]')).to_have_attribute('aria-pressed','true')
                    page.locator('#agent-token-range').fill('4257')
                    expect(page.locator('#id_AI_MAX_TOKENS')).to_have_value('4257')
                    page.locator('#id_AI_MAX_TOKENS').fill('255')
                    expect(page.locator('[data-preview-budget]')).to_have_text('Revisa el límite')
                    page.locator('[data-tokens="3000"]').click()
                    for theme in ('light','dark'):
                        page.evaluate('(t)=>document.documentElement.dataset.theme=t',theme)
                        for width in (1440,768,390,320):
                            page.set_viewport_size({'width':width,'height':1100})
                            page.evaluate('()=>{document.activeElement.blur();scrollTo(0,0)}')
                            page.wait_for_timeout(350)
                            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(theme,width)
                            page.screenshot(path=str(out/f'editor-{theme}-{width}.png'),full_page=True,animations='disabled')
                    page.locator('[data-tokens="6000"]').click()
                    page.locator('[data-save]').click()
                    expect(page.locator('[data-save]')).to_have_count(0)
                    assert json.loads((Path(folder)/'system.json').read_text())['AI_MAX_TOKENS']==6000
                    context=browser.new_context(java_script_enabled=False,storage_state=page.context.storage_state())
                    plain=context.new_page()
                    plain.goto(base+'/system/?view=agents')
                    expect(plain.locator('textarea')).to_have_count(0)
                    plain.get_by_role('link',name='Editar presupuesto',exact=True).click()
                    plain.locator('#id_AI_MAX_TOKENS').fill('512')
                    plain.locator('[data-save]').click()
                    expect(plain.locator('[data-save]')).to_have_count(0)
                    assert json.loads((Path(folder)/'system.json').read_text())['AI_MAX_TOKENS']==512
                    context.close()
                    assert not errors, errors
                    browser.close()
                (out / 'result.json').write_text(json.dumps({'status': 'passed', 'themes': 2, 'widths': [1440, 768, 390, 320],
                    'checks': ['examples', 'toggles', 'presets', 'range', 'cancel', 'readonly', 'section-save', 'validation', 'persistence', 'no-js'],
                    'javascript_errors': errors}, indent=2), encoding='utf-8')
                print('PASS: agent interactions, persistence, validation, no-JS, both themes and 4 widths.')
            finally:
                process.terminate()
                process.wait(timeout=10)


if __name__ == '__main__':
    run()
