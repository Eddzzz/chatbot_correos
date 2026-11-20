"""Scrolling stays inside the chat/history, including short desktop windows."""
from playwright.sync_api import expect, sync_playwright
from browser_smoke import EDGE, credentials


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=EDGE)
        page = browser.new_page()
        page.goto('http://127.0.0.1:8000/accounts/login/')
        username, password = credentials()
        page.locator('#id_username').fill(username)
        page.locator('#id_password').fill(password)
        page.get_by_role('button', name='Ingresar').click()
        expect(page.locator('#workspace')).to_be_visible()
        # The running server can still serve a cached template without this class.
        page.locator('body').evaluate('(node) => node.classList.remove("workspace-page")')
        assert page.locator('html').evaluate('(node) => ["hidden", "clip"].includes(getComputedStyle(node).overflowY)'), 'The document must not scroll, including cached templates'
        page.evaluate('''() => {
            document.querySelector('#chat-welcome').hidden = true;
            for (let i = 0; i < 60; i++) {
                const message = document.createElement('p');
                message.textContent = 'Mensaje de prueba ' + i;
                message.style.padding = '24px';
                document.querySelector('#messages').append(message);
                const item = document.createElement('div');
                item.className = 'history-item';
                const button = document.createElement('button');
                button.textContent = 'Conversación ' + i;
                item.append(button);
                document.querySelector('#history-list').append(item);
            }
        }''')
        for width, height in ((1862, 846), (1280, 500), (390, 844), (844, 390)):
            page.set_viewport_size({'width': width, 'height': height})
            page.evaluate('window.scrollTo(0, 10000)')
            assert page.evaluate('scrollY === 0'), (width, height)
            assert page.evaluate('document.documentElement.scrollHeight <= innerHeight'), (width, height)
            shell = page.locator('.app-shell').bounding_box()
            assert shell['y'] == 0 and shell['height'] == height, (width, height, shell)
            for selector in ('#conversation', '#history-list'):
                if not page.locator(selector).is_visible():
                    continue
                region = page.locator(selector)
                region.evaluate('(node) => node.scrollTop = 0')
                topbar = page.locator('.mobile-toolbar').bounding_box()
                composer = page.locator('#chat-form').bounding_box()
                region.hover()
                page.mouse.wheel(0, 500)
                page.wait_for_timeout(150)
                assert region.evaluate('(node) => node.scrollTop > 0'), selector
                region.evaluate('(node) => node.scrollTop = node.scrollHeight')
                page.mouse.wheel(0, 1500)
                page.wait_for_timeout(150)
                assert page.evaluate('scrollY === 0'), (width, height, selector)
                assert page.locator('.mobile-toolbar').bounding_box() == topbar
                assert page.locator('#chat-form').bounding_box() == composer
            assert page.locator('#chat-form').bounding_box()['y'] >= 0
            assert page.locator('#chat-form').bounding_box()['y'] + page.locator('#chat-form').bounding_box()['height'] <= height
        browser.close()
    print('PASS: chat/history scroll independently; header/composer stay fixed at four viewport sizes')


if __name__ == '__main__':
    main()
