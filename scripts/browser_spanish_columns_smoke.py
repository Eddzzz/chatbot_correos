"""Verify Spanish labels without changing result keys or stored values."""
import json
from pathlib import Path
from playwright.sync_api import expect, sync_playwright
from browser_smoke import EDGE, credentials


def main():
    username, password = credentials()
    columns = ['id', 'origen', 'tipo_correspondencia', 'cantidad', 'peso', 'codigo',
               'precio', 'ciudad', 'created_at', 'updated_at']
    labels = ['Identificador', 'Origen', 'Tipo de correspondencia', 'Cantidad', 'Peso', 'Código',
              'Precio', 'Ciudad', 'Fecha de creación', 'Fecha de actualización']
    row = dict(zip(columns, [1, 'TRINIDAD', 'Documento', 1, 2, 'BO-PRUEBA-001', 20,
                             'RURRENABAQUE', '2026-11-10 12:00:00', '2026-11-10 12:30:00']))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=EDGE)
        context = browser.new_context(permissions=['clipboard-read', 'clipboard-write'])
        page = context.new_page()
        page.goto('http://127.0.0.1:8000/accounts/login/')
        page.locator('#id_username').fill(username)
        page.locator('#id_password').fill(password)
        page.get_by_role('button', name='Ingresar').click()
        expect(page.locator('#workspace')).to_be_visible()
        uid = json.loads(page.locator('#user-id').text_content())
        headers = {'Content-Type': 'application/json', 'X-Bolipost-User': str(uid)}
        job_id = '00000000-0000-0000-0000-000000000002'
        result = {'id': job_id, 'status': 'ok', 'title': 'Envíos', 'answer': '', 'analysis': {},
                  'columns': columns, 'rows': [row, {**row, 'id': 2}], 'source_tables': ['paquetes_contrato'],
                  'filters': {}, 'created_at': '2026-11-10T12:00:00Z', 'row_count': 2,
                  'page': 1, 'has_more': False, 'panels': []}
        page.route('**/api/chat/', lambda route: route.fulfill(status=202, headers=headers, body=json.dumps({'id': job_id, 'status': 'queued'})))
        page.route('**/api/results/**', lambda route: route.fulfill(status=200, headers=headers, body=json.dumps(result)))
        page.locator('#question').fill('Datos de envíos')
        page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
        expect(page.locator('#messages .record-list')).to_be_visible()
        for restored in (False, True):
            if restored:
                page.locator('#new-chat').click()
                page.locator('.history-item > button').first.click()
            assert page.locator('#messages .record-fields').first.locator('dt').all_text_contents() == labels
            expect(page.locator('#messages .record-list')).to_contain_text('RURRENABAQUE')
            page.get_by_role('button', name='Copiar resultado', exact=True).click()
            copied = page.evaluate('navigator.clipboard.readText()')
            assert '\t'.join(labels) in copied
            assert 'created_at' not in copied and 'BO-PRUEBA-001' in copied
        Path('.runtime/qa').mkdir(parents=True, exist_ok=True)
        page.screenshot(path='.runtime/qa/spanish-columns.png')
        page.locator('#new-chat').click()
        result.update(rows=[row], row_count=1)
        page.locator('#question').fill('Detalles del envío')
        page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
        expect(page.locator('#messages .record-fields')).to_be_visible()
        assert page.locator('#messages .record-fields dt').all_text_contents() == labels
        browser.close()
    print('PASS: Spanish table and clipboard headers, including restored history; original values preserved')


if __name__ == '__main__':
    main()
