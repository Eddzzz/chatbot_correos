"""Check chat URLs using isolated browser storage and deterministic API replies."""
import json
import os
import re
import uuid

from playwright.sync_api import expect, sync_playwright

from browser_smoke import EDGE, credentials


def main():
    base = os.environ.get('BOLIPOST_BASE_URL', 'http://127.0.0.1:8000')
    username, password = credentials()
    first_id, second_id, job_id = (str(uuid.uuid4()) for _ in range(3))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=EDGE)
        context = browser.new_context()
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(base + '/accounts/login/')
        page.locator('#id_username').fill(username)
        page.locator('#id_password').fill(password)
        page.get_by_role('button', name='Ingresar').click()
        expect(page.locator('#workspace')).to_be_visible()
        page.wait_for_function("document.querySelector('#question') === document.activeElement")
        page.evaluate("""async ids => {
            const user = JSON.parse(document.getElementById('user-id').textContent);
            await new Promise((resolve, reject) => {
                const request = indexedDB.open('bolipost-history-user-' + user, 1);
                request.onerror = () => reject(request.error);
                request.onsuccess = () => {
                    const db = request.result;
                    const tx = db.transaction('conversations', 'readwrite');
                    ids.forEach((id, index) => tx.objectStore('conversations').put({
                        id, title: 'Chat anterior ' + index, updated: index,
                        messages: [{kind: 'question', text: 'Pregunta anterior ' + index}]
                    }));
                    tx.oncomplete = () => { db.close(); resolve(); };
                    tx.onerror = () => reject(tx.error);
                };
            });
        }""", [first_id, second_id])
        response = page.goto(base + '/c/' + first_id)
        assert response.status == 200
        expect(page.locator('#messages .question-message')).to_have_text('Pregunta anterior 0')
        expect(page.locator('#conversation-id')).to_have_text('ID del chat: ' + first_id)
        page.get_by_role('button', name='Chat anterior 1', exact=True).click()
        expect(page).to_have_url(base + '/c/' + second_id)
        page.go_back()
        expect(page.locator('#messages .question-message')).to_have_text('Pregunta anterior 0')
        page.go_forward()
        expect(page.locator('#messages .question-message')).to_have_text('Pregunta anterior 1')
        page.reload()
        expect(page.locator('#messages .question-message')).to_have_text('Pregunta anterior 1')

        user = page.locator('#user-id').text_content().strip()
        headers = {'Content-Type': 'application/json', 'X-Bolipost-User': user}
        page.route('**/api/chat/', lambda route: route.fulfill(headers=headers, status=202,
                   body=json.dumps({'id': job_id, 'status': 'queued'})))
        result = {'id': job_id, 'status': 'no_matches', 'title': 'Prueba de URL',
                  'columns': [], 'rows': [], 'row_count': 0, 'answer': 'Sin coincidencias.'}
        page.route('**/api/results/**', lambda route: route.fulfill(headers=headers, body=json.dumps(result)))
        page.locator('#new-chat').click()
        expect(page).to_have_url(base + '/')
        expect(page.locator('#conversation-id')).to_be_hidden()
        page.locator('#question').fill('Pregunta nueva')
        page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
        expect(page).to_have_url(re.compile(re.escape(base) + r'/c/[0-9a-f-]{36}$'))
        chat_url = page.url
        assert chat_url not in (base + '/c/' + first_id, base + '/c/' + second_id)
        expect(page.locator('#chat-form button[type="submit"]')).to_be_enabled()
        page.locator('#question').fill('Seguimiento')
        page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
        expect(page.locator('#messages .question-message')).to_have_count(2)
        expect(page.locator('#chat-form button[type="submit"]')).to_be_enabled()
        assert page.url == chat_url
        page.reload()
        expect(page.locator('#messages .question-message')).to_have_count(2)
        expect(page.locator('#conversation-id')).to_contain_text(chat_url.rsplit('/', 1)[1])
        page.on('dialog', lambda dialog: dialog.accept())
        page.get_by_role('button', name='Eliminar conversación: Pregunta nueva', exact=True).click()
        expect(page).to_have_url(base + '/')
        page.goto(chat_url)
        expect(page).to_have_url(base + '/')
        expect(page.locator('#announcement')).to_contain_text('no está disponible')
        expect(page.locator('#messages .question-message')).to_have_count(0)

        # The same account in a browser without its local history cannot open the chat.
        other = browser.new_context(storage_state=context.storage_state())
        other_page = other.new_page()
        other_page.goto(base + '/c/' + first_id)
        expect(other_page).to_have_url(base + '/')
        expect(other_page.locator('#messages .question-message')).to_have_count(0)
        expect(other_page.locator('#announcement')).to_contain_text('no está disponible')
        assert not errors, errors
        browser.close()
    print('PASS: existing UUIDs, direct URLs, reload, Back/Forward, new chats, follow-ups, deletion and local isolation')


if __name__ == '__main__':
    main()
