"""Exercise skill settings in Edge against an isolated database and config file."""
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
    out = ROOT / '.runtime/qa/system-skills'
    out.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = str(probe.getsockname()[1])
    base = 'http://127.0.0.1:' + port
    password = secrets.token_urlsafe(24)
    errors = []
    with tempfile.TemporaryDirectory(prefix='skills-qa-', dir=ROOT / '.runtime') as folder:
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
                    page = browser.new_page(viewport={'width': 1565, 'height': 1000}, reduced_motion='reduce')
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base + '/accounts/login/')
                    page.locator('#id_username').fill('qa-admin')
                    page.locator('#id_password').fill(password)
                    page.locator('button[type=submit]').click()
                    page.wait_for_url(base + '/')
                    page.goto(base + '/system/?view=skills')
                    expect(page.locator('.skills-empty')).to_be_visible()
                    expect(page.locator('#skill-editor')).to_have_count(0)
                    expect(page.locator('.skills-preset')).to_have_count(14)
                    expect(page.locator('[data-skill-key="brief-explanations"]')).to_have_count(0)
                    for theme in ('light', 'dark'):
                        page.evaluate('(t) => document.documentElement.dataset.theme = t', theme)
                        for width in (1565, 1440, 1024, 768, 390, 320):
                            page.set_viewport_size({'width': width, 'height': 1000})
                            page.wait_for_timeout(700)
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (theme, width)
                            assert page.locator('.skills-workspace').evaluate('n => n.scrollWidth <= n.clientWidth'), (theme, width)
                            page.screenshot(path=str(out / f'empty-{theme}-{width}.png'), full_page=True)
                    page.set_viewport_size({'width': 1440, 'height': 1000})
                    page.get_by_role('link', name='Editar Gráficas de barras y líneas', exact=True).click()
                    expect(page.locator('#id_skill-name')).to_have_value('Gráficas de barras y líneas')
                    expect(page.locator('#id_skill-stage')).to_have_value('planner')
                    expect(page.locator('#id_skill-instructions')).to_contain_text('label_column')
                    page.locator('#id_skill-name').fill('Gráficas adaptadas')
                    page.locator('#id_skill-instructions').fill('INSTRUCCION_EDITADA_QA: usa barras verificadas.')
                    page.get_by_role('button', name='Guardar skill', exact=True).click()
                    expect(page.locator('#skill-editor')).to_have_count(0)
                    chart = page.locator('[data-skill-key="charts"]')
                    expect(chart).to_contain_text('Gráficas adaptadas')
                    expect(chart).to_contain_text('INSTRUCCION_EDITADA_QA')
                    chart.get_by_role('button', name='Desactivar Gráficas adaptadas', exact=True).click()
                    expect(chart.locator('.skills-status')).to_have_text('Inactiva')
                    page.reload()
                    expect(chart.locator('.skills-status')).to_have_text('Inactiva')
                    chart.get_by_role('button', name='Activar Gráficas adaptadas', exact=True).click()
                    expect(chart.locator('.skills-status')).to_have_text('Activa')
                    chart.get_by_role('link', name='Editar Gráficas adaptadas', exact=True).click()
                    expect(page.locator('#id_skill-instructions')).to_have_value('INSTRUCCION_EDITADA_QA: usa barras verificadas.')
                    page.get_by_role('link', name='Cerrar editor de skills').click()
                    page.on('dialog', lambda dialog: dialog.accept())
                    page.get_by_role('link', name='Nueva skill', exact=True).click()
                    page.get_by_role('link', name='Cerrar editor de skills').click()
                    expect(page.locator('#skill-editor')).to_have_count(0)
                    page.locator('#id_SKILL_PDF').uncheck()
                    page.get_by_role('button', name='Guardar configuración').click()
                    expect(page.locator('.system-feedback')).to_contain_text('Configuración guardada')
                    expect(page.locator('#id_SKILL_PDF')).not_to_be_checked()
                    page.get_by_role('link', name='Nueva skill', exact=True).click()
                    expect(page.locator('#skill-editor')).to_be_visible()
                    page.locator('#id_skill-name').fill('Resumen por sucursal')
                    page.locator('#id_skill-stage').select_option('both')
                    page.locator('#id_skill-instructions').fill('Agrupa los resultados por sucursal y explica las diferencias.')
                    page.get_by_role('button', name='Guardar skill', exact=True).click()
                    expect(page.locator('.skills-list')).to_contain_text('Resumen por sucursal')
                    expect(page.locator('.skills-count')).to_have_text('1')
                    page.get_by_role('link', name='Editar Resumen por sucursal').click()
                    expect(page.locator('#id_skill-name')).to_have_value('Resumen por sucursal')
                    page.locator('#id_skill-enabled').uncheck()
                    page.get_by_role('button', name='Guardar skill', exact=True).click()
                    expect(page.locator('.skills-list .skills-status')).to_have_text('Inactiva')
                    # Duplicate names surface server errors and retain submitted instructions.
                    expect(page.locator('#skill-editor')).to_have_count(0)
                    page.get_by_role('link', name='Nueva skill', exact=True).click()
                    page.locator('#id_skill-name').fill('Resumen por sucursal')
                    page.locator('#id_skill-stage').select_option('planner')
                    page.locator('#id_skill-instructions').fill('Texto que debe conservarse')
                    page.get_by_role('button', name='Guardar skill', exact=True).click()
                    expect(page.locator('.skills-editor .errorlist')).to_be_visible()
                    expect(page.locator('#id_skill-instructions')).to_have_value('Texto que debe conservarse')
                    page.goto(base + '/system/?view=skills')
                    page.get_by_role('link', name='Editar Resumen por sucursal').click()
                    page.locator('#id_skill-name').fill('Instrucción postal de nombre largo ' * 2)
                    for theme in ('light', 'dark'):
                        page.evaluate('(t) => document.documentElement.dataset.theme = t', theme)
                        for width in (1440, 390, 320):
                            page.set_viewport_size({'width': width, 'height': 1000})
                            page.wait_for_timeout(700)
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (theme, width)
                            page.screenshot(path=str(out / f'edit-{theme}-{width}.png'), full_page=True)
                    page.get_by_role('button', name='Eliminar Resumen por sucursal').click()
                    expect(page.locator('.skills-empty')).to_be_visible()
                    context = browser.new_context(java_script_enabled=False, storage_state=page.context.storage_state())
                    plain = context.new_page()
                    plain.goto(base + '/system/?view=skills')
                    expect(plain.locator('#skill-editor')).to_have_count(0)
                    plain.locator('[data-skill-key="charts"]').get_by_role('button', name='Desactivar Gráficas adaptadas').click()
                    expect(plain.locator('[data-skill-key="charts"] .skills-status')).to_have_text('Inactiva')
                    plain.get_by_role('link', name='Nueva skill', exact=True).click()
                    plain.locator('#id_skill-name').fill('Sin JavaScript')
                    plain.locator('#id_skill-stage').select_option('analyst')
                    plain.locator('#id_skill-instructions').fill('Usa los datos disponibles.')
                    plain.get_by_role('button', name='Guardar skill', exact=True).click()
                    expect(plain.locator('.skills-list')).to_contain_text('Sin JavaScript')
                    assert not errors, errors
                    browser.close()
                (out / 'result.json').write_text(json.dumps({'status': 'passed', 'themes': 2,
                    'widths': [1565, 1440, 1024, 768, 390, 320],
                    'checks': ['empty', 'editor-hidden', 'predefined-edit', 'enable-disable-persistence', 'cancel', 'settings-save', 'create', 'edit', 'validation', 'delete', 'no-js'],
                    'javascript_errors': errors}, indent=2), encoding='utf-8')
                print('PASS: skills CRUD, validation, capabilities, no-JS, both themes and 6 widths.')
            finally:
                process.terminate()
                process.wait(timeout=10)


if __name__ == '__main__':
    run()
