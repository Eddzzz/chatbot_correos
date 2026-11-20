"""Conversation context survives clarification, restore, edit and a new chat. Synthetic API."""
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from browser_smoke import EDGE, credentials


def main():
    output = Path(__file__).resolve().parents[1] / '.runtime' / 'qa' / 'clarification-context'
    output.mkdir(parents=True, exist_ok=True)
    username, password = credentials()
    questions = ['Movimiento de paquetes en la primera semana de junio por departamentos',
                 '2026', 'movimiento de paquetes', 'todo']
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=EDGE)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors, requests, results = [], [], {}
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://127.0.0.1:8000/accounts/login/')
        page.locator('#id_username').fill(username)
        page.locator('#id_password').fill(password)
        page.get_by_role('button', name='Ingresar').click()
        expect(page.locator('#workspace')).to_be_visible()
        expect(page.locator('#connection-state')).not_to_have_text('Comprobando conexión…')
        uid = json.loads(page.locator('#user-id').text_content())
        headers = {'Content-Type': 'application/json', 'X-Bolipost-User': str(uid)}

        def chat(route):
            payload = route.request.post_data_json
            requests.append(payload)
            index = len(requests)
            job_id = f'00000000-0000-0000-0000-{index:012d}'
            result = {'id': job_id, 'status': 'error', 'title': 'Consulta', 'columns': [], 'rows': [],
                      'row_count': 0, 'page': 1, 'panels': [], 'demo': True,
                      'error': {'code': 'clarification', 'message': '¿A qué año corresponde esa semana?'}}
            if index >= 4:
                result.update(status='ok', error=None, title='Movimiento por departamentos · 1 al 7 de junio de 2026',
                              columns=['departamento', 'total_movimientos'],
                              rows=[{'departamento': 'LA PAZ', 'total_movimientos': 12},
                                    {'departamento': 'BENI', 'total_movimientos': 7}], row_count=2)
            results[job_id] = result
            route.fulfill(status=202, headers=headers, body=json.dumps({'id': job_id, 'status': 'queued'}))

        def result(route):
            job_id = route.request.url.split('/api/results/')[1].split('/')[0]
            route.fulfill(headers=headers, body=json.dumps(results[job_id]))

        page.route('**/api/chat/', chat)
        page.route('**/api/results/**', result)
        ids = []
        for index, question in enumerate(questions):
            page.locator('#question').fill(question)
            page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
            expect(page.locator('#messages .result-card')).to_have_count(index + 1)
            assert requests[-1].get('history_ids', []) == ids
            assert requests[-1].get('previous_id') == (ids[-1] if ids else None)
            ids.append(list(results)[-1])
        expect(page.locator('#messages table')).to_contain_text('BENI')
        page.locator('#new-chat').click()
        page.locator('#history-list .history-item > button').first.click()
        expect(page.locator('#messages .result-card')).to_have_count(4)
        page.locator('#messages .question-entry').nth(1).hover()
        page.locator('#messages .question-entry').nth(1).get_by_role('button', name='Editar consulta', exact=True).click()
        page.get_by_role('textbox', name='Editar consulta en el chat', exact=True).fill('2025')
        page.get_by_role('button', name='Enviar consulta editada', exact=True).click()
        expect(page.locator('#messages .result-card')).to_have_count(2)
        assert requests[-1]['history_ids'] == ids[:1]
        assert requests[-1]['question'] == '2025'
        page.screenshot(path=str(output / 'edited-context.png'))
        page.locator('#new-chat').click()
        page.locator('#question').fill('Envíos por servicio')
        page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
        expect(page.locator('#messages .result-card')).to_have_count(1)
        assert 'history_ids' not in requests[-1] and 'previous_id' not in requests[-1]
        assert not errors, errors
        browser.close()
    print('PASS: clarification IDs retained, year/movement/todo keep context, restored edits prune later turns, new chat resets context')


if __name__ == '__main__':
    main()
