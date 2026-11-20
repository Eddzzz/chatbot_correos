"""Audit screen QA in Edge using a temporary database and an isolated session."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def serve(folder, port):
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
    import django
    from django.conf import settings
    settings.DATABASES['default']['NAME'] = str(folder / 'accounts.sqlite3')
    settings.RESULT_DIR = folder / 'results'
    settings.SYSTEM_CONFIG_PATH = folder / 'system.json'
    django.setup()
    from django.core.management import call_command
    from django.contrib.auth import get_user_model
    from django.test import Client
    from postal.models import SystemAudit
    call_command('migrate', verbosity=0)
    user = get_user_model().objects.create_superuser('qa-auditoria')
    client = Client()
    client.force_login(user)
    (folder / 'session').write_text(client.cookies['sessionid'].value)
    for index in range(31):
        action = ['skill_toggle', 'user_update', 'catalog_activate', 'skill_delete'][index % 4]
        SystemAudit.objects.create(user=user, action=action, detail=[
            'Estadística descriptiva · Desactivada', 'operador-postal · Usuario · Activo',
            'Modelo de análisis postal', 'QA gráficas creadas 1794939981'][index % 4],
            metadata={'actor': user.username, 'ip': '127.0.0.1', 'method': 'POST',
                      'path': '/system/', 'resource': f'Recurso #{index + 1}', 'fields': ['enabled']})
    call_command('runserver', f'127.0.0.1:{port}', use_reloader=False)


def main():
    from playwright.sync_api import sync_playwright
    out = ROOT / '.runtime' / 'qa' / 'system-audit'
    out.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    with tempfile.TemporaryDirectory() as folder_name:
        folder = Path(folder_name)
        with (out / 'server.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen([sys.executable, __file__, '--serve', folder_name, str(port)], cwd=ROOT,
                stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                for _ in range(120):
                    try:
                        urllib.request.urlopen(base + '/accounts/login/', timeout=1)
                        break
                    except Exception:
                        if process.poll() is not None:
                            raise RuntimeError('QA server stopped; see server.log')
                        time.sleep(.15)
                with sync_playwright() as play:
                    browser = play.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
                    context = browser.new_context()
                    context.add_cookies([{'name': 'sessionid', 'value': (folder / 'session').read_text(), 'url': base}])
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    checks = []
                    for theme in ('light', 'dark'):
                        for width in (1440, 768, 390, 320):
                            page.set_viewport_size({'width': width, 'height': 1000})
                            page.goto(base + '/system/?view=audit')
                            page.evaluate('(theme) => {localStorage.setItem("postal-theme", theme); document.documentElement.dataset.theme=theme}', theme)
                            page.locator('.audit-table').wait_for()
                            assert page.locator('.audit-table tbody tr').count() == 25
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Overflow {theme} {width}'
                            page.screenshot(path=str(out / f'{theme}-{width}.png'), full_page=True)
                            checks.append(f'{theme} {width}px')
                    page.set_viewport_size({'width': 1440, 'height': 1000})
                    page.goto(base + '/system/?view=audit')
                    page.locator('.audit-details summary').first.click()
                    assert page.locator('.audit-details[open]').count() == 1
                    page.locator('#audit-search').fill('Estadística')
                    page.get_by_role('button', name='Filtrar', exact=True).click()
                    assert page.locator('.audit-table tbody tr').count() == 8
                    with page.expect_download() as download:
                        page.get_by_role('link', name='Exportar CSV').click()
                    assert download.value.suggested_filename == 'auditoria.csv'
                    page.goto(base + '/system/?view=audit&q=sin-coincidencias')
                    assert page.locator('.audit-empty').is_visible()
                    assert not errors, errors
                    browser.close()
                    report = {'viewports': checks, 'filters': True, 'details': True, 'csv': True, 'empty': True, 'javascript_errors': errors}
                    (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
                    print(json.dumps(report))
            finally:
                process.terminate()
                process.wait(timeout=15)


if __name__ == '__main__':
    if '--serve' in sys.argv:
        serve(Path(sys.argv[2]), sys.argv[3])
    else:
        main()
