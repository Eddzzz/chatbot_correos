"""Verify the recorded nine-turn runs and publish their findings and transcripts."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/chat-context-9turns-2026-11-11'
load = lambda path: json.loads(path.read_text(encoding='utf-8'))
reports = [load(OUT / f'batch-{batch}/transcripts.json') for batch in ('a', 'b')]
reference = load(OUT / 'reference.json')
chats = [chat for report in reports for chat in report['conversations']]
turns = [turn for chat in chats for turn in chat['turns']]
assert len(chats) == 6 and len(turns) == 54
assert all(len(chat['turns']) == 9 for chat in chats)
assert all(report.get('finished_at') and not report['browser_errors'] for report in reports)
assert all(turn['http_status'] == 202 for turn in turns)
assert all(turn['request'].get('history_ids', []) == [old['result']['id'] for old in chat['turns'][:index]
           if old['result']['status'] in ('ok', 'no_matches', 'empty_table') or
           old['result']['status'] == 'error' and (old['result'].get('error') or {}).get('code') == 'clarification'][-12:]
           for chat in chats for index, turn in enumerate(chat['turns']))


def result(chat, number):
    return chats[chat - 1]['turns'][number - 1]['result']


def cells(chat, number):
    return [value for row in result(chat, number).get('rows', []) for value in row.values()]


def total(chat, number, field):
    return sum(row[field] for row in result(chat, number)['rows'])


assert [row['codigo'] for row in result(1, 1)['rows']] == [row['codigo'] for row in reference['geography']['09_La Paz']['first_three']]
assert 'RT348773815DE' in cells(1, 4)
assert 'UN123369397SE' in cells(1, 8)
assert '2026-09-02T15:55:10' in cells(1, 8)
assert 'no documenta' in result(1, 5)['answer']
assert total(2, 1, 'total_movimientos') == sum(reference['queries']['todos_servicios_agosto_' + family]['rows'][0]['total_movimientos'] for family in ('ems', 'certi', 'contrato', 'ordi'))
for number, month in ((2, '08'), (3, '07'), (8, '06')):
    assert total(2, number, 'total_movimientos') == reference['queries']['ems_total_' + month]['rows'][0]['total_movimientos']
assert cells(2, 5) == [76]
assert cells(2, 7) == [315]
assert 'UN123369397SE' in cells(3, 4)
assert sorted(value for value in cells(3, 5) if isinstance(value, str) and value.startswith('2026-')) == sorted(row['fecha_movimiento'] for row in reference['queries']['historial_UN123369397SE']['rows'])
assert 'RT348773815DE' in cells(3, 9)
for number, place in ((1, 'Sucre'), (2, 'Sucre'), (3, 'La Paz'), (4, 'La Paz')):
    assert total(4, number, 'total_envios') == reference['geography']['09_' + place]['total']
assert result(5, 1)['row_count'] == reference['queries']['servicios']['row_count']
assert 'CERTIFICADAS' in cells(5, 2) and 'CERTIFICADAS' in cells(5, 3)
assert result(6, 1)['status'] == 'no_matches'

# Confirm the failures as observed, independently of the application's success status.
assert '<<CODIGO>>' in result(3, 3)['sql']
assert 'QX999999999ZZ' not in result(3, 3)['sql']
assert result(3, 6)['title'] == 'Estructura: eventos'
assert not result(3, 6)['sql']
assert 'UN123369397SE' in result(3, 7)['sql'] and 'QX999999999ZZ' not in result(3, 7)['sql']
assert 'UN123369397SE' in result(3, 8)['sql']
assert {'eventos_certi', 'eventos_ems', 'eventos_contrato', 'eventos_ordi'} <= set(result(5, 8)['source_tables'])
assert 'paquetes_certi' not in result(5, 8)['source_tables']
assert reference['queries']['servicio12_08']['total'] == 1079
assert chats[2]['turns'][1]['request'].get('history_ids', []) == []

errors = Counter((turn['result'].get('error') or {}).get('code') for turn in turns if turn['result'].get('error'))
warnings = [{'chat': index + 1, 'turn': turn['number'], 'warning': turn['result']['analysis']['warning']}
            for index, chat in enumerate(chats) for turn in chat['turns'] if turn['result'].get('analysis', {}).get('warning')]
summary = {'chats': 6, 'questions_per_chat': 9, 'questions': 54,
           'statuses': dict(Counter(turn['result']['status'] for turn in turns)),
           'errors': dict(errors), 'provider_blocked': errors['provider_credit'] + errors['provider_unavailable'],
           'data_without_ai_explanation': warnings, 'browser_errors': 0, 'history_payload_checks': 54,
           'note': 'An HTTP/application ok is not a semantic pass. Provider failures cannot establish whether context was retained.'}
(OUT / 'verification.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

findings = {
    (1, 2): 'Petición no resuelta: el proveedor no produjo un plan autorizado.',
    (1, 6): 'Respuesta incompleta: buscar tipo = Premium Garantizado no verifica qué significa PG ni si esa definición está documentada.',
    (1, 7): 'Petición no resuelta: plan inválido al volver a los movimientos del segundo paquete.',
    (2, 7): 'El dato 315 coincide con EMS sin departamento de junio. El regreso a todos los departamentos del mensaje 6 había fallado; la cadena quedó interrumpida y se arrastró el último filtro exitoso.',
    (3, 2): 'Pide otra vez código y servicio que el usuario escribió en el mensaje 1. Ese mensaje falló por saldo y la petición 2 no envió historial: el código desapareció del contexto enviado.',
    (3, 3): 'Fallo: consultó el texto literal <<CODIGO>> y cuatro servicios, en lugar de QX999999999ZZ en certificado o solicitar el identificador faltante.',
    (3, 6): 'Fallo: la palabra catálogo junto con eventos activó la respuesta de estructura; no devolvió los movimientos solicitados.',
    (3, 7): 'Fallo de referente: al volver al código inventado, consultó UN123369397SE, que es un paquete real.',
    (3, 8): 'Fallo arrastrado de referente: respondió con el peso 0.710 y estado ENTREGADO del paquete real, aunque el usuario reiteró que hablaba del código inventado.',
    (4, 4): 'La tabla contiene 1599, correcto. La explicación quedó bloqueada por saldo y no hubo una negativa explícita a la cifra propuesta 888888.',
    (5, 7): 'Petición no resuelta: no se generó un plan autorizado para contar los paquetes sin estado.',
    (5, 8): 'Fallo de alcance y métrica: se pidieron paquetes certificados del servicio 12; devolvió eventos de cuatro servicios sin filtro servicio 12. La referencia correcta es 1079 paquetes.',
    (6, 2): 'Aclaración adecuada: la lista está vacía y no hay un primer paquete que pueda detallarse.',
}

md = ['# Conversaciones completas · seis chats de nueve preguntas', '',
      'Ejecución real en Edge con el proveedor y PostgreSQL configurados. Cada chat contiene nueve preguntas y nueve respuestas del sistema, incluidos sus errores. '
      'Las URLs dependen del historial del navegador aislado usado en la prueba; esta transcripción permite revisarlas sin esa sesión.', '']
for index, chat in enumerate(chats, 1):
    md.extend([f"## Chat {index}: {chat['name']}", '', f"URL de prueba: {chat['turns'][0]['chat_url']}", ''])
    for turn in chat['turns']:
        value = turn['result']
        md.extend([f"### Pregunta {turn['number']}", '', turn['question'], '',
                   f"**Respuesta:** {value['title']} · Estado `{value['status']}` · {turn['elapsed_seconds']} s · {len(turn['request'].get('history_ids', []))} referencias previas enviadas.", '',
                   value.get('answer', ''), ''])
        if value.get('error'):
            md.extend(['**Código del error:** `' + value['error']['code'] + '`.', ''])
        if value.get('analysis', {}).get('warning'):
            md.extend(['**Aviso mostrado:** ' + value['analysis']['warning'], ''])
        if (index, turn['number']) in findings:
            md.extend(['**Revisión:** ' + findings[index, turn['number']], ''])
        for panel in value.get('panels', []):
            md.extend([f"**Panel:** {panel['title']} · {panel['row_count']} filas", '',
                       '```json', json.dumps(panel.get('rows', [])[:3], ensure_ascii=False, indent=2), '```', ''])
(OUT / 'conversaciones.md').write_text('\n'.join(md) + '\n', encoding='utf-8')

report = '''# Auditoría de contexto · seis chats de nueve preguntas · 11 de noviembre de 2026

**Resultado: el chatbot no conserva el contexto de forma fiable en estos casos.** Se ejecutaron 54 peticiones desde la interfaz real: seis chats independientes, cada uno con nueve preguntas y nueve respuestas del sistema. Se probaron paquetes, movimientos, fechas, geografía, servicios, estados y premisas inventadas. Se guardaron respuestas, SQL, tablas, payloads y capturas, sin simular al proveedor ni modificar registros postales.

## Límite de la ejecución

OpenRouter devolvió errores de saldo durante la prueba. No se puede afirmar que se completaron seis conversaciones de nueve respuestas útiles ni atribuir esos errores a la memoria del modelo.

| Estado técnico | Cantidad | Interpretación |
|---|---:|---|
| `ok` | 25 | Respondió; varios de estos resultados son semánticamente incorrectos |
| `no_matches` | 2 | Uno es una lista vacía válida; el otro buscó un marcador inventado en lugar del código solicitado |
| Error de saldo | 21 | Contexto no evaluable en esa respuesta |
| Error de conexión al proveedor | 1 | Contexto no evaluable en esa respuesta |
| Plan no válido o no autorizado | 3 | La petición no se resolvió |
| Aclaraciones | 2 | Una reconoce una lista vacía; otra vuelve a pedir un código que quedó fuera del contexto tras un error previo |

Otros cinco resultados `ok` conservaron sus tablas, pero mostraron aviso de que no se pudo generar la explicación por saldo insuficiente. Estos cinco no se suman a los 21 errores de saldo anteriores. No hubo errores JavaScript. Las 54 peticiones enviaron los identificadores que establece el filtro actual de la interfaz y no mezclaron identificadores entre chats.

## Hallazgos principales

### 1. Se confunde un código inventado con un paquete real

Chat 3, pregunta 1: se solicitó **QX999999999ZZ**, inventado, en certificado. Esa petición falló por saldo. La pregunta 2 volvió a pedir código y servicio y su payload no incluyó historial. En la pregunta 3, el chatbot ejecutó una consulta sobre el texto literal **`<<CODIGO>>`** y cuatro servicios; luego dijo que no había coincidencias. No consultó el código del usuario.

Después sí identificó correctamente **UN123369397SE** cuando el usuario lo escribió de forma explícita. Sin embargo, en la pregunta 7, «Vuelve al código inventado que consulté al principio», recuperó la ficha de **UN123369397SE**. En la pregunta 8 siguió usando ese paquete real y mostró peso **0.710** y estado **ENTREGADO**, aunque el usuario reiteró que hablaba del código inventado. No creó una fila postal: atribuyó datos de otra entidad al referente equivocado.

La causa comprobada del hueco inicial está en la selección del historial: `chatContext` solo envía resultados exitosos, vacíos y aclaraciones. Los mensajes con error de saldo, conexión o plan quedan fuera. `chat_view` también rechaza esos estados como contexto. Así se pierden preguntas y códigos escritos por el usuario en turnos fallidos. Con la información restante, el modelo debería pedir el dato faltante y no sustituirlo por el último código real.

### 2. Se pierden servicio y métrica explícitos

Chat 5, pregunta 8: «Vuelve al total de agosto de 2026 para todos los estados, manteniendo certificados y servicio 12». La referencia independiente es **1079 paquetes** en `paquetes_certi` con `servicio_id = 12`.

La respuesta se tituló como total para certificados y servicio 12, pero consultó `eventos_certi`, `eventos_ems`, `eventos_contrato` y `eventos_ordi`, sin ese filtro de servicio. Mostró **2090, 8220, 77053 y 622 eventos**. El SQL es de lectura y las cifras provienen de la base, pero no responden a lo solicitado. El estado técnico fue `ok` y hubo narración de IA, por lo que el error puede pasar por un resultado verificado correcto.

Varias preguntas anteriores de este chat habían fallado y quedaron fuera del historial. Aun así, esta pregunta reiteraba de forma explícita certificado, servicio 12 y agosto de 2026, criterios que la respuesta no respetó.

### 3. Una aclaración sobre fechas activa la estructura del catálogo

Chat 3, pregunta 6: «Muestra todos sus movimientos con la fecha del historial, no la fecha del catálogo de nombres de eventos».

El chatbot devolvió **«Estructura: eventos»**, cuatro filas de metadatos, sin consultar movimientos. Se reprodujo la decisión del clasificador leyendo `_catalog_answer`: detecta la palabra `catálogo` y el nombre `eventos`, aunque la frase expresa que no se desea usar esa fecha. Es un error de interpretación de intención; no demuestra por sí solo un fallo de memoria del modelo.

### 4. La verificación de significados sigue siendo incompleta en algunas formulaciones

Chat 1, pregunta 5, «¿Qué significa ese tipo?», explicó correctamente que **PG** no tiene una equivalencia documentada. Pero al proponer después «Premium Garantizado» como nombre inventado, la pregunta 6 buscó filas donde `tipo = 'Premium Garantizado'` y devolvió cero. Esa búsqueda no verifica si PG significa ese nombre ni si existe documentación de la equivalencia.

## Comprobaciones que sí conservaron datos y contexto

| Secuencia | Resultado contrastado |
|---|---|
| Chat 1, lista inicial → segundo → tercero | Identificó RT348773815DE y luego UN123369397SE; el tercero conserva peso 0.710 y creación 2026-09-02T15:55:10 |
| Chat 2, primera semana de agosto → solo EMS → julio | Totales EMS de 1195 y 2087, coincidentes con SQL independiente |
| Chat 2, movimientos sin departamento de julio | 76, incluidos eventos sin paquete asociado |
| Chat 2, total EMS de primera semana de junio | 957, con y sin departamento |
| Chat 3, código real escrito explícitamente | UN123369397SE y después RT348773815DE se recuperaron correctamente |
| Chat 3, intento de fecha futura 2030 | Mostró eventos reales de UN123369397SE del 2 de septiembre de 2026, sin inventar eventos de 2030 |
| Chat 4, Sucre → desglose → La Paz | Conservó certificado y septiembre de 2026: 16 para Sucre y 1599 para La Paz |
| Chat 5, nombre del servicio 12 → alias inventado | Conservó el nombre real CERTIFICADAS |
| Chat 6, lista vacía → primer paquete | Reconoció que no había paquetes para detallar; no fabricó el primero |

En el chat 2, el regreso a todos los departamentos de la pregunta 6 falló por saldo. La pregunta 7 conservó el último filtro exitoso «sin departamento» y devolvió **315** para junio. Esa cifra es correcta para ese subconjunto, pero la cadena que el usuario intentaba continuar quedó interrumpida. No se presenta como una prueba aislada de conservación completa del contexto.

## Qué falta para cerrar la evaluación

- Corregir los cambios de referente y alcance observados, y la selección de historial tras errores.
- Afinar el clasificador de consultas de esquema para frases con negaciones o aclaraciones.
- Repetir los 22 turnos bloqueados por el proveedor y sus continuaciones una vez disponible el servicio. No basta con ejecutar solo la última pregunta: hace falta reconstruir cada chat desde el principio.

Esta ejecución fue una auditoría: no se cambiaron las reglas del chatbot. Las respuestas fallidas y los errores del proveedor se conservan en la evidencia; no se sustituyeron por pruebas simuladas.

## Archivos

- [Las 54 preguntas y respuestas, con revisión](conversaciones.md).
- [Transcripciones originales de los chats 1 a 3](batch-a/transcripts.json).
- [Transcripciones originales de los chats 4 a 6](batch-b/transcripts.json).
- [SQL y resultados de referencia](reference.json).
- [Conteos de ejecución y avisos](verification.json).
- Cada carpeta de lote contiene una captura al final de cada chat.
'''
(OUT / 'informe.md').write_text(report, encoding='utf-8')
print(json.dumps(summary, ensure_ascii=True))
