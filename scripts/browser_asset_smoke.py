"""A stale unversioned stylesheet must not affect the current interface."""
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from browser_smoke import EDGE, credentials


def main():
    base = 'http://127.0.0.1:8000'
    output = Path(__file__).resolve().parents[1] / '.runtime' / 'qa' / 'asset-cache-fix'
    output.mkdir(parents=True, exist_ok=True)
    username, password = credentials()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=EDGE)
        page = browser.new_page(viewport={'width': 1814, 'height': 976})
        errors = []
        page.on('pageerror', lambda error: errors.append(type(error).__name__))
        page.add_init_script("localStorage.setItem('bolipost-theme', 'light')")
        # Simulate the obsolete URL still resolving to obsolete styles.
        page.route('**/static/postal/app.css', lambda route: route.fulfill(
            content_type='text/css', body='body{background:#1c1c1c}.brand img{width:2170px!important}'))
        page.goto(base + '/accounts/login/')
        expect(page.locator('.login-card')).to_be_visible()
        assert '?v=' in page.locator('link[rel=stylesheet]').get_attribute('href')
        assert page.locator('.brand img').bounding_box()['width'] == 166
        page.locator('#id_username').fill(username)
        page.locator('#id_password').fill(password)
        page.get_by_role('button', name='Ingresar').click()
        expect(page.locator('#workspace')).to_be_visible()
        for theme in ('light', 'dark'):
            while page.locator('html').get_attribute('data-theme') != theme:
                page.locator('#theme-toggle').click()
            for width in (390, 1440, 1814):
                page.set_viewport_size({'width': width, 'height': 976 if width > 767 else 844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (theme, width)
                if width > 767:
                    assert page.locator('#sidebar').bounding_box()['width'] == 280
                    assert page.locator('.brand img').bounding_box()['width'] == 142
                expect(page.locator('#chat-form')).to_be_visible()
            page.screenshot(path=str(output / (theme + '.png')), full_page=True)
        assert not errors, errors
        browser.close()
    print('PASS: obsolete stylesheet bypassed; logo bounded; light/dark at 390/1440/1814px; no JavaScript errors')


if __name__ == '__main__':
    main()
