# Asistente IA: corrección de reportes y dashboards

**Autorización:** el usuario precisó el alcance original: la IA debe responder, generar reportes, resúmenes y dashboards de la base. Se corrige la implementación anterior, limitada a una consulta y respuestas de plantilla, dentro del diseño ya aprobado.

**Arquitectura:** dos llamadas OpenRouter: planificación de consultas seguras y selección de hallazgos a partir de resultados verificados. Django ejecuta todas las consultas, comprueba las afirmaciones estructuradas y produce los valores de tablas/gráficos/PDF. La protección de columnas, autenticación y permisos de solo lectura se conserva.

- [x] Tests RED de planes múltiples, referencias inválidas y reporte extremo a extremo.
- [x] Planes answer/summary/report/dashboard con hasta seis análisis; sin máximo global de filas ni límite temporal SQL.
- [x] Validación individual de todas las consultas antes de ejecutarlas.
- [x] Resultados independientes en disco; paginación y contexto por panel.
- [x] Segunda fase IA con evidencia acotada y advertencia si falla, conservando resultados verificados.
- [x] IR factual: value, comparison, maximum, minimum. El modelo no puede añadir texto factual libre, unidades ni cifras. Comparaciones y extremos se comprueban en el servidor; no se calcula un extremo global desde una muestra.
- [x] API, interfaz, historial, copia y PDF de informes multipanel sin duplicar el panel principal.
- [x] Comando local seguro para configurar servicios sin compartir secretos en el chat.
- [x] Regresiones de cifras/unidades inventadas y de casts temporales SQLite; marcador visible para gráficos de un solo punto.
- [x] Pruebas HTTP con proveedor simulado: planificación → SQL → filas verificadas → hallazgos → reporte.

La prueba con la cuenta OpenRouter del usuario y la restauración completa siguen pendientes de configuración local. Nunca se presentan datos de demostración como operaciones reales.
