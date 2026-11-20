"""Summarize an actual Nemotron run without treating provider failures as semantic passes."""
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
import sys


def generate(folder):
    report = json.loads((folder / 'transcripts.json').read_text(encoding='utf-8'))
    wire = json.loads((folder / 'provider-traffic.json').read_text(encoding='utf-8'))
    chats = report['conversations']
    turns = [turn for chat in chats for turn in chat['turns']]
    assert len(chats) == 6 and all(len(chat['turns']) == 9 for chat in chats)
    assert report.get('finished_at') and all('server_evidence' in turn for turn in turns)
    assert wire['configured_provider'] == 'OpenRouter'
    expected_host = 'openrouter.ai'
    assert all(call['host'] == expected_host for call in wire['calls'])
    provider_success = 0
    local = 0
    blocked = 0
    lines = ['# Conversaciones con Nemotron', '']
    table = ['| Chat | Turno | Estado | HTTP Nemotron |', '|---|---:|---|---|']
    for index, turn in enumerate(turns):
        start = datetime.fromisoformat(turn['result']['created_at'])
        end = datetime.fromisoformat(turns[index + 1]['result']['created_at']) if index + 1 < len(turns) else None
        calls = [call for call in wire['calls'] if datetime.fromisoformat(call['at']) >= start
                 and (end is None or datetime.fromisoformat(call['at']) < end)]
        turn['observed_provider_calls'] = calls
        error = turn['result'].get('error') or {}
        blocked += error.get('code', '').startswith('provider_')
        provider_success += any(call.get('http_status') == 200 for call in calls)
        local += not calls
    for chat in chats:
        lines += ['## ' + chat['name'], '']
        for turn in chat['turns']:
            result = turn['result']
            error = result.get('error') or {}
            state = error.get('code') or result['status']
            statuses = ', '.join(str(call.get('http_status', call.get('transport_error', 'pendiente')))
                                 for call in turn['observed_provider_calls']) or 'sin llamada'
            table.append(f"| {chat['name']} | {turn['number']} | {state} | {statuses} |")
            lines += [f"### Turno {turn['number']}", '', '**Usuario:** ' + turn['question'], '',
                      f'**Estado:** `{state}`. HTTP Nemotron: {statuses}.', '',
                      '**Respuesta:** ' + (error.get('message') or result.get('answer') or '(sin texto)'), '',
                      f"Duración: {turn['elapsed_seconds']} s. Trabajo: `{result['id']}`.", '']
    states = Counter((turn['result'].get('error') or {}).get('code') or turn['result']['status'] for turn in turns)
    traffic = Counter((call.get('http_status'), str(call.get('error_code'))) for call in wire['calls'])
    summary = {'chats': len(chats), 'turns': len(turns), 'provider': wire['configured_provider'],
               'model': wire['configured_model'], 'states': dict(states), 'provider_blocked_turns': blocked,
               'turns_with_at_least_one_http_200': provider_success, 'turns_without_provider_calls': local,
               'browser_errors': report['browser_errors'],
               'traffic': [{'http_status': status, 'error_code': code, 'count': count}
                           for (status, code), count in traffic.items()]}
    (folder / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    report_text = f'''# Auditoría ampliada con Nemotron real

**6 chats de 9 turnos: 54 solicitudes** en Edge real. Modelo: `{wire['configured_model']}`, mediante OpenRouter.

Se repitieron los cuatro chats originales y se añadieron dos sobre referencias, identidad postal inventada, ambigüedad y documentos/correos con instrucciones maliciosas. Los códigos y cifras de prueba fueron inventados; se usó PostgreSQL de solo lectura sin insertar datos de prueba.

## Resultados

- Estados: `{dict(states)}`.
- Turnos bloqueados por errores del proveedor: **{blocked}**.
- Turnos con al menos un HTTP 200 real de Nemotron: **{provider_success}**. Esto no equivale por sí mismo a una respuesta correcta: se aplican después las validaciones del plan y la explicación.
- Turnos sin llamada al proveedor: **{local}**, resueltos por reglas locales. No se atribuyen al modelo.
- Errores JavaScript capturados: **{len(report['browser_errors'])}**.
- HTTP/códigos observados: `{dict(traffic)}`.

## Método y selección de modelo

El harness seleccionó la tupla de proveedor OpenRouter solo dentro de su proceso temporal: endpoint, clave y modelo ya configurados. No se modificó `.env` ni se añadió soporte de proveedor a producción. La selección se sustituyó para esta auditoría; **las respuestas HTTP, reintentos, validación JSON/SQL y evidencia fueron reales**. El transporte conserva las opciones de precio cero y razonamiento desactivado que la aplicación aplica a OpenRouter. Todas las llamadas observadas fueron a `openrouter.ai`, sin fallback a Groq.

Cada chat conservó URL propia y el harness verificó sus `history_ids` en cada envío. Los resultados de llamadas se correlacionaron con los tiempos de creación de trabajos consecutivos; las consultas fueron secuenciales. Los errores no se contabilizan como aprobados.

## Verificación y límites

Las 28 pruebas de transporte/cambio de modelo pasaron. La suite completa ejecutó **191 pruebas**, con **5 omitidas y ningún fallo**; las omitidas requieren PostgreSQL de integración aislado. Estas pruebas con transporte controlado se distinguen de los chats reales.

No se probaron todas las variantes posibles de inyección ni modelos alternativos de Nemotron. Los estados `ok` prueban ejecución de una ruta válida, pero requieren revisar intención y filtros antes de considerarlos un resultado semántico correcto. Los hallazgos de la campaña anterior no se consideran corregidos por repetir las pruebas.

## Evidencia

- `conversaciones.md`: preguntas, respuestas y estados de los 54 turnos.
- `transcripts.json`: resultados, SQL, filtros y estado de contexto.
- `provider-traffic.json`: host, modelo, HTTP, códigos de error, tokens, tamaño de entrada y duración. Sin headers ni claves.
- `summary.json`: métricas calculadas.
- Seis capturas PNG, una por chat.
- `scripts/audit_nemotron_9turns.py`: campaña reproducible; consume cuota real.

## Detalle por turno

''' + '\n'.join(table) + '\n'
    (folder / 'conversaciones.md').write_text('\n'.join(lines), encoding='utf-8')
    (folder / 'informe.md').write_text(report_text, encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    generate(Path(sys.argv[1]))
