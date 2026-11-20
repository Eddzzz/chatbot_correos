# Usuarios y administración bento

Solicitud: agregar usuarios, mejorar Administrar con bento box y submenús.
Se amplía la aplicación Django y su identidad azul/amarilla existente.

- [x] Pruebas de creación/edición de cuentas, contraseñas, roles, permisos y protección de la cuenta propia.
- [x] Formulario nativo de usuarios, listado buscable/paginado y activación/desactivación sin borrar datos.
- [x] Centro Administrar bento con datos reales y enlaces a usuarios, IA, infraestructura y conversaciones.
- [x] Submenús plegables por área, pestañas internas y formularios agrupados en bloques bento.
- [x] Pruebas Django y Edge, temas claro/oscuro y escritorio/móvil; actualizar servidor local y documentación.

Solo superusuarios activos gestionan cuentas. La cuenta propia no se puede desactivar ni
degradar desde el panel. Las contraseñas usan los validadores y hash de Django, nunca se
precargan ni se auditan. Desactivar una cuenta cancela sus consultas en curso.
