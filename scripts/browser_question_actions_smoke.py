"""Question actions render even with an older page's SVG definitions."""
from playwright.sync_api import expect, sync_playwright

from browser_smoke import EDGE, credentials


def main():
    username, password = credentials()
    question = 'Describe los campos de users'
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=EDGE)
        context = browser.new_context(permissions=['clipboard-read', 'clipboard-write'])
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(type(error).__name__))
        page.goto('http://127.0.0.1:8000/accounts/login/')
        page.locator('#id_username').fill(username)
        page.locator('#id_password').fill(password)
        page.get_by_role('button', name='Ingresar').click()
        expect(page.locator('#workspace')).to_be_visible()
        expect(page.locator('#connection-state')).not_to_have_text('Comprobando conexión…')
        page.evaluate("document.querySelectorAll('#icon-edit, #icon-copy, #icon-download').forEach(node => node.remove())")
        page.locator('#question').fill(question)
        page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
        expect(page.locator('#messages table')).to_be_visible(timeout=15000)
        for restored in (False, True):
            if restored:
                page.locator('#new-chat').click()
                page.locator('.history-item > button').first.click()
            edit = page.get_by_role('button', name='Editar consulta', exact=True)
            copy = page.get_by_role('button', name='Copiar consulta', exact=True)
            page.locator('#messages .question-entry').hover()
            expect(edit).to_be_visible()
            expect(copy).to_be_visible()
            for action in (edit, copy):
                assert action.locator('svg').evaluate(
                    '(svg) => { const box = svg.getBBox(); return box.width > 0 && box.height > 0; }'
                ), 'The action is visible but its icon has no drawing'
            assert edit.inner_text() == '' and copy.inner_text() == ''
            copy.click()
            assert page.evaluate('navigator.clipboard.readText()') == question
            edit.click()
            editor = page.get_by_role('textbox', name='Editar consulta en el chat', exact=True)
            expect(editor).to_have_value(question)
            expect(editor).to_be_focused()
            assert editor.evaluate('(node) => node.getBoundingClientRect().height < 70'), 'Short edits should fit one line'
            assert editor.evaluate('(node) => getComputedStyle(node).outlineStyle === "none" && getComputedStyle(node).borderTopWidth === "0px"'), 'Editing should not add a frame'
            confirm = page.get_by_role('button', name='Enviar consulta editada', exact=True)
            assert confirm.locator('svg path').get_attribute('d') == 'm5 12 4 4L19 6'
            editor.fill('Una línea\nSegunda línea\nTercera línea\nCuarta línea')
            tall = editor.bounding_box()['height']
            assert tall > 100
            editor.fill('Breve')
            assert editor.bounding_box()['height'] < tall
            expect(page.locator('#question')).to_have_value('')
            editor.fill('Cambio descartado')
            editor.press('Escape')
            expect(page.locator('#messages .question-message')).to_have_text(question)
            assert page.locator('#messages .question-message').count() == 1
            assert page.locator('#messages table').count() == 1
        page.set_viewport_size({'width': 390, 'height': 844})
        edit.click()
        editor.fill('Consulta extensa sobre los movimientos de paquetes por departamento y servicio durante la primera semana de noviembre. ' * 6)
        assert editor.evaluate('(node) => node.scrollWidth <= node.clientWidth')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        long_height = editor.bounding_box()['height']
        edited_question = 'describe los campos de users'
        editor.fill(edited_question)
        assert editor.bounding_box()['height'] < long_height
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path='.runtime/qa/question-inline-editor.png')
        page.get_by_role('button', name='Enviar consulta editada', exact=True).click()
        expect(page.locator('#messages table')).to_be_visible(timeout=15000)
        assert page.locator('#messages .question-message').count() == 1
        expect(page.locator('#messages .question-message')).to_have_text(edited_question)
        expect(page.get_by_role('textbox', name='Editar consulta en el chat', exact=True)).to_have_count(0)
        page.locator('#menu-toggle').click()
        page.locator('#new-chat').click()
        page.locator('#menu-toggle').click()
        page.locator('.history-item > button').first.click()
        expect(page.locator('#messages .question-message')).to_have_text(edited_question)
        page.locator('#messages .question-entry').hover()
        copy.click()
        assert page.evaluate('navigator.clipboard.readText()') == edited_question
        expect(copy).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors, errors
        page.screenshot(path='.runtime/qa/question-actions-visible.png')
        browser.close()
    print('PASS: visible icons, inline edit, cancel, resend, persisted history, exact copy and mobile')


if __name__ == '__main__':
    main()
