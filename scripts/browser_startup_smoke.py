"""Hold JavaScript and IndexedDB to reproduce early chat submissions reliably."""
import json
from playwright.sync_api import expect, sync_playwright
from browser_smoke import EDGE, credentials


def main():
    username, password = credentials()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=EDGE)
        page = browser.new_page()
        page.goto('http://127.0.0.1:8000/accounts/login/')
        page.locator('#id_username').fill(username)
        page.locator('#id_password').fill(password)
        page.get_by_role('button', name='Ingresar').click()
        expect(page.locator('#question')).to_be_enabled()
        page.add_init_script('''(() => {
            const original = indexedDB.open.bind(indexedDB);
            indexedDB.open = (...args) => {
                const request = original(...args);
                return new Proxy(request, {
                    get(target, key) { const value = Reflect.get(target, key, target); return typeof value === 'function' ? value.bind(target) : value; },
                    set(target, key, value) {
                        target[key] = key === 'onsuccess' ? event => setTimeout(() => value.call(target, event), 800) : value;
                        return true;
                    }
                });
            };
        })();''')
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        for attempt in range(5):
            held = []
            page.route('**/static/postal/app.js?*', lambda route: held.append(route))
            page.goto('http://127.0.0.1:8000/', wait_until='commit')
            expect(page.locator('#workspace')).to_be_visible()
            expect(page.locator('#question')).to_be_disabled()
            expect(page.locator('#chat-form .send')).to_be_disabled()
            page.wait_for_timeout(100)
            assert held, 'The application script must still be held.'
            held[0].continue_()
            page.unroute('**/static/postal/app.js?*')
            # The script has installed listeners, but history is deliberately slow.
            page.wait_for_function("document.querySelector('#theme-toggle').hasAttribute('data-value')")
            expect(page.locator('#question')).to_be_disabled()
            page.locator('#new-chat').click()
            expect(page.locator('#chat-form .send')).to_be_disabled(timeout=200)
            expect(page.locator('#question')).to_be_enabled(timeout=5000)
            identity = json.loads(page.locator('#api-identity').text_content())
            headers = {'Content-Type': 'application/json', 'X-Bolipost-User': identity}
            job = f'00000000-0000-0000-0000-{500 + attempt:012d}'
            submitted = []

            def chat(route):
                submitted.append(route.request.post_data_json)
                route.fulfill(status=202, headers=headers, body=json.dumps({'id': job, 'status': 'queued'}))

            page.route('**/api/chat/', chat)
            page.route('**/api/results/**', lambda route: route.fulfill(headers=headers, body=json.dumps(
                {'id': job, 'status': 'ok', 'title': 'Inicio', 'columns': ['nombre'], 'rows': [{'nombre': 'Ana'}], 'row_count': 1})))
            page.locator('#question').fill('Consulta inmediata')
            page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
            expect(page.locator('#messages table')).to_contain_text('Ana')
            assert len(submitted) == 1 and submitted[0]['question'] == 'Consulta inmediata'
            assert '/c/' in page.url and '?' not in page.url
            page.unroute('**/api/chat/')
            page.unroute('**/api/results/**')
        assert not errors, errors
        browser.close()
    print('PASS: five cold starts with held JavaScript and slow history; no native navigation, lost input or duplicate submissions')


if __name__ == '__main__':
    main()
