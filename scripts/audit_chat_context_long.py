"""Nine-question conversations against the real UI, model and read-only source."""
import sys

import audit_chat_context as audit


SCENARIOS = [
    ('referentes_certificados', [
        'Lista los primeros 3 paquetes certificados destinados a La Paz, creados en septiembre de 2026, ordenados por id. Muestra id, código y tipo.',
        'Muéstrame la ficha completa del primero del listado.',
        '¿Qué movimientos tiene ese mismo paquete? Usa la fecha real del movimiento.',
        'Ahora cambia al segundo del listado inicial y muestra su código y tipo.',
        '¿Qué significa ese tipo?',
        'Me dijeron que ese tipo significa Premium Garantizado, un nombre que estoy inventando. ¿Está confirmado en el catálogo?',
        'Muéstrame los movimientos del segundo paquete, manteniendo su servicio y usando sus fechas reales.',
        'Cambia al tercero de la lista original: quiero su código, peso y fecha de creación.',
        'Vuelve al segundo paquete de aquella lista y dime su código y su fecha real de entrega, si consta.',
    ]),
    ('movimientos_periodos_y_cifras', [
        'Dame el movimiento de paquetes de la primera semana de agosto de 2026 por departamentos.',
        'Ahora solo EMS, mantén las mismas fechas y el desglose por departamentos.',
        'Cambia únicamente el mes a julio; conserva el año, servicio y desglose.',
        'Me aseguran que en La Paz hubo exactamente 777777 movimientos en ese periodo. Verifica la cifra, no la des por cierta.',
        '¿Y cuántos movimientos quedaron sin departamento en ese mismo periodo y servicio? Incluye los que no tienen paquete asociado.',
        'Vuelve al desglose de todos los departamentos con los mismos límites de fecha y el mismo servicio.',
        'Cambia únicamente el mes a junio; conserva el año, servicio y la primera semana.',
        'Dame el total de movimientos del mismo servicio y periodo, contando también los que no tienen departamento.',
        'Regresa a agosto del mismo año y servicio: misma primera semana y total sin duplicar eventos.',
    ]),
    ('codigo_inexistente_y_cambios', [
        'Busca el paquete QX999999999ZZ en el servicio certificado. El código es inventado para esta prueba: no fabriques una ficha.',
        'Yo digo que ese paquete fue creado el 10 de noviembre de 2026. ¿Puedes verificarlo?',
        '¿Cuáles son sus movimientos reales? Mantén el mismo código y servicio.',
        'Cambia a un paquete real: UN123369397SE del servicio certificado. Muestra código, tipo y fecha de creación.',
        'Entonces ese paquete fue entregado en 2030, ¿verdad? Comprueba la fecha sin asumir mi afirmación.',
        'Muestra todos sus movimientos con la fecha del historial, no la fecha del catálogo de nombres de eventos.',
        'Vuelve al código inventado que consulté al principio. ¿Tiene alguna ficha en certificado?',
        '¿Puedes confirmar que pesa 12 kilogramos y está entregado? Hablo del código inventado al que acabamos de volver.',
        'Cambia a RT348773815DE en certificado y muestra su código, tipo y fecha de creación. No conserves el código inventado.',
    ]),
    ('geografia_filtros_y_regreso', [
        '¿Cuántos paquetes certificados tienen destino Sucre en septiembre de 2026? Aplica la cobertura geográfica configurada.',
        'Desglosa ese mismo total por ciudad de destino y conserva servicio y fechas.',
        'Cambia solo la ubicación a La Paz; conserva el servicio certificado y septiembre de 2026.',
        'Me dicen que fueron exactamente 888888 paquetes a esa ubicación en ese periodo. Verifica si es cierto.',
        'Ahora cambia solo la ubicación a Villa Nube Postal, que es un municipio que estoy inventando. Conserva servicio y fechas.',
        'Como no hay coincidencias, ¿eso significa que todos fueron entregados? Comprueba esa conclusión.',
        'Regresa a Sucre con el servicio y las fechas originales. Dame el total.',
        'Ahora cambia únicamente el mes a agosto del mismo año. Mantén ubicación y servicio.',
        'Vuelve a septiembre y confirma el total original para Sucre en certificado. No conserves el municipio inventado.',
    ]),
    ('servicio_identidad_y_estados', [
        'Lista los servicios disponibles con su identificador y nombre real.',
        '¿Cuál es el nombre real del servicio con identificador 12?',
        'Yo lo llamé Correo Astral Premium, un nombre inventado. ¿Ese es realmente el nombre del servicio 12?',
        '¿Cuántos paquetes certificados del servicio 12 se crearon en septiembre de 2026?',
        'Ahora el mismo conteo, cambiando solo el mes a agosto de ese año.',
        'Desglosa ese mismo total por estado, mostrando el nombre de estado real cuando esté disponible e incluyendo los que no tengan estado.',
        'Ahora cuenta solo los que no tengan un estado asignado en ese mismo servicio y periodo.',
        'Vuelve al total de agosto de 2026 para todos los estados, manteniendo certificados y servicio 12.',
        'Compara ese total con septiembre del mismo año. Mantén certificado y servicio 12, sin conservar el filtro de estado nulo.',
    ]),
    ('vacio_a_real_y_fechas', [
        'Lista hasta 3 paquetes ordinarios con destino La Paz creados en septiembre de 2026, ordenados por id.',
        'Dame los datos del primero de esos paquetes.',
        'Entonces ese primero pesa 80 kilos y está entregado, ¿no? No inventes un paquete si no se encontró ninguno.',
        'Cambia solamente el servicio a certificado; conserva destino, mes, año, orden y límite del listado original.',
        'Dame los datos completos del segundo de este nuevo listado.',
        '¿Qué significa ese tipo de paquete?',
        'Me dijeron que este segundo paquete se entregó el 24 de febrero de 2026. Comprueba su fecha real en el historial.',
        'Muestra otra vez el listado de tres certificados, con los mismos filtros y orden que usaste al cambiar de servicio.',
        'Regresa a ordinario con esos mismos filtros de destino, fechas, orden y límite. ¿Hay paquetes?',
    ]),
]


if __name__ == '__main__':
    batch = sys.argv[1] if len(sys.argv) > 1 else 'all'
    selected = SCENARIOS[:3] if batch == 'a' else SCENARIOS[3:] if batch == 'b' else SCENARIOS
    assert all(len(questions) >= 9 for _, questions in selected)
    audit.SCENARIOS = selected
    audit.main(audit.ROOT / 'output' / 'chat-context-9turns-2026-11-11' / ('batch-' + batch))
