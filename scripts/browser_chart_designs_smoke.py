"""Chart design, data integrity and responsive checks with synthetic report data."""
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from browser_smoke import EDGE, credentials


def main():
    output = Path(__file__).resolve().parents[1] / '.runtime/qa/chart-designs'
    output.mkdir(parents=True, exist_ok=True)
    names = ['Sin departamento', 'LA PAZ', 'COCHABAMBA', 'CHUQUISACA', 'SANTA CRUZ', 'ORURO', 'PANDO', 'TARIJA', 'BENI', 'POTOSI']
    fixtures = [
        ('Movimientos por departamento', names, [6717, 281, 84, 80, 75, 42, 35, 26, 10, 6], 'bar'),
        ('Movimientos CERTIFICADO por departamento', ['Sin departamento'], [313], 'bar'),
        ('Distribución por servicio', ['EMS', 'CERTIFICADO', 'ORDINARIO'], [315, 281, 84], 'bar'),
        ('Evolución mensual', ['2026-06-01', '2026-07-01', '2026-08-01', 'Sin dato'], [10, 0, 20, 2], 'line'),
        ('Sin movimientos', ['LA PAZ', 'BENI'], [0, 0], 'bar'),
        ('Ajustes', ['LA PAZ', 'BENI'], [10, -2], 'bar'),
        ('Comparación por servicio', ['EMS', 'CERTIFICADO', 'ORDINARIO'], [315, 281, 84], 'bar'),
    ]
    panels = [dict(index=i, title=title, status='ok', columns=['departamento', 'total_movimientos'],
                   rows=[dict(departamento=n, total_movimientos=v) for n, v in zip(labels, values)],
                   row_count=len(labels), page=1, has_more=False,
                   chart=dict(kind=kind, labels=labels, values=values, label='Movimientos'))
              for i, (title, labels, values, kind) in enumerate(fixtures)]
    for panel, view in zip(panels, ['horizontal', 'horizontal', 'doughnut', 'line', 'horizontal', 'horizontal', 'bar']):
        panel['chart']['view'] = view
    result = dict(panels[0], id='00000000-0000-0000-0000-000000000049',
                  title='Reporte de movimientos', panels=panels, answer='', demo=True)
    username, password = credentials()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=EDGE)
        page = browser.new_page(viewport=dict(width=1440, height=1000))
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
                   body=json.dumps(dict(id=result['id'], status='queued'))))
        page.route('**/api/results/**', lambda route: route.fulfill(status=200, headers=headers,
                   body=json.dumps(result)))
        page.locator('#question').fill('Compara los movimientos por departamento')
        page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
        report = page.locator('#messages .result-card').last
        expect(report.locator('table')).to_have_count(len(panels))
        expect(report.locator('.chart-single')).to_contain_text('313')
        charts = report.locator('canvas')
        assert charts.nth(0).evaluate('(c) => Chart.getChart(c).options.indexAxis') == 'y'
        assert charts.nth(1).evaluate('(c) => Chart.getChart(c).config.type') == 'doughnut'
        assert charts.nth(2).evaluate('(c) => Chart.getChart(c).data.datasets[0].data') == [10, 0, 20]
        expect(report.locator('.chart-note')).to_contain_text('Sin fecha: 2')
        assert charts.nth(3).evaluate('(c) => Chart.getChart(c).config.type') == 'bar'
        assert charts.nth(4).evaluate('(c) => Chart.getChart(c).config.type') == 'bar'
        expect(report.locator('.chart-view')).to_have_count(0)
        expect(report.get_by_role('combobox', name='Vista')).to_have_count(0)
        assert charts.nth(0).evaluate('(c) => Chart.getChart(c).data.datasets[0].data') == fixtures[0][2]
        expect(report.locator('.chart-legend').nth(1)).to_contain_text('EMS')
        assert charts.nth(2).evaluate('(c) => Chart.getChart(c).config.type') == 'line'
        assert charts.nth(5).evaluate('(c) => Chart.getChart(c).config.type') == 'bar'
        assert charts.nth(5).evaluate('(c) => Chart.getChart(c).options.indexAxis') == 'x'
        for width in [1440, 768, 390]:
            page.set_viewport_size(dict(width=width, height=1000))
            for theme in ['light', 'dark']:
                for _ in range(3):
                    if page.locator('#theme-toggle').get_attribute('data-value') == theme:
                        break
                    if not page.locator('#theme-toggle').is_visible():
                        page.locator('#menu-toggle').click()
                    page.locator('#theme-toggle').click()
                if page.locator('#menu-close').is_visible():
                    page.locator('#menu-close').click()
                assert charts.nth(1).evaluate('(c) => Array.isArray(Chart.getChart(c).data.datasets[0].backgroundColor)')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                report.locator('h3').first.scroll_into_view_if_needed()
                page.screenshot(path=str(output / f'charts-{width}-{theme}.png'))
                report.locator('.chart-figure').first.screenshot(path=str(output / f'bars-{width}-{theme}.png'))
                report.locator('.chart-figure').nth(1).screenshot(path=str(output / f'ring-{width}-{theme}.png'))
        assert not errors, errors
        browser.close()
    print('PASS: model-selected presentations, no selector, unchanged data, zeros, negatives, temporal gaps, desktop/tablet/mobile and themes')


if __name__ == '__main__':
    main()
