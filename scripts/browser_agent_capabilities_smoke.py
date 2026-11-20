"""Verify batch tracking and downloads in Edge using an isolated demo server."""
import csv
import io
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

from openpyxl import load_workbook
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'


def run():
    output = ROOT / '.runtime/qa/agent-capabilities'
    output.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = str(probe.getsockname()[1])
    base = 'http://127.0.0.1:' + port
    password = secrets.token_urlsafe(24)
    errors = []
    with tempfile.TemporaryDirectory(prefix='capabilities-qa-', dir=ROOT / '.runtime') as folder:
        with (output / 'server.log').open('w', encoding='utf-8') as log:
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
                    page.set_default_timeout(15000)
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base + '/accounts/login/')
                    page.locator('#id_username').fill('qa-admin')
                    page.locator('#id_password').fill(password)
                    page.locator('button[type=submit]').click()
                    page.wait_for_url(base + '/')
                    expect(page.locator('#question')).to_be_enabled()
                    page.locator('[data-view="tracking"]').click()
                    page.locator('#tracking-code').fill('BO-DEMO-001\nBO-DEMO-002\nNO-EXISTE')
                    page.locator('#tracking-service').select_option('EMS')
                    page.locator('#tracking-form button').click()
                    expect(page.locator('#tracking-results .report-panels')).to_be_visible()
                    expect(page.locator('#tracking-results')).to_contain_text('NO-EXISTE')
                    expect(page.locator('#tracking-results a[href*="/csv/"]')).to_have_count(3)
                    with page.expect_download() as download:
                        page.locator('#tracking-results a[href*="/csv/?panel=1"]').click()
                    csv_path = output / 'tracking.csv'
                    download.value.save_as(csv_path)
                    rows = list(csv.reader(io.StringIO(csv_path.read_text(encoding='utf-8-sig'))))
                    assert rows[1:]
                    assert all(row[1] == 'BO-DEMO-002' for row in rows[1:]), rows
                    with page.expect_download() as download:
                        page.locator('#tracking-results a[href*="/xlsx/"]').click()
                    xlsx_path = output / 'tracking.xlsx'
                    download.value.save_as(xlsx_path)
                    workbook = load_workbook(xlsx_path)
                    assert len(workbook.worksheets) == 3
                    assert workbook.worksheets[2].max_row == 1
                    workbook.close()
                    for theme in ('light', 'dark'):
                        page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                        for width in (1440, 768, 390, 320):
                            page.set_viewport_size({'width': width, 'height': 1000})
                            page.wait_for_timeout(150)
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (theme, width)
                            page.screenshot(path=str(output / f'tracking-{theme}-{width}.png'), full_page=True)
                    page.set_viewport_size({'width': 1440, 'height': 1000})
                    page.locator('[data-view="chat"]').click()
                    page.locator('#question').fill('Rastrea BO-DEMO-001, BO-DEMO-002')
                    page.locator('#chat-form .send').click()
                    expect(page.locator('#messages .report-panels')).to_be_visible()
                    expect(page.locator('#messages a[href*="/xlsx/"]')).to_have_count(1)
                    expect(page.locator('#messages')).to_contain_text('Elige un servicio para precisar su rastreo.')
                    expect(page.locator('#messages')).to_contain_text('histórico')
                    page.locator('#new-chat').click()
                    page.locator('#question').fill('Cuántos paquetes tengo en La Paz')
                    page.locator('#chat-form .send').click()
                    select = page.locator('#messages .csv-panel-select')
                    expect(select).to_be_visible()
                    assert select.locator('option').count() >= 2
                    select.select_option(index=1)
                    csv_link = page.locator('#messages a[href*="/csv/"]')
                    expect(csv_link).to_have_attribute('href', __import__('re').compile(r'panel=1$'))
                    with page.expect_download() as download:
                        csv_link.click()
                    download.value.save_as(output / 'compact-panel.csv')
                    page.goto(base + '/system/?view=skills')
                    expect(page.locator('.skills-capability')).to_have_count(8)
                    expect(page.locator('.skills-preset')).to_have_count(11)
                    for name in ('SKILL_CSV', 'SKILL_XLSX', 'SKILL_BULK_TRACKING'):
                        expect(page.locator('#id_' + name)).to_be_checked()
                    assert not errors, errors
                    browser.close()
                (output / 'result.json').write_text(json.dumps({'status': 'passed',
                    'checks': ['batch-form', 'batch-chat', 'csv-per-panel', 'excel-all-panels',
                               'empty-panel', 'ambiguity-notice', 'compact-panel-selector',
                               'capability-controls', 'both-themes', 'four-widths'],
                    'javascript_errors': errors}, indent=2), encoding='utf-8')
                print('PASS: batch form/chat, CSV panel download, Excel workbook, 8 controls, both themes and 4 widths.')
            finally:
                process.terminate()
                process.wait(timeout=10)


if __name__ == '__main__':
    run()
