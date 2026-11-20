"""Exercise malformed API responses in the actual UI without submitting jobs."""
import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_smoke import credentials, EDGE


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8765')
    args = parser.parse_args()
    username, password = credentials()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=EDGE)
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(type(error).__name__))
        page.goto(args.base_url + '/accounts/login/')
        page.locator('#id_username').fill(username)
        page.locator('#id_password').fill(password)
        page.locator('button[type=submit]').click()
        page.wait_for_url(args.base_url + '/')
        identity = json.loads(page.locator('#api-identity').text_content())
        headers = {'Content-Type': 'application/json', 'X-Bolipost-User': identity}
        job_id = '00000000-0000-0000-0000-000000000001'
        for name, created, result in [
            ('null response', None, None),
            ('invalid job identifier', {'id': 'invalid', 'status': 'queued'}, None),
            ('unknown job status', {'id': job_id, 'status': 'queued'}, {'id': job_id, 'status': 'unknown'}),
        ]:
            page.locator('#new-chat').click()
            page.route('**/api/chat/', lambda route: route.fulfill(status=202, headers=headers, body=json.dumps(created)))
            if result is not None:
                page.route('**/api/results/**', lambda route: route.fulfill(status=200, headers=headers, body=json.dumps(result)))
            page.locator('#question').fill('Cuenta los envíos EMS')
            page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
            expect(page.locator('#messages .error-text')).to_contain_text('respuesta válida', timeout=10000)
            expect(page.locator('#chat-form button')).to_be_enabled()
            page.unroute('**/api/chat/')
            page.unroute('**/api/results/**')
            print('PASS: ' + name)
        page.locator('#new-chat').click()
        page.emulate_media(reduced_motion='no-preference')
        page.route('**/api/chat/', lambda route: route.fulfill(status=202, headers=headers, body=json.dumps({'id': job_id, 'status': 'queued'})))
        polls = []
        def pending(route):
            polls.append(True)
            route.fulfill(status=200, headers=headers, body=json.dumps({
                'id': job_id, 'status': 'running', 'columns': [], 'rows': [], 'row_count': 0, 'panels': []}))
        page.route('**/api/results/**', pending)
        page.locator('#question').fill('Cuenta los envíos EMS')
        page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
        page.locator('.thinking-character').wait_for()
        page.evaluate('window.qaMascot = document.querySelector(".thinking-character")')
        while len(polls) < 3:
            page.wait_for_timeout(150)
        assert page.evaluate('document.querySelector(".thinking-character") === window.qaMascot'), 'Polling must not restart the animation.'
        page.locator('#new-chat').click()
        print('PASS: waiting animation survives polling')
        assert not errors, errors
        browser.close()


if __name__ == '__main__':
    main()
