# Asistente Bolipost: diseño técnico

Fecha: 2026-11-05. Estado: aprobado por el usuario; implementación autorizada.

## Intención y alcance confirmado

Construir una aplicación web en español para consultar el respaldo de Correos de Bolivia. Los usuarios tendrán cuentas con contraseña, chat contextual, rastreo, explicaciones del catálogo, resúmenes, dashboards, copia de respuestas y descarga PDF. Cada usuario podrá guardar, buscar y eliminar su historial en el navegador. La interfaz funcionará en escritorio y móvil, con tema claro y oscuro e identidad de Bolipost.

El usuario eligió Django. La IA será `openai/gpt-oss-20b` mediante OpenRouter, nunca un modelo ejecutado localmente. PostgreSQL será local inicialmente. Las consultas postales serán exclusivamente de lectura, sin imponer un máximo fijo de filas ni el límite de 10 segundos que se descartaron.

## Evidencia del entorno

- Proyecto inicialmente vacío: `D:\edwin\Documents\chatbotcorreos`.
- Respaldo: `D:\edwin\Documents\correos\backapsiop\backapsiop.sql`, 15.396.364.706 bytes.
- El archivo es un archivo PostgreSQL custom (`PGDMP`), no SQL de texto.
- `pg_restore --list` verificó 122 entradas TABLE del esquema public.
- La extracción del esquema verificó 122 definiciones CREATE TABLE y 159 claves foráneas; no se leyeron filas de negocio.
- PostgreSQL 18.6 está instalado en `D:\Program Files\PostgreSQL\bin` y escucha en el puerto 5432.
- La conexión TCP requiere contraseña. No se verificó todavía el contenido de ninguna base activa.
- Python 3.12.10 y Node 24.22.1 están disponibles.

## Enfoques considerados

1. **Django con plantillas y JavaScript:** una aplicación, autenticación integrada y conexión directa a PostgreSQL. Menos despliegues y menor configuración. Elegido por el usuario.
2. **FastAPI y React:** frontend independiente y API propia, con más configuración de autenticación y dos entornos de construcción. Descartado en favor de la simplicidad de Django.

El detalle siguiente propone decisiones del implementador; la elección de Django es la única decisión de stack confirmada explícitamente.

## Arquitectura propuesta

Una aplicación Django sirve páginas, archivos estáticos y endpoints JSON bajo `/api/`. El navegador nunca accede directamente a PostgreSQL ni a OpenRouter. Se usan plantillas HTML, CSS y JavaScript sin compilación de frontend; Chart.js representa gráficos de datos y una biblioteca PDF con fuente Unicode genera descargas.

Dos almacenes separados:

- **Aplicación:** SQLite inicialmente, mediante ORM de Django, para cuentas y sesiones. No importa cuentas ni contraseñas del respaldo. El administrador crea usuarios con comandos o el administrador de Django; no habrá registro público por defecto.
- **Negocio:** restauración en una base PostgreSQL nueva e identificable, sin sobrescribir bases existentes. Django conecta con un rol restringido a datos autorizados y no ejecuta migraciones en ella.

El módulo de acceso a datos expone catálogo, consulta validada, agregados y rastreo. Una futura integración por API sustituirá ese módulo manteniendo los contratos del frontend; construir esa conexión futura queda fuera de esta entrega.

## Preparación del respaldo

Primero se extrae el esquema con `pg_restore --schema-only --no-owner --no-privileges --file=-` y se revisan tablas, relaciones, funciones y extensiones. La restauración usa una base separada y no acepta SQL arbitrario introducido desde la interfaz. El proceso debe negarse a restaurar sobre una base existente por defecto. Se documentan comandos de restauración y creación del rol de consulta; no se incluyen contraseñas en comandos, registros o repositorio.

El esquema real, no el número esperado de tablas, determina el catálogo. Se mostrará la fecha del respaldo solamente si existe evidencia en sus metadatos. La ausencia de credenciales PostgreSQL no impide implementar y probar con fixtures; sí impide afirmar que la restauración o la integración real funcionan.

## Autenticación e historial

Autenticación y sesiones de Django, contraseñas con los hashers de Django, CSRF en toda operación autenticada y cookies HttpOnly y SameSite. En desarrollo local HTTP no se exige cookie Secure; en producción HTTPS sí. Cierre de sesión por POST. Todos los endpoints de datos requieren sesión. Las credenciales de OpenRouter permanecen en el servidor.

El historial vive en IndexedDB y se separa por identificador estable del usuario autenticado. Al cerrar sesión se elimina de la pantalla y de la memoria el contexto actual. Ninguna cuenta puede abrir desde la aplicación el historial de otra. No se sincroniza entre navegadores ni dispositivos. Quien tenga acceso al perfil del navegador puede inspeccionar su almacenamiento local: esta separación no equivale a cifrado del dispositivo.

El navegador guarda mensajes y referencias de filtros, pero no contraseñas ni claves API. El backend no confía en SQL, resultados ni permisos recibidos desde el historial: revalida y vuelve a consultar lo necesario. La búsqueda y la eliminación del historial actúan únicamente sobre la cuenta actual. Se informa si el navegador no puede guardar datos.

## Catálogo y privacidad

Se documentan las 122 tablas, sus campos y relaciones verificadas en el esquema. Una relación inferida se etiqueta como tal; no se inventan descripciones de campos desconocidos.

Una política explícita de tablas y columnas autorizadas determina qué datos de negocio pueden consultarse. Las tablas de sesiones, tokens, contraseñas, auditorías, telemetría y colas no exponen filas a la IA ni al usuario. Su presencia puede aparecer como metadatos del catálogo, sin valores ni defaults sensibles.

Las columnas permitidas se proyectan en vistas de un esquema de consulta separado. El rol de negocio solo puede consultar esas vistas y no las tablas originales. Se ocultan contraseñas, tokens, secretos, documentos de identidad, teléfonos, correos personales, domicilios precisos, ubicaciones precisas y archivos/fotos, salvo que una revisión futura autorice explícitamente algún dato necesario. Las columnas nuevas quedan denegadas hasta revisión. JSON, texto libre y registros de auditoría no se consideran seguros por su nombre: quedan fuera de las vistas salvo aprobación explícita por campo.

La selección inicial autoriza únicamente datos necesarios para envíos, movimientos, sucursales y personal laboral (nombre, cargo y sucursal cuando el esquema lo permita). Antes de habilitar cada columna se inspecciona su definición y propósito. La misma política se aplica a consultas, contexto, gráficos, PDF, errores y logs. No basta con ocultar columnas después de ejecutar SQL: tampoco se permite filtrar ni agregar sobre columnas prohibidas.

## Consultas de solo lectura

La defensa combina:

1. Rol sin permisos de escritura, creación de objetos ni acceso a tablas originales; privilegios efectivos verificados en la base aislada, incluidos los heredados de PUBLIC.
2. Transacciones de consulta READ ONLY y `search_path` controlado.
3. Parseo de SQL con un parser PostgreSQL, por ejemplo sqlglot: una sola sentencia SELECT o WITH que contenga únicamente consultas de lectura, sobre vistas autorizadas.
4. Validación de todos los nodos, subconsultas, fuentes y funciones: se rechazan escritura dentro de CTE, SELECT INTO, bloqueos, comandos de sesión, catálogos del sistema, funciones definidas por el usuario y funciones no incluidas en una lista explícita. Se permiten solo operadores y funciones de consulta necesarias, como agregados y funciones temporales aprobadas.
5. Parámetros enlazados para valores en rastreo y operaciones predefinidas. Nunca se concatena texto de usuario en SQL.

No se establece un máximo global de filas ni `statement_timeout` de 10 segundos. La interfaz pagina resultados con cursores del servidor y lectura por lotes para no cargar el respaldo completo en memoria. El tamaño de lote es un detalle de transporte, no un límite del total consultable. Se ofrece cancelar consultas; al cerrar sesión, cancelar o abandonar un resultado se cierran sus recursos. Los cursores y resultados temporales pertenecen a la sesión que los creó.

Los presupuestos de contexto de OpenRouter y la paginación se explican cuando apliquen. No se afirma que el modelo leyó todas las filas si recibió una muestra. Los resúmenes globales y gráficos usan consultas agregadas verificadas sobre el conjunto solicitado, no extrapolaciones de una página.

## Flujo de chat y contexto

1. El servidor recibe la pregunta y contexto acotado de la conversación autenticada.
2. Selecciona metadatos pertinentes del catálogo autorizado y solicita un plan estructurado a OpenRouter: tipo de operación, filtros, SQL propuesto y forma del resultado. Se valida la estructura; si es ambigua, se solicita precisión al usuario.
3. Valida el SQL contra la política y lo ejecuta con el rol de consulta.
4. Clasifica el resultado: coincidencias, ninguna coincidencia, tabla fuente vacía, campo/tabla no disponible o error de ejecución/conexión/proveedor. No transforma errores en respuestas vacías. Una tabla vacía solo se afirma cuando una consulta de existencia lo verifica; si no puede verificarse, se informa únicamente ausencia de coincidencias.
5. Responde con resultados verificados y una explicación en español. La tabla y los valores numéricos verificables se renderizan desde el backend. El texto narrativo del modelo es explicativo y se distingue de los datos comprobados; no se le permite generar series gráficas ni métricas sin soporte en resultados.
6. Guarda en el navegador la conversación, filtros y referencias de resultados autorizadas. Una pregunta de seguimiento conserva filtros y referente cuando no los cambia expresamente; si hay varios referentes posibles, pide aclaración.

Una respuesta incluye origen, filtros, estado, columnas, filas de la página, identificador de continuación cuando aplique, SQL validado consultable y datos de gráfico opcionales. El servidor conserva referencias de resultados verificadas vinculadas a sesión; no acepta filas aportadas por el cliente como evidencia. Ante contexto restaurado sin referencia válida, ejecuta una consulta autorizada nueva.

Los datos del respaldo y mensajes anteriores se tratan como contenido, nunca instrucciones para cambiar permisos. Una clave ausente, respuesta inválida, rechazo del proveedor o indisponibilidad producen mensajes claros sin datos inventados. No se cambia de modelo automáticamente. El transporte hacia OpenRouter puede requerir timeout y límites de tokens propios del proveedor; no se presentan como límites de las consultas PostgreSQL.

## Rastreo, dashboards y exportación

**Rastreo:** buscar código exacto en las familias de paquetes disponibles (`paquetes_certi`, `paquetes_contrato`, `paquetes_ems`, `paquetes_ems_formulario`, `paquetes_int`, `paquetes_ordi`) y relacionar eventos solo donde las claves verificadas lo permitan. Preservar diferencias entre servicios y evitar unir por IDs coincidentes de tablas distintas. Ordenar cronológicamente cuando haya fecha, identificar el servicio y mostrar solo movimientos del respaldo. Código duplicado o ambiguo exige mostrar candidatos para elegir. Nunca presentar el último estado histórico como estado en tiempo real.

**Dashboards:** conteos, comparaciones y distribuciones calculados en SQL; series temporales solo para tablas con campo temporal válido. Cada gráfico muestra métrica, filtros y origen. Cero filas, cero movimientos, fechas nulas y datos no compatibles tienen estados explícitos. La vista inicial no realiza conteos exhaustivos de todas las tablas.

**Copia y PDF:** copiar texto con confirmación accesible. PDF generado en el servidor para una respuesta identificada y verificada de la sesión actual, con fuentes que soporten español, tablas, filtros, origen y fecha de exportación. La descarga representa el resultado o página indicado expresamente, sin omitir filas silenciosamente. El historial antiguo requiere verificar de nuevo los datos antes de exportarlos como actuales.

## Interfaz

Escritorio: barra lateral para conversaciones y navegación; área central de chat; resultados con tablas paginadas, tarjetas y gráficos. Móvil: navegación plegable y tablas desplazables. Vistas de ingreso, chat, rastreo, catálogo y dashboards, con estados de carga, vacío, error y desconexión diferenciados.

Dirección visual propuesta: azul institucional y amarillo postal, tipografía legible, jerarquía sobria y contraste accesible. Se usa identidad textual Bolipost/Correos de Bolivia; no se inventa un logotipo oficial ni se afirma que una marca gráfica sea oficial sin recurso autorizado. Tema según sistema y preferencia persistente. Navegación por teclado, foco visible, etiquetas y respeto a movimiento reducido.

## Entrega, dependencias y configuración

Aplicación local en este checkout de Windows; no se publicará el respaldo ni se desplegará en un hosting externo. Dependencias principales propuestas: Django compatible con Python 3.12, psycopg, sqlglot, cliente HTTP, biblioteca PDF Unicode y Chart.js servido localmente. Las versiones exactas se fijan tras comprobar compatibilidad durante el plan.

Se entregan `.env.example` sin secretos, instrucciones Windows, comandos para administrar usuarios, inspeccionar/restaurar el respaldo y crear la política de consulta, pruebas y una guía de configuración. La clave OpenRouter y credenciales PostgreSQL se introducen localmente en configuración ignorada por Git. No se solicitan secretos en el chat ni se imprimen sus valores.

La demostración puede usar fixtures identificadas explícitamente como datos de prueba. El modo real exige credenciales válidas y una restauración verificada; no se mezclan datos ficticios con resultados reales.

## Verificación exigida

- Autenticación, CSRF, cierre de sesión y acceso denegado sin sesión.
- Separación entre cuentas e imposibilidad de reutilizar un resultado de otra sesión.
- Consultas legítimas con JOIN, CTE y agregados; rechazo de escritura, varias sentencias, CTE con escritura, SELECT INTO, funciones peligrosas y tablas/columnas prohibidas, incluso mediante alias y subconsultas.
- Prueba en PostgreSQL de privilegios efectivos y rechazo de escrituras, separada de las pruebas unitarias del parser.
- Privacidad antes de OpenRouter y también en gráficos, logs, exportaciones y mensajes de error.
- Seguimientos que conservan filtros y revalidación del historial aportado por el navegador.
- Rastreo por servicio, código inexistente/duplicado, tabla vacía y fallo de base distinguibles.
- Agregados y gráficos contrastados con SQL conocido; sin métricas deducidas de una muestra.
- Paginación con más de 50 filas y ausencia del antiguo límite de 10 segundos en la configuración del servidor de datos.
- PDF con acentos, columnas y filas legibles; copia, búsqueda y eliminación del historial; pruebas visuales de móvil/escritorio y ambos temas si el entorno permite navegador.
- Integración real con PostgreSQL y OpenRouter solo se declara verificada tras ejecutarla con credenciales disponibles. Las comprobaciones pendientes se entregan expresamente.

## Fuera de alcance y fallos inaceptables

Fuera de alcance: modificar datos postales, IA local, sincronización del historial entre dispositivos, implementar ahora la futura fuente API y datos postales en tiempo real ajenos al respaldo.

Fallos inaceptables: exponer secretos o columnas restringidas, ejecutar SQL de escritura, sobrescribir una base existente, mezclar historiales, presentar datos inventados como verificados o confundir un error con ausencia de datos.

## Referencias verificadas

- Modelo: https://openrouter.ai/openai/gpt-oss-20b
- PostgreSQL, configuración de transacciones: https://www.postgresql.org/docs/18/runtime-config-client.html

## Revisión del diseño

Un agente independiente revisó el documento para detectar decisiones importantes sin resolver antes de planificar. Resultado: `nothing important left`. El usuario aprobó después el diseño. Esta revisión del documento no verifica por sí sola código ni integración con servicios.
