# Implementación de administración del sistema

**Objetivo:** ejecutar el alcance aprobado en ../specs/2026-11-16-system-management.md.
**Arquitectura:** Django, plantillas y JavaScript existentes, SQLite para chats y consumo;
archivo privado de configuración sin dependencias adicionales. Ejecución en esta sesión.

- [x] Pruebas de permisos, aislamiento, revisiones, papelera y límite exacto de 30 días.
- [x] Conversation, AIUsage, SystemAudit, AssistantSkill y PurgedConversation; migraciones,
      API de historial y mantenimiento.
- [x] Formulario validado de configuración, integración de proveedores/DB/agentes/skills,
      registro de consumo por trabajo, diagnóstico y limpieza limitada de resultados vencidos.
- [x] Panel administrativo, papelera de usuario y migración no destructiva del historial local.
- [x] Verificar con pruebas Django, sintaxis JavaScript y navegador en escritorio/móvil;
      aplicar migraciones locales y documentar inicio, privacidad y operación de la purga.

Revisar: accesos cruzados, claves en HTML/errores, actualizaciones desde pestañas obsoletas,
chats grandes, carreras con consultas activas y resultados vencidos.

Verificación final: 266 pruebas Django (261 aprobadas, 5 de integración PostgreSQL omitidas),
18 pruebas nuevas de gestión incluidas. Edge verifica diez flujos, ambos temas y cuatro
anchos, sin errores JS. Revisión independiente corrigió dos carreras de guardado/carga;
sin hallazgos P1/P2 pendientes. Copia de cuentas previa, migraciones aplicadas y servidor
local reiniciado, panel autenticado comprobado sin secretos en HTML.
