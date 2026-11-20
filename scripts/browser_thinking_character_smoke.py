"""Exercise the mascot renderer, its fallback and animation cleanup without AI calls."""
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from browser_smoke import EDGE

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.runtime/qa/thinking-character-v3'
BASE = 'http://127.0.0.1:8000'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=EDGE)
        page = browser.new_page(viewport={'width': 360, 'height': 300}, device_scale_factor=2)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(BASE + '/accounts/login/')
        page.set_content('<html data-theme="dark"><link rel="stylesheet" href="' + BASE +
                         '/static/postal/app.css"><style>body{margin:0;min-height:100vh;display:grid;'
                         'place-items:center;background:var(--sheet)}</style>'
                         '<div class="thinking-scene" aria-hidden="true"></div></html>')
        page.add_script_tag(url=BASE + '/static/postal/thinking-character.js')
        page.evaluate('() => {window.disposeMascot = PostalThinking.mount(document.querySelector(".thinking-scene"));}')
        expect(page.locator('canvas')).to_have_attribute('data-renderer', 'webgl')
        page.wait_for_timeout(250)
        before = page.locator('canvas').screenshot()
        page.wait_for_timeout(1200)
        after = page.locator('canvas').screenshot()
        assert before != after, 'The character must actually move.'
        for theme in ('light', 'dark'):
            page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
            page.screenshot(path=str(OUT / f'{theme}.png'))
        page.evaluate('disposeMascot()')
        expect(page.locator('canvas')).to_have_count(0)
        page.evaluate('disposeMascot()')  # Idempotent cleanup.
        page.emulate_media(reduced_motion='reduce')
        page.evaluate('() => {window.disposeMascot = PostalThinking.mount(document.querySelector(".thinking-scene"));}')
        expect(page.locator('.thinking-scene')).not_to_be_visible()
        page.evaluate('disposeMascot()')
        page.emulate_media(reduced_motion='no-preference')
        page.evaluate('HTMLCanvasElement.prototype.getContext = () => null')
        page.evaluate('() => {window.disposeMascot = PostalThinking.mount(document.querySelector(".thinking-scene"));}')
        expect(page.locator('.thinking-character')).to_be_visible()
        assert 'cartero-thoughtful-v3.png' in page.locator('.thinking-character').evaluate(
            '(n)=>getComputedStyle(n).backgroundImage')
        assert not errors, errors
        browser.close()
    print('PASS: real animated pixels, light/dark, cleanup, reduced motion and no-WebGL fallback')


if __name__ == '__main__':
    main()
