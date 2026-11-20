# Correcciones de la auditoría de chats

Objetivo autorizado: corregir fallos observados con Nemotron, conservando solo lectura, evidencia y aislamiento de sesiones.

1. Reproducir con pruebas de regresión el rechazo insuficiente de escritura, las fechas imposibles, aclaraciones forzadas a SQL y la comparación incompleta de totales.
2. Añadir validación de preguntas antes de rutas locales/modelo. Mantener consultas de lectura que mencionen borrado y continuaciones válidas.
3. Compactar solo expansiones geográficas reconocidas por equivalencia exacta con el normalizador del servidor. Conservar SQL ejecutado, filtros, fechas y referencias; probar también contextos históricos existentes.
4. Calcular comparaciones con el total únicamente sobre agrupaciones COUNT completas, aditivas y verificadas; no sumar muestras, conteos distintos, grupos filtrados ni resultados truncados.
5. Distinguir 413 upstream de cuota Groq (respaldo permitido) de solicitudes grandes genéricas (mensaje específico); mantener reintentos acotados y no disfrazar autenticación/JSON inválido.
6. Ejecutar regresiones dirigidas, suite Django completa, comprobación de migraciones y JS. Repetir casos reales con Nemotron si hay cuota; registrar bloqueos del proveedor sin calificarlos de aprobados.

Ámbitos paralelos sin sobrescribir archivos ajenos: validación en módulo nuevo; compresión de contexto; funciones de transporte. El agente principal integra ai/jobs y verificación de cifras, revisa cambios y ejecuta la suite completa.
