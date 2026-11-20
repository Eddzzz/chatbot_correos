# Ampliación de capacidades

**Objetivo:** incorporar las dos áreas elegidas por el usuario: análisis postal y herramientas del chat.

**Diseño:** conservar Django, las consultas de solo lectura y la evidencia guardada. Añadir tres skills editables (demoras, cumplimiento de plazos y comparación de períodos). El agente debe pedir el plazo y la definición de entrega cuando no estén documentados; no inferir entregas a partir del último evento. Incorporar exportaciones CSV por panel y Excel con una hoja por panel, de todas las filas verificadas, sin volver a consultar el origen. Rastrear hasta seis códigos por solicitud, un panel por código, conservando la resolución de ambigüedades existente. Exponer permisos separados para CSV, Excel y lotes.

**Alternativas:** solo instrucciones no resuelven las descargas ni el rastreo determinista; sustituir el motor de consultas excede el alcance. Se amplían las rutas y el planificador existentes.

**Validación:** pruebas primero para aislamiento, caducidad, permisos, exportación completa, fórmulas, códigos con ceros iniciales, códigos inválidos y rastreos ambiguos. Verificar migración repetible y preservación de skills editadas. Comprobar interfaz con navegador en móvil y escritorio.

- [x] Exportación CSV/Excel: pruebas, endpoints, permisos, botones.
- [x] Rastreo por lotes: pruebas, validación compartida, chat y formulario.
- [x] Skills de análisis: migración con definiciones congeladas, pruebas y documentación.
- [x] Ejecutar pruebas relacionadas y verificación visual.

Verificación: suite completa de 355 pruebas (5 omitidas por requisitos de integración);
55 pruebas finales del área afectada y 11 específicas de capacidades correctas.
Edge aislado: skills en ambos temas y seis anchos; rastreo, chat, CSV por panel,
Excel con hojas completas, avisos de ambigüedad y selector de panel en informes
compactos en ambos temas y cuatro anchos, sin errores JavaScript.
Revisión independiente: corregidos encabezados interpretables como fórmulas,
avisos ocultos y exportación de paneles compactos; segunda revisión sin hallazgos.
Migración 0011 aplicada localmente y servidor reiniciado; HTTP 200,
tres nuevas capacidades habilitadas y tres nuevas skills activas confirmadas.

Decisión: ejecutar en el directorio actual, que no es un repositorio Git. Las pruebas y el navegador utilizan cuentas, configuración y resultados temporales.
