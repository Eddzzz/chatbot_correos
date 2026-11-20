# Red y base de datos

Propuesta aprobada por el usuario: conservar la identidad oscura/amarilla y organizar la pantalla en estado guardado, conexión postal y tiempos de espera compactos. Añadir comprobación de conexión guardada, mostrar únicamente la URL escrita, descartar cambios, valores predeterminados e indicador de cambios pendientes. Adaptar a móvil y tema claro.

Se elige una pantalla única sobre pestañas o asistentes porque solo hay seis campos y deben poder revisarse juntos. Reutilizar Django, los formularios y el diagnóstico existentes; sin dependencias ni migraciones. Conservar validación, permisos, CSRF, auditoría y secretos en servidor. Los predeterminados solo modifican el formulario hasta guardar. La comprobación nunca guarda borradores.
