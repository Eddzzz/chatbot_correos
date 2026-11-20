"""Categorical dashboard regression using verified-shape synthetic results."""
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from browser_smoke import EDGE, credentials

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.runtime/qa/city-dashboard'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    names = ['LA PAZ', 'COCHABAMBA', 'SANTA CRUZ', 'SUCRE', 'TARIJA', 'COBIJA', 'POTOSÍ', 'ORURO', 'TRINIDAD']
    values = [2692, 1052, 955, 502, 350, 313, 288, 266, 261]
    primary = dict(index=0, title='Paquetes EMS por ciudad', status='ok',
                   columns=['ciudad', 'total_envios'],
                   rows=[dict(ciudad=name, total_envios=value) for name, value in zip(names, values)],
                   row_count=9, page=1, has_more=False,
                   chart=dict(kind='bar', labels=names, values=values, label='Paquetes EMS'))
    scalar = dict(index=1, title='Total general de paquetes EMS', status='ok',
                  columns=['total_envios'], rows=[dict(total_envios=sum(values))],
                  row_count=1, page=1, has_more=False)
    result = dict(primary, id='00000000-0000-0000-0000-000000000044',
                  title='Dashboard de paquetes EMS por ciudad', response_type='dashboard',
                  primary_title=primary['title'], panels=[primary, scalar], answer='', demo=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=EDGE)
        page = browser.new_page(viewport=dict(width=1440, height=1000))
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://127.0.0.1:8000/accounts/login/')
        username, password = credentials()
        page.locator('#id_username').fill(username)
        page.locator('#id_password').fill(password)
        page.get_by_role('button', name='Ingresar').click()
        expect(page.locator('#workspace')).to_be_visible()
        uid = json.loads(page.locator('#user-id').text_content())
        headers = {'Content-Type': 'application/json', 'X-Bolipost-User': str(uid)}
        page.route('**/api/chat/', lambda route: route.fulfill(status=202, headers=headers,
                   body=json.dumps(dict(id=result['id'], status='queued'))))
        page.route('**/api/results/**', lambda route: route.fulfill(status=200, headers=headers, body=json.dumps(result)))

        def submit():
            count = page.locator('#messages .result-card').count()
            page.locator('#question').fill('Dame un dashboard')
            page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
            expect(page.locator('#messages .result-card')).to_have_count(count + 1)
            expect(page.locator('#messages .result-card').last).to_contain_text(result['title'])
            expect(page.locator('.thinking-state')).to_have_count(0)
            return page.locator('#messages .result-card').last

        report = submit()
        expect(report.locator('.categorical-kpis')).to_contain_text('6.679')
        expect(report.locator('.categorical-kpis')).to_contain_text('9')
        expect(report.locator('.categorical-kpis')).to_contain_text('40,3')
        expect(report.locator('.categorical-kpis')).to_contain_text('70,4')
        expect(report.locator('table, details, summary')).to_have_count(0)
        expect(report.locator('.dashboard-share-list li')).to_have_count(9)
        for name, value in zip(names, values):
            item = report.locator('.dashboard-share-list li').filter(has_text=name)
            expect(item).to_contain_text(f'{value:,}'.replace(',', '.'))
            expect(item).to_be_visible()
        expect(report.locator('.report-panels')).to_have_count(0)
        for theme in ['light', 'dark']:
            page.set_viewport_size(dict(width=1440, height=1000))
            for _ in range(3):
                if page.locator('#theme-toggle').get_attribute('data-value') == theme:
                    break
                page.locator('#theme-toggle').click()
            assert report.locator('canvas').evaluate('(c) => Chart.getChart(c).data.datasets[0].borderColor === getComputedStyle(document.documentElement).getPropertyValue("--blue").trim()')
            for width in [1440, 768, 390, 320]:
                page.set_viewport_size(dict(width=width, height=1000))
                page.wait_for_timeout(250)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert report.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
                page.locator('#conversation').evaluate('(e) => e.scrollTop = 0')
                page.screenshot(path=str(OUT / f'{theme}-{width}.png'), full_page=True)
                if width == 1440:
                    report.locator('.categorical-grid').screenshot(path=str(OUT / f'visual-breakdown-{theme}.png'))
        report.locator('.categorical-grid').screenshot(path=str(OUT / 'visual-breakdown.png'))
        expect(report.locator('.chart-view')).to_have_count(0)
        expect(report.get_by_role('combobox', name='Vista')).to_have_count(0)
        # A requested pie keeps all nine categories and displays the verified commentary.
        result['chart']['view'] = 'pie'
        result['answer'] = 'LA PAZ concentra el mayor volumen.\n\nConsejo: compara períodos equivalentes antes de decidir.'
        result['analysis'] = {'generated': True, 'citations': []}
        report = submit()
        expect(report.locator('.result-narrative')).to_contain_text('Consejo:')
        assert report.locator('canvas').evaluate('(c) => Chart.getChart(c).config.type') == 'pie'
        assert report.locator('canvas').evaluate('(c) => Chart.getChart(c).data.datasets[0].data') == values
        expect(report.locator('.chart-legend li')).to_have_count(9)
        for width in [1440, 768, 390, 320]:
            page.set_viewport_size(dict(width=width, height=1000))
            page.wait_for_timeout(150)
            assert report.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
        page.set_viewport_size(dict(width=1440, height=1000))
        report.screenshot(path=str(OUT / 'pie-with-advice.png'))
        # Asking for an explanation displays prose, retaining the evidence only for exports/followups.
        result['analysis']['presentation'] = 'explanation'
        report = submit()
        expect(report.locator('.result-narrative')).to_contain_text('Consejo:')
        expect(report.locator('table, canvas, .categorical-kpis, .report-panels')).to_have_count(0)
        for width in [1440, 390, 320]:
            page.set_viewport_size(dict(width=width, height=1000))
            assert report.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
        page.set_viewport_size(dict(width=1440, height=1000))
        report.screenshot(path=str(OUT / 'explanation-only.png'))
        page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
        page.bring_to_front()
        page.get_by_role('button', name='Copiar explicación', exact=True).last.click()
        copied = page.evaluate('navigator.clipboard.readText()')
        assert 'Consejo:' in copied and '\t' not in copied
        result['analysis'].pop('presentation')
        # Already-saved explanations from before the marker was introduced must also show their prose.
        original_title = result['title']
        result['title'] = 'Explicación del dashboard de paquetes EMS por ciudad'
        report = submit()
        expect(report.locator('.result-narrative')).to_contain_text('Consejo:')
        expect(report.locator('table, canvas')).to_have_count(0)
        result['title'] = original_title
        # Partial results must not be promoted to whole-dataset dashboard metrics.
        result['has_more'] = True
        result['panels'][0]['has_more'] = True
        report = submit()
        expect(report.locator('.categorical-kpis')).to_have_count(0)
        # A zero dataset is valid; no NaN or fictional change is displayed.
        result['has_more'] = False
        result['panels'][0]['has_more'] = False
        result['chart']['values'] = [0] * len(values)
        for row in result['rows']:
            row['total_envios'] = 0
        report = submit()
        expect(report.locator('.categorical-kpis')).to_contain_text('0%')
        assert 'NaN' not in report.inner_text()
        # The separate total now disagrees and must remain visible as evidence.
        expect(report.locator('.report-panels')).to_contain_text(scalar['title'])
        # Additional measures remain visible as compact records, without tables.
        result['columns'].append('peso_total')
        for row in result['rows']:
            row['peso_total'] = '12.345'
        report = submit()
        expect(report.locator('.dashboard-record')).to_have_count(9)
        expect(report.locator('.dashboard-record').first).to_contain_text('12,345')
        expect(report.locator('table, details, summary')).to_have_count(0)
        assert not errors, errors
        browser.close()
    print('PASS: KPIs, complete visual ranking, totals and shares, extra measures, no tables or selectors, partial fallback, 4 widths, both themes')


if __name__ == '__main__':
    main()
