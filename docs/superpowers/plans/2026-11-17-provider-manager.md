# Gestor de proveedores, modelos y claves

1. Añadir catálogo persistente de proveedores, modelos, claves y modelo activo. Importar la configuración existente una sola vez, sin cambiar la conexión usada.
2. Implementar formularios y acciones administrativas para crear, editar, activar/desactivar y eliminar. Proteger la conexión activa y no devolver secretos al navegador ni a la auditoría.
3. Conectar el catálogo al cliente de IA: endpoints compatibles con OpenAI, modelos múltiples, claves ordenadas y captura de configuración al iniciar cada trabajo. Conservar el modo anterior hasta una activación explícita.
4. Reemplazar los campos fijos por un directorio con secciones de modelos y claves y formularios en diálogos.
5. Verificar permisos, validación, CRUD, conexión real mediante transporte simulado, claves de respaldo, conservación de secretos, migración y navegador en ambos temas y tamaños. Respaldar la base local antes de migrarla y verificar la instancia real sin crear proveedores de prueba en ella.
