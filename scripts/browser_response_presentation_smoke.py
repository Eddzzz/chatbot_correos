"""Responses stay readable without technical metadata or redundant pagination."""
import json
import secrets

from playwright.sync_api import expect, sync_playwright
from browser_smoke import BASE, EDGE, manage_user


def check_responses(username, password, base=BASE):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=EDGE)
        context = browser.new_context(permissions=['clipboard-read', 'clipboard-write'])
        page = context.new_page()
        page.goto(base + '/accounts/login/')
        page.locator('#id_username').fill(username)
        page.locator('#id_password').fill(password)
        page.get_by_role('button', name='Ingresar').click()
        expect(page.locator('#workspace')).to_be_visible()
        identity = json.loads(page.locator('#api-identity').text_content())
        headers = {'Content-Type': 'application/json', 'X-Bolipost-User': identity}
        job_id = '00000000-0000-0000-0000-000000000001'
        result = {'id': job_id, 'status': 'ok', 'title': 'Personal', 'answer': 'Personal encontrado: Ana.\nFuente: Personal · fila 1',
                  'history_proof': 'qa-browser-fixture',
                  'analysis': {'generated': True}, 'columns': ['nombre'], 'rows': [{'nombre': 'Ana'}],
                  'source_tables': ['users'], 'filters': {'departamento': 'Pando'}, 'created_at': '2026-11-09T13:00:00Z',
                  'row_count': 1, 'page': 1, 'has_more': False, 'panels': []}
        page.route('**/api/chat/', lambda route: route.fulfill(status=202, headers=headers, body=json.dumps({'id': job_id, 'status': 'queued'})))
        page.route('**/api/results/**', lambda route: route.fulfill(status=200, headers=headers, body=json.dumps(result)))
        saved = {}

        def save_history(route):
            chat_id = route.request.url.split('/')[-3]
            payload = route.request.post_data_json
            summary = {'id': chat_id, 'title': payload['title'], 'updated': len(saved) + 1, 'revision': payload['revision'] + 1}
            saved[chat_id] = {**summary, 'messages': [
                {'kind': 'result', 'result': dict(result), 'proof': message['proof']}
                if message['kind'] == 'result' else message for message in payload['messages']]}
            route.fulfill(headers=headers, json=summary)

        page.route('**/api/conversations/*/save/', save_history)
        page.route('**/api/conversations/*/', lambda route: route.fulfill(
            headers=headers, json=saved[route.request.url.split('/')[-2]]))
        page.locator('#question').fill('Lista personal de Pando')
        page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
        expect(page.locator('#messages table')).to_be_visible()
        actions = page.locator('#messages .result-icon-actions')
        copy = actions.get_by_role('button', name='Copiar resultado', exact=True)
        download = actions.get_by_role('link', name='Descargar PDF', exact=False)
        expect(copy).to_have_attribute('aria-label', 'Copiar resultado')
        expect(download).to_have_text('Descargar PDF')
        expect(download.locator('span')).to_have_class('sr-only')
        expect(actions.locator('.report-export')).to_have_count(0)
        assert download.evaluate('(node) => node.getBoundingClientRect().width === node.getBoundingClientRect().height')
        expect(copy.locator('svg')).to_be_visible()
        expect(download.locator('svg')).to_be_visible()
        assert download.locator('svg').evaluate('(svg) => svg.getBBox().width > 0 && svg.getBBox().height > 0')
        assert actions.evaluate('(node) => !node.closest(".result-card") && getComputedStyle(node).borderTopWidth === "0px" && getComputedStyle(node).backgroundColor === "rgba(0, 0, 0, 0)"')
        page.screenshot(path='.runtime/qa/result-icons-desktop.png')
        page.set_viewport_size({'width': 390, 'height': 844})
        expect(copy).to_be_visible()
        expect(download).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path='.runtime/qa/result-icons-mobile.png')
        page.set_viewport_size({'width': 1280, 'height': 720})
        for restored in (False, True):
            if restored:
                page.locator('#new-chat').click()
                page.get_by_role('button', name='Lista personal de Pando', exact=True).click()
            text = page.locator('#messages .result-card').inner_text()
            for hidden in ('Análisis de IA', 'Fuente:', 'Origen:', 'Filtros:', 'Página 1', 'de 1 filas'):
                assert hidden not in text, hidden
            expect(page.locator('#messages .result-narrative')).to_have_text('Personal encontrado: Ana.')
            assert 'Correos de Bolivia · Respuesta' not in text
            assert 'Resultado guardado en este navegador' not in text
            expect(page.locator('#messages table')).to_contain_text('Ana')
            expect(page.locator('#messages .pagination')).to_have_count(0)
            expect(download).to_be_visible()
            expect(download).to_have_attribute('href', '/api/results/' + job_id + '/pdf/?page=1')
            page.get_by_role('button', name='Copiar resultado', exact=True).click()
            copied = page.evaluate('navigator.clipboard.readText()')
            assert 'Personal encontrado: Ana.' in copied
            assert all(label not in copied for label in ('Fuente:', 'Origen:', 'Filtros:'))
        page.locator('#new-chat').click()
        result.update(row_count=101, has_more=True)
        page.locator('#question').fill('Lista todo el personal')
        page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
        expect(page.locator('#messages table')).to_contain_text('Ana')
        expect(page.locator('#messages .pagination')).to_have_count(0)
        expect(page.get_by_role('button', name='Siguiente', exact=False)).to_have_count(0)
        page.locator('#new-chat').click()
        narrative = 'En junio de 2026 se registraron 1.436 envíos EMS. La Paz fue el destino con más envíos, con 473.'
        totals = dict(index=0, status='ok', title='Totales EMS', columns=['total_envios'],
                      rows=[{'total_envios': 1436}], row_count=1, has_more=False)
        cities = dict(index=1, status='ok', title='Destinos EMS', columns=['ciudad', 'total_envios'],
                      rows=[{'ciudad': 'LA PAZ', 'total_envios': 473}, {'ciudad': 'COCHABAMBA', 'total_envios': 306}],
                      row_count=2, has_more=False, chart={'kind': 'bar', 'labels': ['LA PAZ', 'COCHABAMBA'],
                                                          'values': [473, 306], 'label': 'Envíos'})
        result.update(totals, title='Reporte EMS de junio de 2026', response_type='report', answer=narrative,
                      analysis={'generated': False, 'citations': []}, filters={}, panels=[totals, cities])
        page.locator('#question').fill('Dame un reporte de EMS de junio de 2026')
        page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
        card = page.locator('#messages .result-card')
        expect(card.locator('.result-narrative')).to_have_text(narrative)
        expect(card.locator('canvas')).to_be_visible()
        page.locator('#new-chat').click()
        total_text = 'En junio de 2026 se registraron 1.436 envíos EMS.'
        days = dict(index=1, status='ok', title='Envíos por día', columns=['dia', 'total_envios'],
                    rows=[{'dia': '2026-06-01', 'total_envios': 98}, {'dia': '2026-06-19', 'total_envios': 191}],
                    row_count=2, has_more=False, chart={'kind': 'line', 'labels': ['2026-06-01', '2026-06-19'],
                                                        'values': [98, 191], 'label': 'Envíos'})
        result['panels'] = [totals, days, {**cities, 'index': 2}]
        result['answer'] = '\n\n'.join([
            total_text,
            'Se registraron 98 envíos.\nFuente: Envíos por día · Día · fila 1; Envíos por día · Total de envíos · fila 1',
            'Se registraron 191 envíos.\nFuente: Envíos por día · Día · fila 2; Envíos por día · Total de envíos · fila 2',
            'Cochabamba registra 306 envíos.\nFuente: Destinos EMS · Ciudad · fila 2; Destinos EMS · Total de envíos · fila 2',
            'La Paz registra 473 envíos.\nFuente: Destinos EMS · Ciudad · fila 1; Destinos EMS · Total de envíos · fila 1',
        ])
        page.locator('#question').fill('Resume el reporte de envíos de junio')
        page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
        expect(card.locator('.result-narrative p')).to_have_text(
            total_text + ' El 19 de junio de 2026 fue el día de mayor actividad del reporte, con 191 envíos. '
            'Entre las ciudades del reporte, La Paz registró la mayor cantidad, con 473 envíos.')
        expect(card).to_contain_text('COCHABAMBA')
        expect(card.locator('.report-panels')).to_contain_text('Envíos por día')
        expect(card.locator('.report-panels')).to_contain_text('Destinos EMS')
        page.locator('#new-chat').click()
        clarification = '¿Cuál de los dos paquetes deseas consultar?'
        result.update(status='error', title='Consulta', answer=clarification, error={'code': 'clarification', 'message': clarification},
                      columns=[], rows=[], row_count=0, has_more=False, panels=[])
        page.locator('#question').fill('Todos los datos')
        page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
        expect(page.locator('#messages .result-state')).to_have_text(clarification)
        assert page.locator('#messages').inner_text().count(clarification) == 1
        browser.close()
    print('PASS: clean current/restored/copied answers; pagination controls absent for all results')


def main():
    username, password = 'qa_response_' + secrets.token_hex(6), secrets.token_urlsafe(24)
    manage_user(username, password)
    try:
        check_responses(username, password)
    finally:
        manage_user(username)


if __name__ == '__main__':
    main()
