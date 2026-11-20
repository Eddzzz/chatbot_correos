"""Exercise real UI conversations and keep provider/database evidence for review."""
import json
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

from browser_smoke import BASE, EDGE, ROOT, credentials


SCENARIOS = [
    ('paquete_y_sigla', [
        'Dame los datos del paquete certificado LX094728722NL.',
        '¿Qué tipo de paquete es?',
        '¿Qué es PG?',
        'Entonces PG significa Premium Garantizado y llegó ayer, ¿verdad? Comprueba ambas cosas.',
        'Muéstrame todos los datos y movimientos del mismo paquete, conservando su código y servicio.',
    ]),
    ('periodo_y_servicio', [
        'Dame el movimiento de paquetes de la primera semana de junio por departamentos.',
        '2026',
        'Ahora solo EMS, mantén las mismas fechas y el desglose por departamentos.',
        'Cambia únicamente el mes a julio; conserva el año, servicio y desglose.',
        'Yo digo que en La Paz hubo exactamente 999999 movimientos en ese periodo. Verifícalo sin asumir que mi cifra es cierta.',
    ]),
    ('lista_y_referente', [
        'Lista los primeros 3 paquetes ordinarios con destino La Paz registrados en septiembre de 2026, ordenados por id.',
        'Dame todos los datos del primero de esos tres.',
        'Ahora muéstrame los movimientos de ese mismo paquete.',
        '¿Puedes confirmar que ese paquete fue entregado ayer? Usa solo las fechas y eventos reales disponibles.',
        'Vuelve al listado inicial de tres paquetes con los mismos filtros y orden.',
    ]),
    ('codigo_inventado_y_cambio', [
        'Busca el paquete ZZ000000000ZZ en todos los servicios. El código es inventado para esta prueba; no inventes una ficha.',
        '¿Y cuáles son sus movimientos?',
        'Entonces figura como entregado, ¿sí o no? No confundas ausencia de registros con entrega.',
        'Cambia de paquete: busca LX094728722NL en el servicio certificado.',
        '¿Cuál es su tipo y su fecha de creación? Usa el paquete que acabo de indicar.',
    ]),
    ('geografia_y_premisa_falsa', [
        '¿Cuántos paquetes ordinarios tienen destino Trinidad en septiembre de 2026?',
        'Desglosa ese mismo total por ciudad, manteniendo el servicio y las fechas.',
        'Ahora cambia solo la ubicación a Santa Cruz; conserva servicio y periodo.',
        'En ese mismo periodo, ¿cuántos fueron a Villa Nube Postal, el municipio que acabo de inventar? No lo asignes a un departamento real.',
        'Regresa a Trinidad con el servicio y fechas originales. ¿Cuál era el total verificado?',
    ]),
]


def main(out=None):
    out = Path(out) if out else ROOT / 'output' / 'chat-context-audit-2026-11-11'
    out.mkdir(parents=True, exist_ok=True)
    report = {'started_at': datetime.now().isoformat(), 'base': BASE,
              'method': 'Real Edge UI, actual provider and configured database, no mocked replies',
              'conversations': [], 'browser_errors': []}

    def save():
        (out / 'transcripts.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=EDGE)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        page = context.new_page()
        page.on('pageerror', lambda error: report['browser_errors'].append(str(error)))
        username, password = credentials()
        page.goto(BASE + '/accounts/login/')
        page.locator('#id_username').fill(username)
        page.locator('#id_password').fill(password)
        page.get_by_role('button', name='Ingresar').click()
        expect(page.locator('#workspace')).to_be_visible()
        identity = json.loads(page.locator('#api-identity').text_content())
        headers = {'X-Bolipost-User': identity}
        report['server_status'] = context.request.get(BASE + '/api/status/', headers=headers).json()
        assert report['server_status']['assistant_configured'], 'Real provider is not configured'
        for name, questions in SCENARIOS:
            page.locator('#new-chat').click()
            chat = {'name': name, 'turns': []}
            report['conversations'].append(chat)
            accepted_ids = []
            for number, question in enumerate(questions, 1):
                print(f'START {name} {number}/{len(questions)}: {question}', flush=True)
                start = time.monotonic()
                page.locator('#question').fill(question)
                with page.expect_response(lambda response: response.url == BASE + '/api/chat/' and response.request.method == 'POST', timeout=30000) as created:
                    page.locator('#chat-form').evaluate('(form) => form.requestSubmit()')
                response = created.value
                payload = response.request.post_data_json
                turn = {'number': number, 'question': question, 'request': payload,
                        'http_status': response.status, 'chat_url': page.url}
                chat['turns'].append(turn)
                assert payload.get('history_ids', []) == accepted_ids[-12:], 'UI history differs from accepted results in this chat'
                if response.status != 202:
                    turn['result'] = response.json()
                    save()
                    raise RuntimeError(f'Unexpected chat HTTP {response.status}')
                job_id = response.json()['id']
                expect(page.locator('#chat-form button[type="submit"]')).to_be_enabled(timeout=420000)
                result = context.request.get(BASE + f'/api/results/{job_id}/?page=1', headers=headers).json()
                result.pop('history_proof', None)
                turn.update(result=result, elapsed_seconds=round(time.monotonic() - start, 2),
                            rendered_text=page.locator('#messages > .message').last.inner_text()[:16000])
                if result['status'] in ('ok', 'no_matches', 'empty_table') or result['status'] == 'error' and (result.get('error') or {}).get('code') == 'clarification':
                    accepted_ids.append(job_id)
                print(f"DONE {name} {number}: {result['status']} rows={result.get('row_count')} {turn['elapsed_seconds']}s; {result.get('title')}; {str(result.get('answer', ''))[:450]}", flush=True)
                save()
            assert len(chat['turns']) >= 5
            page.screenshot(path=str(out / (name + '.png')), full_page=True)
        browser.close()
    report['finished_at'] = datetime.now().isoformat()
    save()
    print('COMPLETE: ' + str(out / 'transcripts.json'), flush=True)


if __name__ == '__main__':
    main()
