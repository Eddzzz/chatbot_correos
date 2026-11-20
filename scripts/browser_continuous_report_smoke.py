"""Continuous shipment report: mocked responses, real browser, no provider calls."""
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from browser_smoke import EDGE, credentials


OUT = Path(__file__).resolve().parents[1] / '.runtime' / 'qa' / 'continuous-report'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    username, password = credentials()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=EDGE)
        context = browser.new_context(permissions=['clipboard-read', 'clipboard-write'])
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
        job_id = '00000000-0000-0000-0000-000000000042'

        def panel(index, title, rows):
            return {'index': index, 'title': title, 'status': 'ok', 'columns': list(rows[0]),
                    'rows': rows, 'row_count': len(rows), 'page': 1, 'has_more': False}

        panels = [
            panel(0, 'Detalle del paquete EMS', [{'id': 42, 'codigo': 'BO-DEMO-042', 'origen': 'SANTA CRUZ',
                  'tipo_correspondencia': 'PARTICULAR', 'cantidad': 1, 'peso': '0.005', 'precio': '17.00',
                  'ciudad': 'LA PAZ', 'created_at': '2026-10-08T15:00:07', 'updated_at': '2026-10-08T15:00:07'}]),
            panel(1, 'Historial de eventos del paquete EMS', [
                {'id': 71, 'evento': 'Paquete recibido del cliente.', 'fechaEvento': '2026-10-08T15:00:07'},
                {'id': 72, 'evento': 'Ingreso a oficina de destino.', 'fechaEvento': '2026-10-09T09:30:00'}]),
            panel(2, 'Información del usuario asociado al paquete', [{'id': 45, 'name': 'USUARIO DE DEMOSTRACIÓN',
                  'rol': None, 'codigoSucursal': 1, 'puntoVenta': 0, 'municipio': 'SANTA CRUZ DE LA SIERRA', 'departamento': 'SANTA CRUZ'}]),
            panel(3, 'Estado actual del paquete', [{'id': 3, 'nombre_estado': 'ADMISIONES', 'activo': True}])]
        result = {**panels[0], 'id': job_id, 'title': 'Datos completos del paquete BO-DEMO-042',
                  'primary_title': panels[0]['title'], 'panels': panels, 'answer': '', 'demo': True}
        page.route('**/api/chat/', lambda route: route.fulfill(status=202, headers=headers, body=json.dumps({'id': job_id, 'status': 'queued'})))
        page.route('**/api/results/**', lambda route: route.fulfill(status=200, headers=headers, body=json.dumps(result)))
        page.locator('#question').fill('Todos los datos del paquete BO-DEMO-042')
        page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
        report = page.locator('#messages .result-card')
        expect(report).to_have_count(1)
        expect(report.locator('.result-card')).to_have_count(0)
        expect(report.locator('.result-section')).to_have_count(3)
        expect(report.locator('.record-fields')).to_have_count(3)
        expect(report.locator('table tbody tr')).to_have_count(2)
        expect(report.locator('dd')).to_contain_text(['42', 'BO-DEMO-042'])
        expect(report.locator('dt')).to_contain_text(['Código', 'Fecha de creación', 'Fecha de actualización'])
        assert report.inner_text().count('Datos de demostración') == 1
        page.get_by_role('button', name='Copiar informe', exact=True).click()
        copied = page.evaluate('navigator.clipboard.readText()')
        for metadata in panels:
            assert metadata['title'] in copied
        assert '17.00' in copied and '0.005' in copied and '—' in copied
        links = page.locator('#messages .result-actions a')
        expect(report.locator('.result-section .result-actions')).to_have_count(0)
        expect(links).to_have_count(1)
        assert 'panel_pages=' in links.last.get_attribute('href')

        for width, height in [(1440, 1000), (768, 1024), (390, 844)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.evaluate('document.documentElement.dataset.theme = "light"')
            page.locator('#announcement').wait_for(state='hidden')
            page.locator('#question').blur()
            page.locator('#conversation').evaluate('(node) => node.scrollTop = 0')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert report.locator('.record-fields').first.evaluate('(node) => node.scrollWidth <= node.clientWidth')
            assert report.locator('.result-section').first.evaluate('(node) => getComputedStyle(node).borderRadius === "0px"')
            page.screenshot(path=str(OUT / f'report-{width}.png'))

        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.evaluate('document.documentElement.dataset.theme = "dark"')
        page.screenshot(path=str(OUT / 'report-dark.png'))
        page.evaluate('document.documentElement.dataset.theme = "light"')
        # Export only synthetic report content; no session, CSRF or account data.
        markup = report.evaluate('(node) => node.outerHTML + node.nextElementSibling.outerHTML')
        css = (OUT.parents[2] / 'static' / 'postal' / 'app.css').read_text(encoding='utf-8')
        sprites = page.locator('.icon-definitions').evaluate('(node) => node.outerHTML')
        (OUT / 'report.html').write_text('<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<style>' + css + '</style><title>Informe postal · Demostración</title>' + sprites +
            '<main style="max-width:1000px;margin:32px auto;padding:16px"><h1 style="font-size:24px">Consulta de envío</h1>'
            + markup + '</main></html>', encoding='utf-8')
        page.locator('#new-chat').click()
        page.locator('#history-list .history-item > button').first.click()
        expect(report.locator('.record-fields')).to_have_count(3)
        expect(report.locator('.result-section')).to_have_count(3)
        assert not errors, errors
        browser.close()
    print('PASS: continuous report, single-record fields, event table, copy, export links, history, 3 widths and dark theme')


if __name__ == '__main__':
    main()
