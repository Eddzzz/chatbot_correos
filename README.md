# Asistente Bolipost

El chat explica los resultados en lenguaje natural con datos verificados. El
nivel de detalle depende de la pregunta y de la evidencia disponible. Al pedir
«amplía» o «explícame más», el asistente conserva el contexto de la consulta.
La skill **Consejos basados en evidencia** permite añadir recomendaciones cuando
se solicitan expresamente. Las tablas y referencias permiten revisar los resultados.

- [Inicio en Windows](#inicio-en-windows)
- [Demostración y conexión real](#demostración-y-conexión-real)
- [Producción en Windows](#producción-en-windows)
- [Gestor de proveedores, modelos y claves](#gestor-de-proveedores-modelos-y-claves)
- [Verificación](#verificación)

## Capacidades ampliadas · 17 de noviembre de 2026

El gestor incorpora **Exportar CSV**, **Exportar Excel** y **Rastreo por lotes**, con
permisos independientes comprobados en el servidor. CSV descarga todas las filas
verificadas del panel seleccionado; Excel incluye una hoja por panel del informe.
Ambos usan los resultados guardados, conservan el aislamiento por cuenta/sesión y
su caducidad, sin volver a consultar la base postal. Excel conserva códigos con
ceros iniciales como texto; CSV neutraliza texto que podría interpretarse como fórmula.
Excel rechaza resultados que exceden sus límites y permite recurrir a CSV.

**Rastreo de envíos** acepta hasta seis códigos separados por líneas, comas o punto
y coma, con filtro opcional de servicio. También puede escribir en el chat:
«Rastrea BO-DEMO-001, BO-DEMO-002». Cada código tiene su propio panel; los registros
ambiguos requieren precisar el servicio y los códigos sin coincidencias se indican
por separado. Los movimientos corresponden al respaldo histórico.

Las tres nuevas skills editables son **Demoras y tiempos de tránsito**,
**Cumplimiento de plazos de entrega** y **Comparación entre períodos**. Se integran
en el planificador y el analista existentes. Para clasificar cumplimiento se necesitan
un plazo, reglas de calendario y fechas de inicio/entrega verificables; si faltan,
el agente debe pedir aclaración. Las instrucciones no crean datos ni garantizan
que el respaldo contenga fechas o equivalencias suficientes para evaluar entregas.

Instalación existente: instalar `requirements.txt`, ejecutar `manage.py migrate --noinput`
y reiniciar Django. La migración 0011 añade las tres
skills sin sobrescribir instrucciones o estados personalizados.

Verificación aislada: `postal.tests.test_agent_capabilities`,
`scripts/browser_agent_capabilities_smoke.py` y `scripts/browser_system_skills_smoke.py`.

Aplicación Django en español para consultar un respaldo PostgreSQL de Correos de Bolivia. IA mediante **Groq, `openai/gpt-oss-120b`**, con **OpenRouter como respaldo al agotar cuotas**. 

## Administración del sistema y papelera

**Administrar** (`/system/?view=manage`) reúne los accesos en una cuadrícula bento:
personas y permisos, agentes/skills, infraestructura y conversaciones. El menú lateral
ofrece accesos directos en **Actividad**, **Asistente IA**, **Sistema** y **Mi cuenta**.
Las secciones son visibles sin desplegar submenús; se retiraron las pestañas duplicadas.

**Usuarios** (`/system/?view=users`) permite al superusuario crear y editar cuentas,
asignar rol de usuario o administrador, cambiar contraseñas y activar/desactivar accesos.
El directorio incluye búsqueda, filtros de estado/rol, número de chats y paginación.
Las contraseñas se validan y guardan con Django; dejarlas vacías al editar conserva la
actual. Desactivar conserva las conversaciones y cancela consultas en curso. La cuenta
propia debe permanecer activa y con rol de administrador. Repetir una desactivación no
vuelve a activar la cuenta. No se envían correos de invitación ni se eliminan usuarios.

La administración abre con **Resumen y analíticas** (`/system/`), una sola pantalla
con operación y consumo. El enlace anterior `/system/?view=analytics` abre esta misma
vista y conserva el período seleccionado. Incluye consumo
diario de tokens, generaciones registradas, usuarios con actividad, chats guardados/importados,
consumo por modelo/usuario/agente y filtros de **7, 30 y 90 días calendario de Bolivia**.
La tarjeta **Tokens disponibles** muestra la última cuota por minuto informada por Groq
en las respuestas del asistente para la clave y el modelo principales. Conserva el cero,
vence a los 60 segundos y se actualiza al recargar el panel después de una consulta.
No genera llamadas adicionales de IA ni estima un saldo diario a partir del consumo local;
los proveedores sin soporte muestran que no informan esta cuota.
Un valor ausente se distingue de cero; no se reconstruye consumo anterior a su registro.
La operación reciente muestra únicamente trabajos conservados de las últimas 24 horas;
las aclaraciones y cancelaciones quedan fuera de la tasa de éxito. Las conexiones indican
configuración, no disponibilidad de un proveedor que no se ha comprobado.

Cada área tiene su propia vista: modelos, red/DB, agentes, skills, conversaciones, estado
y auditoría. Guardar una sección conserva las opciones de las otras. La navegación se
pliega en móvil y ambos temas mantienen tablas, gráficos y controles accesibles.

El superusuario dispone de **Administración** en el menú del chat (`/system/`). Puede:

- Seleccionar Groq, NVIDIA, Cloudflare u OpenRouter y sus modelos; reemplazar o quitar
  claves sin mostrarlas en el navegador. Groq conserva sus respaldos y OpenRouter exige precios cero.
- Configurar tiempos de conexión y respuesta, origen demo/PostgreSQL y URL de lectura.
  El panel identifica la base de cuentas/chats y el host/base postal y permite comprobarlos.
- Activar el planificador y el analista, añadir indicaciones, definir tokens de salida,
  crear/editar/desactivar/eliminar skills de instrucciones y asignarlas a los agentes.
  Las skills no ejecutan scripts y mantienen los controles SQL y de evidencia.
- Activar chat, rastreo, estadísticas, catálogo y PDF para todos los usuarios.
- Consultar consumo informado por las APIs en los períodos de 7, 30 o 90 días, agrupado por usuario,
  proveedor, modelo y agente, incluidos intentos truncados. No se calculan saldos ni precios.
- Revisar conversaciones de todos los usuarios, enviarlas a papelera y restaurarlas;
  limpiar la caché Django y los resultados temporales vencidos; consultar la auditoría.

En **Administración → Permisos de tablas** se muestran las 122 tablas del catálogo, en pestañas separadas «Permitidas» y «No permitidas», con «Permitidas» seleccionada al entrar. La búsqueda se conserva entre pestañas; los campos autorizados y protegidos se despliegan como etiquetas que se ajustan al ancho disponible, también en móvil. Solo el superusuario puede permitir o bloquear tablas; los cambios son globales, se guardan y se auditan, y afectan a consultas nuevas sin reiniciar. El validador comprueba también joins, CTE y subconsultas. Los campos revisados de las tablas existentes se conservan; las tablas adicionales habilitan inicialmente identificadores numéricos y fechas, con una proyección revisada adicional para auditoría. Las tablas sin campos autorizados permanecen protegidas.

Cada tabla dispone de **Editar campos**: marcar un campo lo autoriza y desmarcarlo lo protege. Guardar campos, permitir tablas y bloquearlas requieren confirmación en una ventana emergente; cancelar conserva los permisos guardados. Las credenciales, tokens y contenidos de sesión tienen protección obligatoria. Si se desmarcan todos los campos, la tabla queda bloqueada; configurar campos de una tabla ya bloqueada no la habilita. Los cambios de campos se auditan y actualizan la proyección PostgreSQL de las tablas activas, sin modificar sus registros.

En producción, los permisos se guardan en la configuración local y se aplican a las consultas nuevas. El usuario lector debe tener acceso a las tablas y los campos habilitados. El catálogo cuenta 122 tablas físicas y muestra `user_roles` como fuente derivada.

La configuración guardada en el panel prevalece sobre `.env` y aplica a consultas nuevas
sin reiniciar. Se almacena mediante reemplazo atómico en `.runtime/system-settings.json`,
con permisos de archivo privados donde el sistema operativo los soporta. **Contiene secretos
en texto, igual que `.env`**: proteja el acceso a `.runtime` con permisos de Windows/servidor
y no publique ni comparta ese archivo. Nunca se precargan claves ni la URL con credenciales
en formularios. Las cuentas normales y el personal sin privilegio de superusuario no
pueden administrar el sistema. No se gestionan firewall, proxies ni claves del propio Codex.

El historial se guarda por cuenta en la base de la aplicación y se sincroniza entre sesiones
y dispositivos. Al abrir el chat se importa el historial IndexedDB de esa misma cuenta y
navegador; cada copia local se retira solo después de confirmar su importación al servidor.
Las importaciones nunca sobrescriben chats existentes ni restauran chats eliminados.
La importación solo puede recuperar el historial que todavía exista en cada navegador.
Cada guardado admite hasta 4 MiB y 2.000 mensajes; si no puede importarse, la copia local
permanece intacta y se muestra el error. Las revisiones impiden sobrescrituras desde otras pestañas.

Todos los usuarios tienen **Mi papelera** (`/trash/`), que conserva el chat durante **30 días
desde su eliminación**, con posibilidad de restaurarlo. Transcurrido el plazo se borran sus
mensajes y resultados asociados; queda solo un identificador por cuenta para impedir que un
navegador antiguo vuelva a importar el chat eliminado. Los resultados temporales y sus PDF
conservan su vigencia independiente de 24 horas, aunque se restaure el historial.

La purga funciona aproximadamente cada minuto mientras el servicio iniciado haya recibido
una petición autenticada. También se ejecuta al acceder al historial/papelera/administración
y si se ejecuta `manage.py cleanup_trash` durante el arranque local.
Para ejecutarla desde el Programador de tareas u otro servicio externo:

```powershell
.\.venv\Scripts\python.exe manage.py cleanup_trash
```

La instalación existente necesita `manage.py migrate --noinput` y reiniciar Django una vez
para cargar estos cambios de código. Las siguientes ediciones del panel no requieren reinicio.
`scripts/browser_system_management_smoke.py` comprueba administración, aislamiento,
guardados demorados, historial entre sesiones y papelera en una base temporal, sin llamadas
a IA real. Las migraciones de administración solo modifican la base local de la aplicación.

Incluye cuentas con contraseña, chat con contexto, rastreo histórico por servicio, catálogo de datos autorizados, cuatro dashboards, historial guardado por cuenta, copia y PDF, móvil y temas claro/oscuro.

El diseño se adaptó del frontend suministrado en `D:/edwin/Documents/correos/chatbot-correos/frontend/`: marca institucional, menú lateral azul, sobre animado, acceso, chat y modos claro/oscuro. Los recursos necesarios se sirven desde `static/postal/assets/`. La app conserva sus plantillas Django y su API; no requiere iniciar Vite ni instalar React. La carpeta original no se modifica.

## Asistente de IA y reportes desde el chat

El chat interpreta la petición con `Gemma 4 31B`, propone entre una y seis consultas según el análisis requerido, valida cada SQL y consulta la fuente de solo lectura. Después la IA selecciona y organiza hallazgos vinculados a celdas verificadas. El servidor comprueba comparaciones y extremos y redacta sus cifras sin permitir unidades o hechos aportados libremente por el modelo.

Puede pedir, por ejemplo:

- «Resume los envíos EMS por ciudad y estado».
- «Genera un reporte de envíos de octubre con totales y evolución mensual».
- «Crea un dashboard con cantidad de envíos, distribución por servicio y evolución temporal».
- «Compara los registros de La Paz y Cochabamba».

Las consultas del chat aplican cobertura departamental a las capitales: Trinidad incluye Beni, Sucre incluye Chuquisaca, Cobija incluye Pando y las otras seis capitales incluyen los municipios de sus departamentos. Los municipios que no son capitales conservan su alcance municipal. Esta regla se aplica a los filtros de ubicación de envíos y sucursales; conserva la distinción entre origen y destino. Los títulos deben identificar el alcance departamental. Los registros históricos no cambian: vuelva a ejecutar la consulta para aplicar la cobertura nueva.

El catálogo local `data/municipalities.json` deriva de la clasificación municipal del INE e incorpora San Pedro de Macha con referencia del Órgano Electoral. No necesita Internet durante las consultas. Incluye variantes con y sin acentos y ubicaciones compuestas con guion, como `RURRENABAQUE-BENI`. Los nombres compartidos por varios departamentos o las ubicaciones incompletas pueden requerir aclaración; el texto postal no siempre permite identificar un municipio de forma unívoca.

Los dashboards creados desde el chat son dinámicos; las cuatro métricas de la pestaña Estadísticas siguen disponibles como acceso directo. Cada reporte puede incluir indicadores, varias tablas, gráficos y hallazgos con fuentes. Los paneles se paginan de manera independiente, se guardan juntos en el historial y se copian/exportan juntos o individualmente. El PDF identifica las páginas incluidas; no oculta que hay más filas.

La IA recibe únicamente las columnas autorizadas por Administración; las credenciales mantienen protección obligatoria. No se generan causas, unidades nuevas ni máximos globales a partir de una muestra. Los extremos incluyen también los grupos sin departamento. Si los hallazgos de la IA no superan la validación, se solicita una corrección una sola vez; si vuelve a fallar, el servidor redacta una explicación con celdas verificadas e identifica ese origen. Los errores del proveedor conservan su aviso y las tablas disponibles.

Las fechas de movimientos proceden del historial del servicio (`eventos_ems`, `eventos_certi`, `eventos_contrato` o `eventos_ordi`), no de la creación de las definiciones de `eventos`. El servidor corrige las referencias inequívocas antes de ejecutar el SQL y rechaza las ambiguas. Las verificaciones de cifras propuestas, significados no documentados y referencias a «ayer» se explicitan cuando la evidencia permite resolverlas; una lista vacía no identifica un primer paquete ni confirma una entrega.

En reportes de la primera semana por departamentos, las continuaciones que cambian solo servicio o mes reutilizan el reporte verificado y conservan los movimientos sin paquete asociado. El contexto mantiene sus filtros y resultados; las consultas internas del servidor que no cumplen las reglas del planificador se omiten como ejemplos SQL para el modelo.

Las preguntas sobre el significado de un tipo ya consultado (por ejemplo, «¿qué es PG?») conservan el valor verificado. Si el catálogo no documenta una equivalencia, el chat indica esa limitación sin inventar el nombre ni pedir al usuario que defina la misma sigla.

Las preguntas conceptuales sobre EMS, tránsito y autenticación, la extracción de horarios de avisos aportados y los ejemplos didácticos con filas inventadas tienen respuestas sin consultas de negocio. El contenido de un aviso no cambia las instrucciones del asistente. Los ejemplos SQL se muestran sin ejecutarlos. Un conteo presentado como «entregados» debe filtrar el estado ENTREGADO mediante su relación con el envío; tener cualquier estado asignado no basta. Los porcentajes se calculan con desgloses completos o con conteos verificados del mismo alcance. Una continuación puede recuperar un desglose previo del chat, conservando los controles de usuario, sesión, período y ubicación; una proporción por sí sola no determina el tiempo de entrega.

### Contexto compacto enviado a las APIs

El planificador recibe JSON compacto, un único ejemplar del SQL principal y los filtros que no estén ya representados por ese SQL. Los cambios independientes de año, mes o servicio omiten la muestra anterior. Las preguntas que pueden referirse a filas («el primero», «ese paquete», «todos sus datos») conservan hasta 20 filas verificadas, su orden y la indicación de muestra parcial. El catálogo autorizado y las reglas de seguridad se mantienen completos.

El servidor guarda una memoria por trabajo, también cuando pide una aclaración: petición base, últimas correcciones explícitas, restricciones no reconocidas y aclaración pendiente. La API recibe esa memoria y hasta tres turnos recientes. Las restricciones desconocidas se conservan textualmente; no se resumen con otra llamada de IA. Tras una consulta ejecutada, su SQL y filtros son la referencia del alcance resuelto. Las conversaciones anteriores sin memoria persistida se reconstruyen desde el historial autorizado disponible.

Las referencias a resultados se conservan en el servidor. Una continuación que solo identifica la última aclaración puede recuperar el resultado verificado asociado. Para peticiones sobre el resultado inicial/original se recupera también el primer resultado del chat; todos los accesos mantienen las comprobaciones de usuario, sesión y vencimiento. Los resultados completos siguen en disco y disponibles en sus tablas; comprimir el contexto no reduce las filas consultadas.

El analista recibe muestras parciales de hasta 20 filas por panel con un presupuesto de 24.000 caracteres para la evidencia JSON, frente a los 80.000 anteriores. Los resultados completos disponibles en la primera página (hasta 100 filas) se conservan mientras quepan. Primero se reducen muestras parciales grandes. Se mantienen los índices de panel/fila, las cifras y las marcas de completitud. Si ni una fila por panel cabe, se conservan las tablas y se informa que la explicación de IA no está disponible. Este presupuesto mide caracteres, no tokens.

El registro `postal.ai` muestra proveedor, intento, tamaño de entrada en caracteres y los contadores `prompt_tokens`, `completion_tokens` y `total_tokens` cuando el proveedor los informa, distinguiendo planificación y análisis. No registra preguntas, SQL, filas, claves ni cuerpos del proveedor. Los contadores incluyen intentos truncados si el proveedor devuelve su consumo. El ahorro real depende de la conversación y se evalúa con estos contadores, junto con los reintentos y la corrección de las respuestas.

La migración `0003_queryjob_context_state` añade la memoria a la base local de cuentas. Para una instancia ya instalada ejecute `.\.venv\Scripts\python.exe manage.py migrate --noinput` y reinicie Django.

### Configuración guiada local

Cree una clave en [Groq API Keys](https://console.groq.com/keys). Desde PowerShell, en la carpeta del proyecto:

```powershell
.\.venv\Scripts\python.exe manage.py configure_services
```

El comando pide la clave Groq y la contraseña de PostgreSQL con entrada oculta. Verifica la conexión PostgreSQL antes de guardar; conserva el resto de `.env`, codifica caracteres especiales y prepara una contraseña nueva para el rol lector. No imprime claves, no restaura ni modifica bases y mantiene `DATA_MODE=demo` hasta completar la restauración. Si la clave ya está en `.env`, Enter la conserva.

Después de configurarlo, reinicie Django para probar la IA en demostración. El comando muestra las rutas y órdenes concretas para restaurar el respaldo y crear el rol lector; tras completarlas cambie `DATA_MODE=postgres` y reinicie. La generación de reportes con el proveedor real y la consulta del respaldo completo requieren estas credenciales; no se consideran verificadas por las pruebas simuladas.

## Inicio en Windows

Requiere Python 3.12 o posterior compatible con Django 5.2. PostgreSQL 18 y sus herramientas son necesarios para restaurar el respaldo real; el modo de demostración no los necesita.

Desde PowerShell, en esta carpeta:

```powershell
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
}
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}
.\.venv\Scripts\python.exe manage.py migrate --noinput
.\.venv\Scripts\python.exe manage.py cleanup_trash
.\.venv\Scripts\python.exe manage.py setup_local
```

### Iniciar o reiniciar la app

Si la aplicación ya está instalada, abra PowerShell en la raíz del proyecto y ejecute:

```powershell
$env:DJANGO_HTTPS = 'false'
.\.venv\Scripts\python.exe manage.py serve_postal --local-http
```

Abra `http://127.0.0.1:8000`. La cuenta inicial y una contraseña aleatoria quedan en `.runtime/local-access.txt`, ignorado por Git. `setup_local` conserva las contraseñas existentes. Use `manage.py changepassword` para cambiar la contraseña inicial y elimine el archivo de acceso cuando ya no lo necesite. Administre las cuentas desde **Administración → Usuarios**.

Para usar otro puerto, añada `--port 8001` a `serve_postal --local-http` y abra `http://127.0.0.1:8001`.

Para reiniciar, pulse `Ctrl+C` en la terminal donde corre el servidor y ejecute de nuevo el bloque de arranque. Si lo inició con el servidor de desarrollo de Django, también puede reiniciarlo con estos comandos:

```powershell
$env:DJANGO_HTTPS = 'false'
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --noreload --insecure
```

Defina `DJANGO_HTTPS` en la misma terminal antes de arrancar. Si la app redirige a `https://127.0.0.1:8000`, detenga el servidor y vuelva a ejecutar el bloque completo.

Desde otra terminal, compruebe que la pantalla de inicio de sesión devuelve HTTP 200:

```powershell
curl.exe --fail --silent --show-error --location --max-time 10 --output NUL --write-out 'HTTP %{http_code} %{url_effective}\n' http://127.0.0.1:8000/
```

## Producción en Windows

La instalación usa un proceso Waitress en loopback y Caddy como proxy HTTPS en el mismo equipo. Esta topología conserva la base SQLite, los resultados en disco y los trabajos en memoria. Instale Caddy y asegúrese de que `caddy.exe` esté en `PATH`. Configure DNS para el dominio de la aplicación y permita la entrada a Caddy por 80 y 443. Mantenga el puerto de Waitress en loopback. [Instalación de Caddy](https://caddyserver.com/docs/install)

1. Restrinja los permisos de `.env`, `.runtime/` y sus copias de seguridad a las cuentas que los necesitan. Genere una clave con `python -c "import secrets; print(secrets.token_urlsafe(64))"`, guárdela como `DJANGO_SECRET_KEY` en `.env` y consérvela entre reinicios. Si rota la clave, configure `DJANGO_SECRET_KEY_FALLBACK` con la clave anterior para seguir verificando las firmas del historial. Con una clave nueva, repita las consultas cuyos resultados temporales estén vinculados a la sesión anterior.
2. Para usar PostgreSQL, configure `DATA_MODE=postgres` y `BUSINESS_DATABASE_URL` con la cuenta de solo lectura. En un respaldo preparado con `prepare_business`, habilite `BUSINESS_USE_ISOLATED_VIEWS=1` para usar las vistas `assistant`. En una base cuyo lector tiene acceso directo a las columnas autorizadas de `public`, use `BUSINESS_USE_ISOLATED_VIEWS=0`. Revise la configuración efectiva en Administración, ya que las preferencias guardadas prevalecen sobre `.env`. El límite inicial por sentencia es de 15 segundos y se puede ajustar en **Red y base de datos**. El comando `migrate` aplica a SQLite, la base de cuentas de Django.
3. Antes de actualizar una instalación, detenga Waitress y guarde una copia protegida de `accounts.sqlite3` (incluidos sus archivos auxiliares si existen), `system-settings.json`, `.env`, la clave vigente y `.runtime/results` si debe conservar exportaciones vigentes. Use una versión del código y una copia del estado tomadas en el mismo punto para revertir una actualización.
4. Ejecute desde la raíz del proyecto. Defina `BOLIPOST_HOST` también en el entorno del proceso Caddy, que lee las variables del proceso.

```powershell
$env:DJANGO_HTTPS = 'true'
$env:BOLIPOST_HOST = 'bolipost.example.org'
$env:DJANGO_ALLOWED_HOSTS = $env:BOLIPOST_HOST
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate --noinput
.\.venv\Scripts\python.exe manage.py collectstatic --noinput
.\.venv\Scripts\python.exe manage.py check --deploy
.\.venv\Scripts\python.exe manage.py serve_postal --check-only
caddy validate --config config/Caddyfile
# Terminal de la aplicación
.\.venv\Scripts\python.exe manage.py serve_postal
# Terminal del proxy con BOLIPOST_HOST definido
caddy run --config config/Caddyfile
```

En una base nueva, cree el primer administrador con `manage.py createsuperuser` tras migrar. Inicie ambos procesos con la raíz del proyecto como directorio de trabajo y configure su reinicio automático y rotación de logs en el servidor. Si cambia el puerto de Waitress, pase `--port` y defina el mismo valor en `BOLIPOST_PORT` para Caddy. Programe `cleanup_trash`, `cleanup_results` y `clearsessions` con la cuenta de la aplicación.

En modo PostgreSQL, el arranque y `serve_postal --check-only` ejecutan una consulta de solo lectura sobre la primera fuente autorizada. Si todas las fuentes están deshabilitadas, comprueban la conexión con `SELECT 1`. Antes de abrir el acceso, compruebe que HTTP redirige a HTTPS y que `/accounts/login/` y `/static/postal/app.js` devuelven 200 por HTTPS. Inicie sesión, ejecute una consulta de chat y descargue una exportación. `check --deploy` puede mostrar `W005` y `W021` porque HSTS se aplica al dominio de la aplicación y la activación para subdominios o preload requiere revisar toda la zona DNS.

Caddy termina HTTPS y elimina la cabecera `Server`. Django emite cookies `Secure` en ese modo y Waitress acepta la IP y el protocolo de Caddy en loopback. El acceso concede hasta cinco intentos consecutivos por combinación de cuenta e IP en 15 minutos. Un inicio de sesión válido reinicia el contador. Las cuotas por cuenta son de 3 consultas de chat, 30 de rastreo y 20 de estadísticas por minuto, con hasta 2 trabajos simultáneos por herramienta. Las respuestas 429 incluyen `Retry-After`.

El historial muestra las respuestas verificadas por el servidor. La importación de preguntas devuelve 201 al crear el historial y 200 cuando la misma copia ya existe. Ante un conflicto o una eliminación definitiva, el navegador conserva la copia local y muestra el error. Antes de pasar de HTTP a HTTPS, abra la aplicación en su origen HTTP anterior para completar la importación hacia la misma base de cuentas. El navegador guarda IndexedDB por origen.

## Demostración y conexión real

En PostgreSQL de producción, la aplicación resuelve `user_roles` durante la consulta, a partir de `public.users` y `public.model_has_roles`. La cuenta lectora necesita acceso a `users.id`, `users.role_id`, `model_has_roles.model_id`, `model_has_roles.model_type` y `model_has_roles.role_id` para esa fuente. Su uso no requiere crear vistas, aplicar migraciones ni restaurar un respaldo.

Las restauraciones locales preparadas con `prepare_business` pueden conservar sus vistas con `BUSINESS_USE_ISOLATED_VIEWS=1`. En una restauración local antigua se puede ejecutar `manage.py prepare_user_roles` para añadir esa vista.

`DATA_MODE=demo` utiliza fixtures ficticias identificadas en pantalla y en cada PDF. Hay 80 registros EMS y registros de las otras familias; no representan envíos reales. Pruebe:

- Rastreo `BO-DEMO-002`: un servicio.
- Rastreo `BO-DEMO-001`: varios servicios; elija EMS para ver sus movimientos.
- Estadísticas de envíos por servicio, identificador de estado, evolución mensual y sucursales por departamento.
- Chat `Describe los campos de users`: metadatos del respaldo, sin clave IA.

Para las consultas de chat que requieren IA, configure una clave del proveedor activo también en modo de demostración. El rastreo, las estadísticas predefinidas y la consulta del catálogo funcionan sin clave de IA.

Para configurar Groq desde `.env`, use la plantilla `.env.example` como referencia y guarde las claves solo en su archivo local.

```dotenv
DATA_MODE=demo
AI_PROVIDER=groq
GROQ_API_KEY=su_clave_local
GROQ_BACKUP_API_KEY=
OPENROUTER_API_KEY=
```

Reinicie Django después de editar `.env`. Con la configuración inicial de Groq, cada generación empieza con `GROQ_API_KEY` y el modelo `openai/gpt-oss-120b`. Ante un límite de cuota (429 o `rate_limit_exceeded`) o saldo insuficiente (402 o `blocked_api_access`), prueba `GROQ_BACKUP_API_KEY` con el mismo modelo y después `OPENROUTER_API_KEY` con `nvidia/nemotron-3.5-super-vl:free`. Las claves de respaldo son opcionales y se omiten cuando están vacías. Los errores de autenticación, conexión y respuestas inválidas detienen la solicitud.

OpenRouter exige precios cero de entrada y salida. Cada generación nueva vuelve a intentar la clave principal. Si se agotan todos los respaldos configurados, se muestra el error del último intento. Una pregunta puede requerir varias generaciones.

Cuando ya hay una conexión activa en **Administración → Modelos y API**, cambie las claves y el orden de respaldo desde ese panel. El catálogo importa las variables una sola vez y luego usa las credenciales guardadas allí.

Las claves permanecen en el backend. El proveedor recibe la pregunta, nombres de vistas/columnas permitidas y contexto verificado acotado; no recibe contraseñas ni columnas restringidas. El endpoint gratuito de NVIDIA registra solicitudes e indica no enviar datos personales ni información confidencial: úselo con demostraciones o información autorizada para ese servicio. Consulte las [condiciones del modelo](https://openrouter.ai/nvidia/nemotron-3.5-super-vl:free) y los [límites de OpenRouter](https://openrouter.ai/docs/api_reference/limits).

El planificador incluye tipos de columnas y relaciones declaradas entre campos autorizados. Valida el JSON y el SQL antes de ejecutar. Si el plan es inválido, pide una corrección una sola vez. Para errores 429, 502, 503 y 504, el transporte vuelve a intentar la misma conexión una vez si la espera indicada es de hasta dos segundos. Con las dos claves Groq y el respaldo OpenRouter, la cadena inicial puede hacer hasta seis solicitudes HTTP por generación. Una generación truncada puede repetirse una vez con mayor presupuesto. Los errores de clave, saldo, permisos y tiempo de espera tienen mensajes propios y no exponen el cuerpo del proveedor.

El modelo interpreta primero los conteos y comparaciones geográficas. Para comparar dos o tres departamentos por servicio propone un agregado SQL y `comparison` con la columna geográfica y las ubicaciones. El servidor valida y ejecuta el mismo agregado para cada departamento, conserva fechas y otros filtros, e incluye los ceros. El contexto conserva la consulta base y las ubicaciones para continuaciones. Por defecto se cuenta destino: ciudad en EMS/ORDI, cuidad en CERTI y destino en CONTRATO/INT; origen solo se usa cuando se solicita. Ante falta de clave o cuota, los conteos simples como «cuántos paquetes tengo en Tarija» y sus continuaciones «compara la carga con Oruro» tienen un respaldo local de solo lectura. Las peticiones con fechas, estados u otras restricciones conservan el planificador y su contexto. Estos conteos describen registros del respaldo, no la ubicación física actual de los paquetes.

`python scripts/audit_department_comparisons.py` prueba el modelo real, ejecuta sus planes en PostgreSQL y contrasta cada agregado con consultas independientes. Consume cuota real y guarda preguntas, respuestas del modelo, tráfico sin claves y resultados en `output/model-department-comparisons-*`. Puede reanudarse pasando la carpeta de evidencia como argumento; los casos bloqueados por cuota no cuentan como aprobados.

En Windows, si `PG_BIN` contiene `libpq.dll`, Django registra ese directorio para que psycopg pueda usar la biblioteca instalada cuando Windows bloquee las DLL del paquete Python. No modifica la política de seguridad del equipo.

## Restaurar el respaldo real

El archivo `D:\edwin\Documents\correos\backapsiop\backapsiop.sql` es un archivo **custom PGDMP**, pese a su extensión. Se restaura con `pg_restore`, no se ejecuta como SQL de texto.

En este equipo el respaldo completo está restaurado en `bolipost_consulta` y la aplicación usa el rol `bolipost_reader`. El dashboard y su PDF se verificaron originalmente con PostgreSQL y OpenRouter; la conexión actual usa Groq. Los pasos siguientes sirven para repetir la instalación en otra base nueva. La restauración requiere espacio para datos descomprimidos e índices.

Configure en `.env` una URL administrativa válida y una contraseña nueva para el rol lector:

```dotenv
BUSINESS_ADMIN_DATABASE_URL=postgresql://ADMIN:CLAVE_CODIFICADA@127.0.0.1:5432/postgres
BUSINESS_READONLY_PASSWORD=UNA_CLAVE_NUEVA_DE_AL_MENOS_16_CARACTERES
```

Codifique caracteres especiales de contraseñas para usarlos en una URL. No pase secretos como argumentos de consola. El administrador necesita permiso para crear la base y el rol y restaurar el esquema. Las herramientas instaladas en este equipo están en `D:\Program Files\PostgreSQL\bin`.

```powershell
.\.venv\Scripts\python.exe manage.py restore_backup "D:\edwin\Documents\correos\backapsiop\backapsiop.sql" --database bolipost_consulta --pg-restore "D:\Program Files\PostgreSQL\bin\pg_restore.exe"
.\.venv\Scripts\python.exe manage.py prepare_business --database bolipost_consulta --role bolipost_reader
```

`restore_backup` rechaza una base existente, incluso si se trata de una restauración previa. Si falla, conserva la base nueva para inspección y no la habilita para consulta. `prepare_business` exige la marca de restauración aislada y un rol nuevo: no cambia un rol utilizado por otras aplicaciones. Las revocaciones de PUBLIC se realizan únicamente en esta base aislada. No cambia el servicio PostgreSQL ni el respaldo original.

Después configure:

```dotenv
DATA_MODE=postgres
BUSINESS_DATABASE_URL=postgresql://bolipost_reader:CLAVE_LECTOR_CODIFICADA@127.0.0.1:5432/bolipost_consulta
BUSINESS_USE_ISOLATED_VIEWS=1
```

Reinicie y compruebe rastreo/estadísticas. La aplicación nunca utiliza la URL administrativa para consultas web. Nunca ejecute migraciones Django sobre la base postal: las cuentas y sesiones viven en `.runtime/accounts.sqlite3`.

## Datos y seguridad

- Catálogo estructural completo, sin defaults ni valores sensibles. Los campos restringidos pueden verse como metadatos.
- Política explícita en `postal/policy.py`: 16 tablas y la fuente derivada `user_roles` tienen columnas autorizadas por defecto. El superusuario puede habilitar otras tablas y campos.
- Transacciones `READ ONLY` y `search_path=pg_catalog`. Producción consulta proyecciones de las tablas existentes de `public`. La restauración local con vistas usa un rol limitado a `assistant.*`.
- Parser PostgreSQL con validación de todas las fuentes, columnas, aliases, CTE y funciones. Rechaza varias sentencias, escrituras, SELECT INTO, bloqueos, catálogos y funciones ajenas a la lista autorizada.
- Los planes IA también rechazan valores inventados en las proyecciones. El modelo no aporta filas ni cifras de gráficos. Los gráficos IA solo se generan a partir de agregados directos admitidos; los demás resultados se muestran como tablas.
- La validación prueba procedencia y seguridad, no que la interpretación del modelo sea infalible. Consulte el SQL y los filtros ejecutados para revisar la pregunta de negocio.
- Sin máximo global de filas ni límite de 10 segundos para consultas PostgreSQL. Se leen lotes y se almacenan resultados en disco, con páginas de 100 filas. Una petición expresa de “primeros N” puede producir un LIMIT solicitado por el usuario.
- El timeout de conexión PostgreSQL y los plazos HTTP de Groq son independientes de la duración SQL. No se elimina la protección de conexión ni las restricciones del proveedor.
- Cancelación PostgreSQL real. El sondeo de una consulta activa renueva su presencia; tras dos minutos sin sondeo se cancela como abandonada. Esto no limita la duración de una consulta que el usuario sigue esperando.
- Todas las APIs exigen sesión y las operaciones POST exigen CSRF. Resultados, exportaciones y cancelación pertenecen a la cuenta **y** sesión originales. Cambiar de cuenta en otra pestaña invalida la página antigua.
- Las solicitudes JSON rechazan claves duplicadas, valores no finitos, Unicode inválido y estructuras excesivamente anidadas. Un cuerpo superior a 64 KB devuelve un error JSON 413; un contexto explícito debe ser un UUID válido de esta sesión. El navegador comprueba identificadores, estados y estructura de filas antes de mostrar o sondear resultados.

Las órdenes explícitas de escritura y las fechas imposibles se rechazan antes de consultar al modelo o resolver reportes locales. Una pregunta ambigua conserva su aclaración; no se fuerza a convertirse en un listado por tener contexto previo. Las comparaciones de cifras incluyen totales de grupos únicamente cuando el resultado está completo y el COUNT es aditivo, sin DISTINCT, HAVING ni límites.

Un HTTP 413 de Groq con código exacto `rate_limit_exceeded` activa el respaldo por cuota. Los demás HTTP 413 del proveedor indican que la solicitud de IA es demasiado grande; son distintos del límite de 64 KB de la API local. La expansión de municipios se compacta en el contexto solo si el normalizador puede reproducir exactamente el predicado ejecutado, conservando sus otros filtros y fechas.

## Contexto, historial y exportaciones

El seguimiento conserva SQL/filtros previos y una vista previa obtenida del servidor, no filas recibidas del navegador. La vista previa de contexto contiene hasta 20 filas y se identifica como parcial cuando corresponde. Si el referente es ambiguo o ha vencido, se debe consultar de nuevo; no se reinterpreta un seguimiento sin sus filtros silenciosamente.

El historial se guarda exclusivamente en IndexedDB, separado por ID de cuenta. Incluye mensajes y la página visible, permite búsqueda y eliminación y no se sincroniza entre dispositivos. El almacenamiento del navegador no está cifrado: quien controle ese perfil del dispositivo puede inspeccionarlo. Cerrar sesión limpia la memoria y la pantalla, conservando el historial para la misma cuenta.

Cada conversación tiene un UUID visible y una URL propia `/c/<uuid>`. Al abrirla o recargarla, se restaura desde el historial de esa cuenta y navegador; también funciona la navegación Atrás/Adelante. Los chats anteriores conservan sus identificadores. Una URL sin historial local disponible muestra un aviso y vuelve al inicio.

Un historial restaurado se etiqueta y no se trata como evidencia del servidor. Para exportarlo como una consulta actual, reejecute la consulta. Un PDF representa la **página indicada**, con su número, total verificado, origen, filtros y fecha; no pretende incluir todas las páginas. Las tablas anchas se distribuyen en grupos de columnas para mantener legibilidad.

Los movimientos se muestran por código dentro de su familia de servicio. Cuando no existe FK entre paquete y evento se indica la asociación por código y su límite. Un código con varios registros exige precisar el servicio; no se mezclan movimientos ni se afirma estado en tiempo real.

Los resultados temporales se conservan 24 horas después de finalizar. La creación de consultas elimina resultados vencidos periódicamente; también puede ejecutar:

```powershell
.\.venv\Scripts\python.exe manage.py cleanup_results
.\.venv\Scripts\python.exe manage.py clearsessions
```

La limpieza de resultados no elimina el historial IndexedDB. El `.gitignore` excluye `.env` y sus variantes locales, `.runtime/`, las bases SQLite, los respaldos `.sql` y `.dump`, y los archivos generados en `output/`, `tmp/` y `.taste-skill/`. Versione `.env.example` como plantilla sin credenciales. Los resultados temporales pueden contener información postal autorizada.

## Verificación

```powershell
.\.venv\Scripts\python.exe manage.py check
$env:DJANGO_HTTPS = 'false'
.\.venv\Scripts\python.exe manage.py test
node --check static/postal/app.js
```

Las pruebas de integración PostgreSQL son explícitas y no pueden usar el puerto 5432 del servicio existente. Requieren una base aislada marcada por el flujo de restauración y el esquema real:

```powershell
$env:POSTAL_INTEGRATION_URL='postgresql://postgres@127.0.0.1:55439/bolipost_integration'
.\.venv\Scripts\python.exe manage.py test postal.tests.test_data
Remove-Item Env:POSTAL_INTEGRATION_URL
```

El clúster utilizado durante el desarrollo está detenido. Las pruebas verifican permisos efectivos, rechazo de escritura incluso fuera del parser, más de 50 filas, parámetros, agregados, cancelación durante bloqueo y protección contra sustitución de funciones.

El smoke de navegador `scripts/browser_smoke.py` utiliza Playwright y Edge locales como herramientas de desarrollo opcionales, no dependencias de ejecución de la aplicación. Comprueba el menú actual del chat, autenticación, historial, temas, copia, PDF y cambio de cuenta. Detecta el modo del servidor sin exigir demostración; prepara un informe demo aislado con IA simulada y utiliza sus endpoints reales de resultados y PDF. Sus capturas quedan bajo `.runtime/qa/`.

El formulario de consulta se habilita después de cargar JavaScript y restaurar el historial local. `scripts/browser_startup_smoke.py` retrasa ambos deliberadamente durante cinco arranques y comprueba que la primera consulta no navegue como un formulario normal, no pierda texto ni se envíe dos veces.

Las pruebas unitarias de la API desactivan la clave real; las de Groq simulan el transporte HTTP. Para comprobar respuestas API malformadas en la interfaz, con Django iniciado y la cuenta local preparada:

```powershell
.\.venv\Scripts\python.exe scripts/browser_validation_smoke.py --base-url http://127.0.0.1:8000
```

Esta comprobación usa el navegador real y respuestas HTTP simuladas; no envía consultas a Groq ni crea trabajos. El smoke de informes `scripts/browser_report_smoke.py` verifica gráficos, páginas, historial y PDF con datos demo y proveedor simulado.

## Estructura y futura API

- `config/`: configuración Django y URLs.
- `postal/data.py`, `policy.py`: frontera de acceso y privacidad; sustituir esta fuente al integrar la futura API.
- `postal/ai.py`, `postal/provider_catalog.py`: conexión con los proveedores de IA, validación del plan y gestión de modelos y claves.
- `postal/jobs.py`, `models.py`, `views.py`: trabajos, páginas de evidencia y aislamiento de sesión.
- `postal/operations.py`, `pdf.py`: rastreo, agregados y exportación.
- `templates/`, `static/`: interfaz sin compilación; Chart.js y tipografía locales con licencias.
- `data/catalog.json`: metadatos extraídos del respaldo, nunca filas de negocio.
- `docs/superpowers/`: diseño aprobado, plan y registro de verificación.

Referencias: [Django: autenticación](https://docs.djangoproject.com/en/5.2/topics/auth/default/), [modelo Groq](https://console.groq.com/docs/model/openai/gpt-oss-120b), [formato de salida Groq](https://console.groq.com/docs/structured-outputs), [PostgreSQL: transacciones y configuración](https://www.postgresql.org/docs/18/runtime-config-client.html).


### Cloudflare Workers AI

Para usar Cloudflare, configure en `.env` `AI_PROVIDER=cloudflare`, `CLOUDFLARE_ACCOUNT_ID` y `CLOUDFLARE_API_TOKEN`. El modelo predeterminado es `@cf/meta/llama-3.1-8b-instruct-fp8-fast`; puede cambiarse con `CLOUDFLARE_MODEL`. Reinicie el servidor tras editar `.env`. El token solo se utiliza en el servidor. El transporte conserva la validación JSON, SQL de lectura y evidencia de resultados. Para volver a Groq use `AI_PROVIDER=groq` y su `GROQ_API_KEY`.


### NVIDIA API Catalog

Configure `AI_PROVIDER=nvidia`, `NVIDIA_API_KEY` y `NVIDIA_MODEL` con el identificador de un modelo habilitado en su cuenta en `.env` y reinicie el servidor. Se usa el endpoint compatible Chat Completions de NVIDIA con JSON y las mismas validaciones de lectura y evidencia. La clave nunca se envía al navegador. Si el catálogo lista el modelo pero la generación devuelve 404 `Specified function ... is not found`, la aplicación informa `provider_access`: revise el acceso al endpoint y la verificación de la cuenta en NVIDIA. Que una clave pueda listar modelos no garantiza que pueda ejecutarlos.



## Estadísticas, consejos e informes del chatbot

En **Skills** hay cuatro instrucciones adicionales editables y desactivables:
estadísticas ampliadas, explicaciones breves y ampliables, consejos basados en
evidencia y reportero estadístico. Se aplican a las consultas nuevas.
Puedes pedir «Más estadísticas de peso y precio de EMS en junio de 2026»,
«Amplía la explicación con los mismos filtros» o «Prepara un informe estadístico».
Las medidas se calculan sobre el conjunto filtrado, con las funciones autorizadas.
Los consejos citan resultados y proponen revisarlos y comparar períodos equivalentes.

La exportación PDF incluye el resumen verificado, los consejos de la respuesta y
las tablas de las páginas seleccionadas. La ampliación del texto depende del
modelo configurado; las referencias y los datos siguen validándose en el servidor.
La migración `0012_statistics_advice_reporter` registra las nuevas skills sin
sobrescribir sus personalizaciones en ejecuciones posteriores. La migración
`0013_chat_response_skills` amplía las instrucciones originales de las dos skills
de respuestas y conserva instrucciones personalizadas y estados de activación.

## Gestor de proveedores, modelos y claves

En **Modelos y API** puede agregar cualquier proveedor que ofrezca un endpoint de Chat Completions compatible con OpenAI. Use **Agregar proveedor** e indique el nombre, la URL completa y, si ya la tiene, la clave API. El dominio oficial de OpenRouter activa automáticamente la política de modelos gratuitos. Use HTTPS para endpoints externos. HTTP solo se admite en localhost.

Primero seleccione una tarjeta de proveedor. Solo entonces aparecen sus modelos, claves y acciones; seleccionar una tarjeta no cambia la conexión activa. Puede cambiar de proveedor con las tarjetas superiores, sin paneles plegables.

Dentro de cada proveedor:

- **Agregar modelo** guarda un nombre visible y el identificador exacto que acepta su API. Puede registrar varios modelos.
- **Agregar clave** guarda una credencial con nombre, orden y estado. Se usa primero la clave habilitada con menor orden; ante límites o falta de saldo se intenta la siguiente. Los errores de autenticación detienen el intento para que se corrija la clave.
- **Usar modelo** establece la conexión de las próximas consultas. Requiere proveedor y modelo habilitados y al menos una clave habilitada.
- **Editar** permite cambiar datos o habilitar/deshabilitar un elemento. En una clave, un campo vacío conserva la existente y un valor nuevo la reemplaza; nunca se muestra la clave guardada.
- **Eliminar** retira el elemento. Para quitar el modelo activo, su proveedor o su última clave habilitada, seleccione primero otra conexión o agregue otra clave.

Al inicializarse, el catálogo importa los proveedores, modelos y claves de la configuración previa. Si la conexión activa es Groq, importa las dos claves configuradas en su orden y habilita el modelo de OpenRouter como respaldo. Una vez que el catálogo tiene un modelo activo, las consultas nuevas usan su configuración guardada. Los trabajos en curso conservan la configuración con la que empezaron.

La migración `0007_provider_catalog` añade las tablas a la base local de cuentas, sin modificar la base postal de negocio. La administración exige una cuenta de administrador del sistema y registra acciones por identificador, sin credenciales en la auditoría.

### Prioridad automática de modelos

La lista **Orden de uso de los modelos** muestra el principal y los respaldos habilitados, incluso entre proveedores diferentes. En **Editar orden** marque **Incluir como respaldo automático** y asigne una prioridad (menor número primero). Solo participan modelos, proveedores y claves habilitados. El principal siempre va primero; al agotar sus claves por cuota o saldo se prueba el siguiente modelo. Cada generación nueva vuelve a intentar el principal. Los fallos de autenticación y las respuestas inválidas no provocan cambio de modelo.

El botón **Agregar respaldo**, junto al orden de modelos, permite añadir directamente cualquier modelo habilitado con una clave configurada y definir su prioridad. Puede sumar varios respaldos; seleccionar uno ya incluido actualiza su prioridad. Para añadir más credenciales de respaldo del mismo servicio use **Agregar clave** dentro del proveedor.

Use **Reordenar** en la lista de modelos para mover filas arrastrando su tirador, o con flechas arriba/abajo al enfocarlo. El orden se guarda automáticamente; el primer modelo pasa a ser principal y los demás quedan como respaldos. **Terminar edición** muestra la configuración confirmada. Si falla el guardado se restaura el orden anterior.
