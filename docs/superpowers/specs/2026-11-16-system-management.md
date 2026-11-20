# Administración del sistema

El administrador (superusuario Django activo) administra proveedores y modelos existentes,
claves, tiempos de conexión, origen postal, agentes planificador/analista y capacidades
del asistente, incluyendo skills de instrucciones por agente. Los usuarios normales no acceden a configuración ni a chats ajenos.
Se conserva la interfaz institucional, con página de ajustes y papelera adaptables.

Configuración persistente en archivo privado del servidor, escritura atómica y campos
secretos nunca precargados ni incluidos en respuestas. La configuración nueva aplica a
consultas nuevas, sin alterar los controles SQL ni los datos postales. No se ejecutan
scripts arbitrarios como skills: se administran las capacidades de la aplicación.

Historial centralizado por usuario con importación del IndexedDB existente al abrirlo.
Papelera compartida entre dispositivos, restauración y purga después de 30 días desde
la eliminación. Revisiones impiden sobrescrituras y resurrección desde pestañas antiguas.
Los resultados temporales conservan su vigencia de 24 horas, independiente del chat.
La purga se ejecuta periódicamente mientras el servicio está activo y al iniciar/acceder;
un comando permite usar un programador externo cuando la app está detenida.

El panel presenta conexiones y comprobación explícita de DB, caché temporal, chats,
consumo real informado por proveedor (incluidos reintentos), por usuario/modelo/agente.
No calcula saldo ni facturación que el proveedor no informa. Las auditorías no contienen claves.
