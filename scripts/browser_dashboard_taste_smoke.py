"""Shipment dashboard QA with synthetic data, without provider calls."""
import json
from decimal import Decimal
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from browser_smoke import EDGE, credentials

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.runtime' / 'qa' / 'dashboard-taste'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    username, password = credentials()
    families = [('EMS', 6679, '5058.201'), ('CERTI', 5231, '6165.708'),
                ('ORDI', 1079, '280.983'), ('INT', 2396, '14404.056'),
                ('CONTRATO', 58752, '80155.394')]
    panels = [dict(index=i, title='Resumen de envíos ' + name, status='ok',
                   columns=['total_envios', 'peso_total'],
                   rows=[dict(total_envios=count, peso_total=weight)],
                   row_count=1, page=1, has_more=False)
              for i, (name, count, weight) in enumerate(families)]
    months = ['2026-06-01T00:00:00', '2026-07-01T00:00:00', '2026-08-01T00:00:00',
              '2026-09-01T00:00:00', '2026-10-01T00:00:00', None]
    counts = [12043, 19705, 17348, 19756, 5284, 1]
    weights = ['16155.339', '27862.322', '30077.584', '26299.542', '5669.425', '0.130']
    assert sum(counts) == sum(count for _, count, _ in families)
    assert sum(map(Decimal, weights)) == sum(Decimal(weight) for _, _, weight in families)
    monthly = dict(index=5, title='Evolución mensual de envíos', status='ok',
                   columns=['mes', 'total_envios', 'peso_total', 'peso_promedio'],
                   rows=[dict(mes=month, total_envios=count, peso_total=weight,
                              peso_promedio='1.34147131113509922777' if index == 0 else str(Decimal(weight) / count))
                         for index, (month, count, weight) in enumerate(zip(months, counts, weights))],
                   row_count=6, page=1, has_more=False,
                   chart=dict(kind='line', labels=[m or 'Sin dato' for m in months],
                              values=counts, label='Envíos'))
    panels.append(monthly)
    job_id = '00000000-0000-0000-0000-000000000043'
    result = dict(panels[0], id=job_id, title='Dashboard de envíos por familia y evolución mensual',
                  primary_title=panels[0]['title'], panels=panels, answer='', demo=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=EDGE)
        context = browser.new_context(permissions=['clipboard-read', 'clipboard-write'],
                                      viewport=dict(width=1440, height=1000))
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://127.0.0.1:8000/accounts/login/')
        page.locator('#id_username').fill(username)
        page.locator('#id_password').fill(password)
        page.get_by_role('button', name='Ingresar').click()
        expect(page.locator('#workspace')).to_be_visible()
        uid = json.loads(page.locator('#user-id').text_content())
        headers = {'Content-Type': 'application/json', 'X-Bolipost-User': str(uid)}
        page.route('**/api/chat/', lambda route: route.fulfill(status=202, headers=headers,
                   body=json.dumps(dict(id=job_id, status='queued'))))
        page.route('**/api/results/**', lambda route: route.fulfill(status=200, headers=headers,
                   body=json.dumps(result)))

        def submit():
            previous = page.locator('#messages canvas').count()
            page.locator('#question').fill('Dame un dashboard de envíos')
            page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
            expect(page.locator('#messages canvas')).to_have_count(previous + 1)

        def theme(value):
            for _ in range(3):
                if page.locator('#theme-toggle').get_attribute('data-value') == value:
                    break
                page.locator('#theme-toggle').click()

        submit()
        report = page.locator('#messages .result-card').last
        expect(report.locator('.shipment-summary tbody tr')).to_have_count(5)
        expect(report.locator('.dashboard-kpis')).to_contain_text('74.137')
        expect(report.locator('.dashboard-kpis')).to_contain_text('106.064,342')
        expect(report.locator('.shipment-summary')).to_contain_text('80.155,394')
        chart = report.locator('canvas')
        assert chart.evaluate('(c) => Chart.getChart(c).data.datasets[0].data') == counts[:-1]
        assert chart.evaluate('(c) => Chart.getChart(c).data.labels')[0] == 'jun 2026'
        expect(report.locator('.chart-note')).to_contain_text('Sin fecha: 1')
        expect(report.locator('.monthly-detail tbody tr')).to_have_count(6)
        expect(report.locator('.monthly-detail')).to_contain_text('1,34')
        assert 'T00:00:00' not in report.inner_text()
        assert '1.34147131113509922777' not in report.inner_text()
        page.bring_to_front()
        page.get_by_role('button', name='Copiar informe', exact=True).last.click()
        expect(page.locator('#announcement')).to_have_text('Resultado copiado.')
        copied = page.evaluate('navigator.clipboard.readText()')
        assert '2026-06-01T00:00:00' in copied and '1.34147131113509922777' in copied
        for panel in panels:
            assert panel['title'] in copied
        assert 'panel_pages=' in page.locator('#messages .result-actions a[href*="/pdf/"]').last.get_attribute('href')

        for width, height in [(1440, 1000), (768, 1024), (390, 844)]:
            page.set_viewport_size(dict(width=width, height=height))
            theme('light')
            expect(page.locator('#announcement')).to_be_hidden(timeout=6000)
            page.locator('#question').blur()
            page.mouse.move(0, 0)
            page.locator('#conversation').evaluate('(node) => node.scrollTop = 0')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert report.evaluate('(node) => node.scrollWidth <= node.clientWidth')
            page.screenshot(path=str(OUT / f'dashboard-{width}.png'))
        page.set_viewport_size(dict(width=1440, height=1000))
        theme('dark')
        assert chart.evaluate('(c) => Chart.getChart(c).data.datasets[0].borderColor === getComputedStyle(document.documentElement).getPropertyValue("--blue").trim()')
        page.screenshot(path=str(OUT / 'dashboard-dark.png'))
        theme('light')
        # Standalone review artifact contains only synthetic report data.
        markup = report.evaluate('''(node) => {
            const copy = node.cloneNode(true);
            copy.querySelectorAll('canvas').forEach((canvas, index) => {
                const image = document.createElement('img');
                image.src = node.querySelectorAll('canvas')[index].toDataURL();
                image.alt = canvas.getAttribute('aria-label');
                image.style.cssText = 'width:100%;height:100%;object-fit:contain';
                canvas.replaceWith(image);
            });
            return copy.outerHTML;
        }''')
        css = (ROOT / 'static/postal/app.css').read_text(encoding='utf-8')
        (OUT / 'review.html').write_text('<!doctype html><html lang="es"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Correos de Bolivia · Dashboard de demostración</title><style>' + css +
            '</style><main style="max-width:1088px;margin:24px auto;padding:16px">'
            '<h1 style="font-size:20px">Correos de Bolivia · Envíos</h1>' + markup + '</main></html>', encoding='utf-8')
        page.locator('#new-chat').click()
        page.locator('#history-list .history-item > button').first.click()
        expect(page.locator('.shipment-summary tbody tr')).to_have_count(5)
        # A true zero remains a point in the temporal series.
        monthly['chart']['values'][1] = 0
        submit()
        assert page.locator('#messages canvas').last.evaluate('(c) => Chart.getChart(c).data.datasets[0].data[1]') == 0
        # Partial or failed summaries retain their own result/error without pagination controls.
        panels[1]['has_more'] = True
        panels[2]['status'] = 'error'
        panels[2]['error'] = {'message': 'No se pudo ejecutar la consulta.'}
        submit()
        last = page.locator('#messages .result-card').last
        expect(last.locator('.shipment-summary')).to_have_count(0)
        expect(last.locator('.pagination')).to_have_count(0)
        expect(last.locator('.error-text')).to_be_visible()
        assert not errors, errors
        browser.close()
    print('PASS: family comparison, totals, localized values, missing dates, true zero, raw copy, PDF link, history, partial/error fallback, 3 widths and dark theme')


if __name__ == '__main__':
    main()
