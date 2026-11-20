"""Isolated real-browser check of administration, chat sync and trash; no live AI calls."""
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'


def serve(folder, port):
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
    os.environ.update({key: '' for key in ('GROQ_API_KEY', 'GROQ_BACKUP_API_KEY', 'OPENROUTER_API_KEY', 'NVIDIA_API_KEY', 'CLOUDFLARE_API_TOKEN')})
    os.environ['AI_PROVIDER'] = 'groq'
    import django
    from django.conf import settings
    settings.DATABASES['default']['NAME'] = str(folder / 'accounts.sqlite3')
    settings.RESULT_DIR = folder / 'results'
    settings.SYSTEM_CONFIG_PATH = folder / 'system.json'
    settings.JOBS_EAGER = True
    settings.DATA_MODE = 'demo'
    django.setup()
    from django.core.management import call_command
    from django.contrib.auth import get_user_model
    call_command('migrate', verbosity=0)
    users = get_user_model()
    users.objects.create_superuser('qa-admin', password=os.environ['SYSTEM_QA_PASSWORD'])
    users.objects.create_user('qa-user', password=os.environ['SYSTEM_QA_PASSWORD'])
    # Synthetic usage exists only in this temporary QA database, never in the user's DB.
    from datetime import timedelta
    from django.utils import timezone
    from postal.models import AIUsage
    for day in range(30):
        for stage, account in [('planner', 1), ('analyst', 2)]:
            prompt = 1200 + (day * 223) % 1400
            completion = 200 + (day * 61) % 500
            usage = AIUsage.objects.create(user_id=account, provider='Groq', model='openai/gpt-oss-120b',
                stage=stage, prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion)
            AIUsage.objects.filter(pk=usage.pk).update(created_at=timezone.now() - timedelta(days=day))
    call_command('runserver', '127.0.0.1:' + port, use_reloader=False, verbosity=0)


def run():
    from playwright.sync_api import sync_playwright, expect
    out = ROOT / '.runtime/qa/system-management'
    out.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = str(probe.getsockname()[1])
    base = 'http://127.0.0.1:' + port
    password = secrets.token_urlsafe(24)
    checks, errors = [], []
    with tempfile.TemporaryDirectory(prefix='system-qa-', dir=ROOT / '.runtime') as folder:
        with (out / 'server.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen([sys.executable, __file__, '--serve', folder, port], cwd=ROOT,
                env={**os.environ, 'SYSTEM_QA_PASSWORD': password}, stdout=log, stderr=log,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                for _ in range(100):
                    try:
                        urllib.request.urlopen(base + '/accounts/login/', timeout=1)
                        break
                    except Exception:
                        if process.poll() is not None:
                            raise RuntimeError('El servidor de QA no pudo iniciar; revise server.log.')
                        time.sleep(.15)
                with sync_playwright() as play:
                    browser = play.chromium.launch(headless=True, executable_path=EDGE)
                    context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                    page = context.new_page()
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    def login(tab, username):
                        tab.goto(base + '/accounts/login/')
                        tab.locator('#id_username').fill(username)
                        tab.locator('#id_password').fill(password)
                        tab.locator('button[type=submit]').click()
                        tab.wait_for_url(base + '/')
                        expect(tab.locator('#question')).to_be_enabled()
                    login(page, 'qa-admin')
                    page.add_init_script('''
                        window.dashboardMotionCalls = [];
                        const animate = Element.prototype.animate;
                        Element.prototype.animate = function (...args) {
                            window.dashboardMotionCalls.push({card:this.matches('.bento-cell'), chart:!!this.closest('.dashboard-chart')});
                            return animate.apply(this, args);
                        };
                    ''')
                    page.goto(base + '/system/')
                    page.wait_for_function('() => dashboardMotionCalls.some(call => call.card) && dashboardMotionCalls.some(call => call.chart)', timeout=3000)
                    page.wait_for_timeout(1100)
                    expect(page.locator('.dashboard-period')).to_have_count(0)
                    before = page.evaluate("JSON.parse(document.getElementById('dashboard-data').textContent).totals.tokens")
                    page.locator('.dashboard-data-table summary').click()
                    page.locator('.dashboard-data-table summary').blur()
                    page.evaluate('window.dashboardPageMarker = true')
                    with sqlite3.connect(Path(folder) / 'accounts.sqlite3') as db:
                        db.execute('UPDATE postal_aiusage SET total_tokens = total_tokens + 123 WHERE id = (SELECT id FROM postal_aiusage ORDER BY created_at DESC LIMIT 1)')
                    db.close()
                    page.wait_for_function("expected => JSON.parse(document.getElementById('dashboard-data').textContent).totals.tokens === expected", arg=before + 123, timeout=10000)
                    assert page.evaluate('window.dashboardPageMarker === true')
                    expect(page.locator('.dashboard-data-table')).to_have_attribute('open', '')
                    expect(page.locator('#tokens-chart svg')).to_be_visible()
                    page.locator('.dashboard-data-table summary').click()
                    checks.append('Actualización automática de consumo real sin recarga, conservando detalles y gráficos')
                    for value in page.locator('.kpi-big-num[data-number]').all():
                        if value.get_attribute('data-number') == '':
                            assert value.inner_text() == '—'
                            continue
                        assert value.inner_text() == page.evaluate("value => new Intl.NumberFormat('es-BO', {maximumFractionDigits:0}).format(Number(value))", value.get_attribute('data-number'))
                    expect(page.locator('#available-tokens')).to_have_text('—')
                    expect(page.get_by_text('Sin reporte de cuota.', exact=False)).to_be_visible()
                    quiet = context.new_page()
                    quiet.emulate_media(reduced_motion='reduce')
                    quiet.goto(base + '/system/')
                    expect(quiet.locator('#tokens-chart svg')).to_be_visible()
                    assert quiet.locator('.bento-cell').evaluate_all('(cards) => cards.every(card => card.getAnimations({subtree:true}).length === 0)')
                    quiet.close()
                    expect(page.get_by_role('heading', name='Resumen y analíticas')).to_be_visible()
                    expect(page.locator('.system-topbar h1')).to_have_text('Resumen y analíticas')
                    expect(page.locator('#system-content h1')).to_have_count(0)
                    expect(page.locator('.system-topbar p')).to_have_count(0)
                    expect(page.locator('.system-topbar .system-kicker')).to_have_count(0)
                    expect(page.locator('#system-sidebar #system-collapse')).to_have_count(1)
                    expect(page.locator('.system-topbar #system-collapse')).to_have_count(0)
                    expect(page.locator('#system-sidebar .system-sidebar-tools #system-theme')).to_be_visible()
                    expect(page.locator('.system-topbar #system-theme')).to_have_count(0)
                    initial_theme = page.locator('html').get_attribute('data-theme')
                    page.locator('#system-theme').click()
                    expect(page.locator('html')).to_have_attribute('data-theme', 'light' if initial_theme == 'dark' else 'dark')
                    page.locator('#system-theme').click()
                    page.evaluate('window.scrollTo(0, 600)')
                    assert page.locator('.system-topbar').evaluate('(el) => Math.abs(el.getBoundingClientRect().top - 14) < 1')
                    page.evaluate('window.scrollTo(0, 0)')
                    expect(page.locator('#tokens-chart svg')).to_be_visible()
                    page.locator('#system-collapse').click()
                    expect(page.locator('#system-collapse')).to_have_attribute('aria-expanded', 'false')
                    expect(page.locator('#system-sidebar')).to_have_css('width', '64px')
                    expect(page.locator('.system-brand-letter')).to_be_visible()
                    expect(page.locator('.system-brand-full')).to_be_hidden()
                    page.locator('#system-sidebar').screenshot(path=str(out / 'sidebar-collapsed-letter.png'))
                    expect(page.locator('.system-users-link')).to_have_attribute('title', 'Gestión de usuarios')
                    # The saved width must apply even before the deferred UI script runs.
                    initial_nav = context.new_page()
                    initial_nav.route('**/postal/system.js*', lambda route: route.abort())
                    for destination in ('overview', 'agents', 'users'):
                        initial_nav.goto(base + '/system/?view=' + destination)
                        assert initial_nav.locator('html').get_attribute('data-admin-nav') == 'collapsed', destination
                        assert initial_nav.locator('#system-sidebar').evaluate('(el) => el.getBoundingClientRect().width') == 64, destination
                    initial_nav.close()
                    page.locator('.system-users-link').click()
                    expect(page.locator('h1')).to_have_text('Usuarios')
                    expect(page.get_by_role('link', name='Ver resumen', exact=True)).to_have_count(0)
                    directory_lefts = page.locator('.users-directory').evaluate('(directory) => [".users-directory-heading h2", ".users-directory-count", ".users-table th:first-child", ".users-table .users-identity"].map(selector => directory.querySelector(selector).getBoundingClientRect().left)')
                    assert max(directory_lefts) - min(directory_lefts) < 1, directory_lefts
                    expect(page.locator('#system-sidebar')).to_have_css('width', '64px')
                    page.reload()
                    expect(page.locator('#system-collapse')).to_have_attribute('aria-expanded', 'false')
                    page.set_viewport_size({'width':390,'height':844})
                    expect(page.locator('#system-collapse')).to_be_hidden()
                    page.locator('#system-menu').click()
                    expect(page.locator('#system-sidebar')).to_have_css('width', '280px')
                    expect(page.locator('#system-theme')).to_be_visible()
                    expect(page.locator('.system-brand-full')).to_be_visible()
                    expect(page.locator('.system-chat-shortcut > span')).to_be_visible()
                    page.keyboard.press('Escape')
                    page.set_viewport_size({'width':1440,'height':1000})
                    expect(page.locator('#system-sidebar')).to_have_css('width', '64px')
                    page.locator('#system-collapse').press('Enter')
                    expect(page.locator('#system-sidebar')).to_have_css('width', '280px')
                    expect(page.locator('.system-brand-letter')).to_be_hidden()
                    checks.append('Barra contraíble: iconos con nombres, preferencia persistida, teclado y menú móvil completo')
                    if '--catalog-only' not in sys.argv:
                        page.goto(base + '/system/?view=agents')
                        page.locator('#id_AI_MAX_TOKENS').fill('768')
                        page.get_by_role('button', name='Guardar configuración', exact=True).click()
                        expect(page.locator('#id_AI_MAX_TOKENS')).to_have_value('768')
                    page.goto(base + '/system/?view=models')
                    expect(page.locator('.catalog-workspace')).to_be_visible()
                    expect(page.locator('.catalog-workspace details')).to_have_count(0)
                    expect(page.locator('.catalog-provider')).to_have_count(0)
                    expect(page.locator('.catalog-selection-empty')).to_have_count(0)
                    expect(page.get_by_role('heading', name='Orden de uso de los modelos', exact=True)).to_be_visible()
                    page.get_by_role('link', name='Seleccionar Groq', exact=True).click()
                    expect(page.locator('.catalog-provider')).to_have_count(1)
                    expect(page.get_by_role('link', name='Seleccionar Groq', exact=True)).to_have_attribute('aria-expanded', 'true')
                    page.get_by_role('link', name='Seleccionar Groq', exact=True).click()
                    expect(page.locator('.catalog-provider')).to_have_count(0)
                    expect(page.get_by_role('link', name='Seleccionar Groq', exact=True)).to_have_attribute('aria-expanded', 'false')
                    page.get_by_role('link', name='Seleccionar Groq', exact=True).click()
                    expect(page.locator('.catalog-provider')).to_have_count(1)
                    groq = page.locator('.catalog-provider').filter(has=page.get_by_text('Groq', exact=True))
                    groq.get_by_role('link', name='Agregar clave', exact=True).click()
                    page.locator('#id_name').fill('Clave de QA')
                    page.locator('#id_secret').fill('qa-private-key')
                    page.locator('#catalog-form button[type=submit]').click()
                    assert 'qa-private-key' not in page.content()
                    page.get_by_role('link', name='Agregar proveedor', exact=True).click()
                    page.locator('#id_name').fill('Servicio de QA')
                    page.locator('#id_endpoint').fill('https://example.com/v1/chat/completions')
                    page.locator('#catalog-form button[type=submit]').click()
                    custom = page.locator('.catalog-provider').filter(has=page.get_by_text('Servicio de QA', exact=True))
                    expect(custom).to_be_visible()
                    for name, identifier in [('Rápido', 'qa-fast'), ('Preciso', 'qa-precise')]:
                        custom.get_by_role('link', name='Agregar modelo', exact=True).click()
                        page.locator('#id_name').fill(name)
                        page.locator('#id_identifier').fill(identifier)
                        if identifier == 'qa-precise':
                            page.locator('#id_fallback_enabled').check()
                            page.locator('#id_priority').fill('2')
                        page.locator('#catalog-form button[type=submit]').click()
                    expect(custom.get_by_role('button', name='Usar modelo').first).to_be_disabled()
                    for name, secret in [('Principal QA', 'qa-catalog-secret'), ('Respaldo QA', 'qa-backup-secret')]:
                        custom.get_by_role('link', name='Agregar clave', exact=True).click()
                        page.locator('#id_name').fill(name)
                        page.locator('#id_secret').fill(secret)
                        page.locator('#catalog-form button[type=submit]').click()
                        assert secret not in page.content()
                    custom.locator('.catalog-row').filter(has=page.get_by_text('Rápido', exact=True)).get_by_role('button', name='Usar modelo').click()
                    expect(page.locator('.catalog-current')).to_contain_text('Servicio de QA')
                    expect(page.locator('.catalog-current')).to_contain_text('qa-fast')
                    expect(page.locator('.catalog-chain li').first).to_contain_text('Rápido')
                    expect(page.locator('.catalog-chain li').nth(1)).to_contain_text('Preciso')
                    expect(page.locator('.catalog-chain-hint')).to_have_count(0)
                    page.get_by_role('button', name='Reordenar', exact=True).click()
                    order_rows = page.locator('#catalog-sort-list [data-model-id]')
                    order_rows.nth(1).locator('.catalog-drag-handle').drag_to(order_rows.first, target_position={'x':80,'y':3})
                    expect(page.locator('#catalog-order-status')).to_contain_text('Orden guardado')
                    expect(order_rows.first).to_contain_text('Preciso')
                    page.reload()
                    expect(page.locator('.catalog-current')).to_contain_text('qa-precise')
                    page.get_by_role('button', name='Reordenar', exact=True).click()
                    order_rows.first.locator('.catalog-drag-handle').press('ArrowDown')
                    expect(page.locator('#catalog-order-status')).to_contain_text('Orden guardado')
                    expect(order_rows.first).to_contain_text('Rápido')
                    def reject_order(route):
                        if route.request.method == 'POST' and 'catalog_reorder' in (route.request.post_data or ''):
                            route.fulfill(status=500, content_type='application/json', body='{"error":"No se pudo guardar el orden."}')
                        else:
                            route.continue_()
                    page.route('**/system/**', reject_order)
                    order_rows.nth(1).locator('.catalog-drag-handle').press('ArrowUp')
                    expect(page.locator('#catalog-order-status')).to_contain_text('No se pudo guardar')
                    expect(order_rows.first).to_contain_text('Rápido')
                    page.unroute('**/system/**', reject_order)
                    page.get_by_role('button', name='Terminar edición', exact=True).click()
                    expect(page.locator('.catalog-current')).to_contain_text('qa-fast')
                    expect(page.locator('.catalog-chain li').nth(1)).to_contain_text('Respaldo 1')
                    page.get_by_role('link', name='Agregar respaldo', exact=True).click()
                    expect(page.locator('#catalog-editor')).to_be_visible()
                    expect(page.locator('#catalog-form select')).to_have_count(0)
                    page.locator('.catalog-backup-option').filter(has_text='Preciso').locator('input[type=radio]').check()
                    expect(page.locator('#id_priority')).to_be_hidden()
                    expect(page.locator('#backup-preview-new')).to_contain_text('Preciso')
                    for theme in ('light', 'dark'):
                        page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
                        for width in (1440,390,320):
                            page.set_viewport_size({'width':width,'height':1000})
                            assert page.locator('#catalog-editor').evaluate('el => el.scrollWidth <= el.clientWidth')
                    page.locator('#catalog-form button[type=submit]').click()
                    expect(page.locator('.system-feedback')).to_contain_text('Respaldo agregado')
                    expect(page.locator('.catalog-chain li').nth(1)).to_contain_text('Preciso')
                    for theme in ('light', 'dark'):
                        page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
                        for width in (1440, 768, 390, 320):
                            page.set_viewport_size({'width': width, 'height': 1000})
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), ('models', theme, width)
                            page.screenshot(path=str(out / f'models-{theme}-{width}.png'), full_page=True, animations='disabled')
                    page.set_viewport_size({'width': 1440, 'height': 1000})
                    custom.get_by_role('link', name='Editar / reemplazar', exact=True).first.click()
                    expect(page.locator('#id_secret')).to_have_value('')
                    assert 'qa-catalog-secret' not in page.content()
                    for theme in ('light', 'dark'):
                        page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
                        for width in (1440,390,320):
                            page.set_viewport_size({'width':width,'height':1000})
                            assert page.locator('#catalog-editor').evaluate('el => el.scrollWidth <= el.clientWidth')
                            if width != 320:
                                page.screenshot(path=str(out / f'model-key-dialog-{theme}-{width}.png'))
                    page.locator('#catalog-form button[type=submit]').click()
                    page.get_by_role('link', name='Seleccionar Groq', exact=True).click()
                    groq = page.locator('.catalog-provider').filter(has=page.get_by_text('Groq', exact=True))
                    groq.get_by_role('button', name='Usar modelo', exact=True).click()
                    expect(page.locator('.catalog-current')).to_contain_text('Groq')
                    checks.append('Gestor de proveedores: alta, dos modelos, dos claves, activación real, edición sin revelar secretos y ambos temas')
                    if '--catalog-only' in sys.argv:
                        assert not errors, errors
                        browser.close()
                        print(json.dumps({'checks': checks, 'javascript_errors': errors, 'live_ai_calls': False}, ensure_ascii=False))
                        return
                    page.goto(base + '/system/?view=skills')
                    page.locator('#id_skill-name').fill('Resumen QA')
                    page.locator('#id_skill-stage').select_option('analyst')
                    page.locator('#id_skill-instructions').fill('Prioriza las cifras verificadas.')
                    page.locator('#id_skill-enabled').check()
                    page.get_by_role('button', name='Guardar skill', exact=True).click()
                    expect(page.locator('#custom-skills table')).to_contain_text('Resumen QA')
                    checks.append('Creación de skill asignada al analista')
                    page.goto(base + '/system/?view=health')
                    page.get_by_role('button', name='Comprobar conexión DB').click()
                    expect(page.locator('#health')).to_contain_text('Conexión correcta')
                    checks.append('Diagnóstico de cuentas y origen demo')
                    page.goto(base + '/system/')
                    def export_taste_snapshot(snapshot_name='overview'):
                        import base64
                        import re
                        html = page.content()
                        css = '\n'.join((ROOT / path).read_text(encoding='utf-8') for path in ('static/postal/app.css', 'static/postal/system.css', 'static/postal/system-bento.css', 'static/postal/system-reference.css'))
                        if snapshot_name == 'users':
                            css += '\n' + (ROOT / 'static/postal/system-users.css').read_text(encoding='utf-8')
                        jakarta = base64.b64encode((ROOT / 'static/fonts/plus-jakarta-sans.ttf').read_bytes()).decode()
                        css = css.replace('/static/fonts/plus-jakarta-sans.ttf', 'data:font/ttf;base64,' + jakarta)
                        for name in ('regular', 'medium', 'bold'):
                            data = base64.b64encode((ROOT / f'static/fonts/geist-{name}.ttf').read_bytes()).decode()
                            css = css.replace(f"/static/fonts/geist-{name}.ttf", 'data:font/ttf;base64,' + data)
                        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', '', html)
                        html = re.sub(r'<script[^>]+src="[^"]+"[^>]*></script>', '', html)
                        html = html.replace('</head>', '<style>' + css + '</style></head>')
                        logo = base64.b64encode((ROOT / 'static/postal/assets/correos-bolivia.png').read_bytes()).decode()
                        html = re.sub(r'src="/static/postal/assets/correos-bolivia.png[^\"]*"', 'src="data:image/png;base64,' + logo + '"', html)
                        scripts = '\n'.join((ROOT / path).read_text(encoding='utf-8') for path in ('static/postal/system-charts.js', 'static/postal/system.js'))
                        html = html.replace('</body>', '<script>' + scripts + '</script></body>')
                        html = html.replace('Actividad del asistente y operación de Correos de Bolivia.', 'Datos sintéticos de validación · Correos de Bolivia.')
                        (out / ('taste-' + snapshot_name + '.html')).write_text(html, encoding='utf-8')
                    expect(page.locator('#tokens-chart svg')).to_be_visible()
                    export_taste_snapshot()
                    for theme in ('light', 'dark'):
                        page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
                        for width in (1440, 768, 390, 320):
                            page.set_viewport_size({'width': width, 'height': 920})
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (theme, width)
                            if width in (1440, 390):
                                page.screenshot(path=str(out / f'admin-{theme}-{width}.png'), full_page=True)
                    page.goto(base + '/system/?view=analytics')
                    page.locator('#analytics-days').select_option('custom')
                    expect(page.locator('#analytics-custom')).to_be_visible()
                    page.locator('[name=start]').fill('2026-01-10')
                    page.locator('[name=end]').fill('2026-01-12')
                    page.get_by_role('button', name='Aplicar', exact=True).click()
                    expect(page.locator('#analytics-days')).to_have_value('custom')
                    expect(page.locator('[name=start]')).to_have_value('2026-01-10')
                    assert len(page.locator('#dashboard-data').text_content()) > 0
                    assert len(page.evaluate("JSON.parse(document.getElementById('dashboard-data').textContent).daily")) == 3
                    with page.expect_response(lambda response: 'live=1' in response.url and response.ok):
                        page.wait_for_timeout(3500)
                    expect(page.locator('[name=end]')).to_have_value('2026-01-12')
                    for theme in ('light', 'dark'):
                        page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
                        for width in (1440, 768, 390, 320):
                            page.set_viewport_size({'width': width, 'height': 920})
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), ('custom', theme, width)
                            page.screenshot(path=str(out / f'custom-range-{theme}-{width}.png'))
                    page.locator('#analytics-days').select_option('30')
                    expect(page.locator('#analytics-custom')).to_be_hidden()
                    expect(page.locator('[name=start]')).to_be_disabled()
                    checks.append('Rango personalizado: fechas inclusivas, persistencia al actualizar, ambos temas y cuatro anchos')
                    page.locator('#analytics-days').select_option('7')
                    page.get_by_role('button', name='Aplicar', exact=True).click()
                    expect(page.locator('#analytics-days')).to_have_value('7')
                    expect(page.locator('#calls-chart svg')).to_be_visible()
                    page.locator('#system-menu').click()
                    expect(page.locator('#system-sidebar')).to_have_class('system-sidebar is-open')
                    page.keyboard.press('Escape')
                    expect(page.locator('#system-menu')).to_have_attribute('aria-expanded', 'false')
                    checks.append('Dashboard, filtro de período, dos gráficos y menú móvil accesible')
                    checks.append('Administración en ambos temas, 1440/768/390/320px sin desbordamiento')
                    for view in ('models', 'network', 'agents', 'skills', 'chats', 'health', 'audit', 'analytics', 'manage', 'users'):
                        page.goto(base + '/system/?view=' + view)
                        for width in (1440, 768, 390, 320):
                            page.set_viewport_size({'width': width, 'height': 920})
                            if not page.evaluate('document.documentElement.scrollWidth <= innerWidth'):
                                overflow = page.locator('#system-content *').evaluate_all('(nodes) => nodes.filter(n => n.getBoundingClientRect().right > innerWidth || n.scrollWidth > n.clientWidth).map(n => ({tag:n.tagName, class:n.className, right:n.getBoundingClientRect().right, scroll:n.scrollWidth, width:n.clientWidth, text:n.textContent.slice(0,100)})).slice(0,16)')
                                raise AssertionError((view, width, overflow))
                    checks.append('Diez vistas administrativas adicionales sin desbordamiento en cuatro anchos')
                    page.set_viewport_size({'width':1440,'height':1000})
                    page.goto(base + '/system/?view=manage')
                    expect(page.locator('.admin-bento .admin-tile')).to_have_count(4)
                    page.evaluate("document.documentElement.dataset.theme = 'light'")
                    palette = page.evaluate("({sidebar:getComputedStyle(document.querySelector('.system-sidebar')).backgroundColor, tile:getComputedStyle(document.querySelector('.admin-tile-users')).backgroundImage})")
                    assert palette['sidebar'] == 'rgb(32, 83, 154)', palette
                    assert 'linear-gradient' in palette['tile'], palette
                    export_taste_snapshot('manage')
                    for theme in ('light','dark'):
                        page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
                        for width in (1440,768,390,320):
                            page.set_viewport_size({'width':width,'height':920})
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), ('bento',theme,width)
                            if width in (1440,390):
                                page.screenshot(path=str(out / f'bento-{theme}-{width}.png'),full_page=True)
                    page.set_viewport_size({'width':1440,'height':1000})
                    expect(page.locator('.system-nav details')).to_have_count(0)
                    expect(page.locator('.system-nav-section')).to_have_count(4)
                    for view in ('overview', 'chats', 'users', 'models', 'agents', 'skills', 'network', 'health', 'audit', 'manage'):
                        expect(page.locator('.system-nav a[href="/system/?view=' + view + '"]')).to_have_count(1)
                    page.locator('.system-nav .system-users-link').click()
                    expect(page.locator('h1')).to_have_text('Usuarios')
                    expect(page.locator('.system-users-link')).to_have_attribute('aria-current', 'page')
                    page.evaluate("document.documentElement.dataset.theme = 'light'")
                    export_taste_snapshot('users')
                    for theme in ('light', 'dark'):
                        page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
                        for width in (1440, 768, 390, 320):
                            page.set_viewport_size({'width': width, 'height': 920})
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), ('users', theme, width)
                            if width in (1440, 390):
                                page.screenshot(path=str(out / f'users-{theme}-{width}.png'), full_page=True)
                    page.set_viewport_size({'width': 1440, 'height': 1000})
                    page.goto(base + '/system/?view=users')
                    page.locator('.users-directory-heading').get_by_role('link', name='Crear usuario').click()
                    expect(page.locator('#account-editor')).to_be_visible()
                    expect(page.locator('#account-editor')).to_have_css('border-top-width', '0px')
                    expect(page.locator('#account-editor')).to_have_css('border-radius', '16px')
                    expect(page.locator('.users-dialog-fields').first).to_have_css('display', 'grid')
                    expect(page.locator('#account-editor .users-dialog-heading')).to_have_css('position', 'sticky')
                    expect(page.locator('#account-editor .users-dialog-footer')).to_have_css('position', 'sticky')
                    assert page.evaluate("document.querySelector('#account-editor').matches(':modal')")
                    expect(page.locator('#id_username')).to_be_focused()
                    page.keyboard.press('Escape')
                    expect(page.locator('#account-editor')).not_to_be_visible()
                    expect(page.locator('.users-directory-heading .button')).to_be_focused()
                    page.locator('.users-directory-heading .button').click()
                    for theme in ('light', 'dark'):
                        page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
                        for width in (1440, 768, 390, 320):
                            page.set_viewport_size({'width': width, 'height': 920})
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                            assert page.locator('#account-editor').evaluate('el => el.scrollWidth <= el.clientWidth')
                            if width in (1440, 390):
                                page.screenshot(path=str(out / f'users-create-{theme}-{width}.png'))
                    page.set_viewport_size({'width': 1440, 'height': 1000})
                    page.locator('#account-editor').get_by_role('link', name='Cancelar', exact=True).click()
                    page.goto(base + '/system/?view=users&new=1')
                    page.locator('#id_username').fill('qa-created')
                    page.locator('#id_first_name').fill('Persona')
                    page.locator('#id_last_name').fill('Validación')
                    page.locator('#id_email').fill('qa-created@example.com')
                    page.locator('#id_role').select_option('user')
                    page.locator('#id_password1').fill(password)
                    page.locator('#id_password2').fill(password)
                    page.locator('#id_is_active').check()
                    page.locator('#account-form').get_by_role('button',name='Crear usuario',exact=True).click()
                    expect(page.locator('.system-feedback')).to_contain_text('Usuario creado')
                    row = page.locator('.users-table tbody tr').filter(has_text='@qa-created')
                    expect(row).to_have_count(1)
                    page.on('dialog',lambda dialog:dialog.accept())
                    row.get_by_role('button',name='Desactivar',exact=True).click()
                    expect(page.locator('.system-feedback')).to_contain_text('Cuenta desactivada')
                    row = page.locator('.users-table tbody tr').filter(has_text='@qa-created')
                    row.get_by_role('button',name='Activar',exact=True).click()
                    expect(page.locator('.system-feedback')).to_contain_text('Cuenta activada')
                    row = page.locator('.users-table tbody tr').filter(has_text='@qa-created')
                    row.get_by_role('link',name='Editar',exact=True).click()
                    expect(page.locator('#id_password1')).to_have_value('')
                    page.locator('#id_first_name').fill('Persona editada')
                    page.locator('#account-form').get_by_role('button',name='Guardar cambios',exact=True).click()
                    expect(page.locator('.users-table')).to_contain_text('Persona editada')
                    row = page.locator('.users-table tbody tr').filter(has_text='@qa-created')
                    row.get_by_role('link', name='Restablecer contraseña', exact=True).click()
                    expect(page.locator('#password-editor')).to_be_visible()
                    assert page.evaluate("document.querySelector('#password-editor').matches(':modal')")
                    page.locator('#id_new_password1').fill('Otra-Clave-Postal-2026!')
                    page.locator('#id_new_password2').fill('No-Coincide-2026!')
                    page.locator('#password-form button[type=submit]').click()
                    expect(page.locator('#password-editor')).to_be_visible()
                    expect(page.locator('#password-form .errorlist')).to_be_visible()
                    expect(page.locator('#id_new_password1')).to_have_value('')
                    for theme in ('light', 'dark'):
                        page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
                        for width in (1440, 390, 320):
                            page.set_viewport_size({'width': width, 'height': 920})
                            assert page.locator('#password-editor').evaluate('el => el.scrollWidth <= el.clientWidth')
                            if width != 320:
                                page.screenshot(path=str(out / f'users-reset-{theme}-{width}.png'))
                    page.locator('#id_new_password1').fill('Otra-Clave-Postal-2026!')
                    page.locator('#id_new_password2').fill('Otra-Clave-Postal-2026!')
                    page.locator('#password-form button[type=submit]').click()
                    expect(page.locator('.system-feedback')).to_contain_text('Contraseña restablecida')
                    checks.append('Popups de usuarios: foco, Escape, cancelar, responsive, validación y reset de contraseña')
                    for theme in ('light', 'dark'):
                        page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
                        for width in (1440,390):
                            page.set_viewport_size({'width':width,'height':920})
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), ('users',theme,width)
                            page.screenshot(path=str(out / f'users-{theme}-{width}.png'),full_page=True)
                    page.set_viewport_size({'width':1440,'height':1000})
                    checks.append('Navegación directa en cuatro grupos; crear/editar usuario, activar/desactivar y contraseñas ocultas')
                    page.set_viewport_size({'width': 1440, 'height': 1000})
                    page.goto(base + '/')
                    expect(page.locator('#question')).to_be_enabled()
                    delayed_save = {'tested': False, 'details': 0}
                    def count_detail(request):
                        if '/api/conversations/' in request.url and request.method == 'GET' and '?page=' not in request.url:
                            delayed_save['details'] += 1
                    page.on('request', count_detail)
                    def delay_result_save(route):
                        data = route.request.post_data_json
                        if not delayed_save['tested'] and any(message.get('kind') == 'result' for message in data['messages']):
                            delayed_save['tested'] = True
                            before = delayed_save['details']
                            page.locator('#history-list .history-item > button').first.evaluate('(button) => button.click()')
                            page.wait_for_timeout(150)
                            assert delayed_save['details'] == before, 'El detalle debe esperar al guardado pendiente'
                        route.fulfill(response=route.fetch())
                    page.route('**/api/conversations/*/save/', delay_result_save)
                    with page.expect_response(lambda response: '/api/conversations/' in response.url
                                              and response.request.method == 'GET' and '?page=' not in response.url) as restored_response:
                        page.locator('#question').fill('Describe los campos de sucursales')
                        page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
                    assert restored_response.value.ok
                    expect(page.locator('.pending-card')).to_have_count(0, timeout=15000)
                    expect(page.locator('#history-list .history-item')).to_have_count(1)
                    expect(page.locator('#messages')).to_contain_text('Estructura:', timeout=15000)
                    expect(page.locator('#question')).to_be_enabled()
                    assert delayed_save['tested']
                    page.unroute('**/api/conversations/*/save/', delay_result_save)
                    checks.append('Guardado demorado conserva mensajes al abrir el historial y no aborta su petición')
                    chat_url = page.url
                    page.reload()
                    expect(page.locator('#messages')).to_contain_text('Estructura:')
                    checks.append('Chat persistido y recargado desde el servidor')
                    page.locator('.history-delete').click()
                    expect(page.locator('#history-list .history-item')).to_have_count(0)
                    page.goto(base + '/trash/')
                    expect(page.locator('.system-trash-row')).to_have_count(1)
                    page.get_by_role('button', name='Restaurar', exact=True).click()
                    expect(page.locator('.system-trash-row')).to_have_count(0)
                    page.goto(chat_url)
                    expect(page.locator('#messages')).to_contain_text('Estructura:')
                    checks.append('Papelera, restauración e historial recuperado')
                    second_context = browser.new_context(viewport={'width': 390, 'height': 844})
                    second = second_context.new_page()
                    login(second, 'qa-admin')
                    second.goto(chat_url)
                    expect(second.locator('#messages')).to_contain_text('Estructura:')
                    checks.append('Chat accesible con otra sesión y dispositivo')
                    user_context = browser.new_context()
                    user_page = user_context.new_page()
                    login(user_page, 'qa-user')
                    response = user_page.goto(base + '/system/')
                    assert response.status == 403
                    user_page.goto(base + '/')
                    expect(user_page.locator('#history-list .history-item')).to_have_count(0)
                    assert user_page.locator('a[href="/system/"]').count() == 0
                    checks.append('Usuario normal sin administración ni chats ajenos')
                    legacy_id = user_page.evaluate('''async () => {
                        const id = crypto.randomUUID();
                        const db = await new Promise((resolve, reject) => {
                            const request = indexedDB.open('bolipost-history-user-2', 1);
                            request.onupgradeneeded = () => request.result.createObjectStore('conversations', {keyPath:'id'});
                            request.onsuccess = () => resolve(request.result);
                            request.onerror = () => reject(request.error);
                        });
                        await new Promise((resolve, reject) => {
                            const tx = db.transaction('conversations', 'readwrite');
                            tx.objectStore('conversations').put({id, title:'Consulta heredada QA',
                                messages:[{kind:'question', text:'Consulta heredada QA'}], updated:Date.now()});
                            tx.oncomplete = resolve; tx.onerror = () => reject(tx.error);
                        });
                        db.close(); return id;
                    }''')
                    user_page.reload()
                    expect(user_page.locator('#history-list .history-item')).to_have_count(1)
                    user_page.locator('#history-list .history-item > button').first.click()
                    expect(user_page.locator('#messages')).to_contain_text('Consulta heredada QA')
                    assert legacy_id in user_page.url
                    empty_local = user_page.evaluate('''async () => {
                        const db = await new Promise(resolve => {
                            const request = indexedDB.open('bolipost-history-user-2', 1);
                            request.onsuccess = () => resolve(request.result);
                        });
                        const records = await new Promise(resolve => {
                            const request = db.transaction('conversations').objectStore('conversations').getAll();
                            request.onsuccess = () => resolve(request.result);
                        });
                        db.close(); return records.length === 0;
                    }''')
                    assert empty_local
                    checks.append('Historial IndexedDB importado y copia local retirada solo tras persistir')
                    assert not errors, errors
                    browser.close()
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
    report = {'checks': checks, 'javascript_errors': errors, 'live_ai_calls': False}
    (out / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    if '--serve' in sys.argv:
        serve(Path(sys.argv[2]), sys.argv[3])
    else:
        run()
