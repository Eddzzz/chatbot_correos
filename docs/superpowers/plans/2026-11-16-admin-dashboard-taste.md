# Dashboard y analíticas administrativas

Alcance solicitado: rediseñar la administración con Taste y añadir dashboard/analíticas.
Ejecución directa en el proyecto Django existente.

Taste: framed-sheet, seed 1461395669; azul institucional en la serie de consumo, marco
azul grisáceo, marca Correos y tipografía Geist local. Sin redibujos.
Pregunta principal: cuánto se está usando el asistente y qué requiere atención ahora.
Elemento propio: flujo planificador → analista → respuesta verificada, con consumo real por agente.

Datos: AIUsage (tokens, usuario, modelo, etapa, fecha), Conversation (chats conservados),
QueryJob (estado de trabajos recientes, vigencia 24h), configuración y caché actuales.
No se inventan tendencias, presupuestos, saldos ni disponibilidad de conexiones no comprobadas.

- [x] Pruebas de agregación por período, días locales, valores ausentes, permisos y ajustes parciales.
- [x] Servicio de agregación 7/30/90 días y contexto de dashboard; estados recientes identificados como 24h.
- [x] Vistas separadas mediante navegación real: resumen, analíticas, modelos, red, agentes, skills,
      chats, estado y auditoría; formularios guardan únicamente su sección.
- [x] Marco Taste con menú plegable móvil, gráficos SVG del helper de la skill y tablas accesibles.
- [x] Verificación Django, Edge, Taste Inspector, temas claro/oscuro y tamaños 1440/768/390/320;
      documentación y reinicio del servicio local sin trabajos activos.
