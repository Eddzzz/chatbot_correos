# Estadísticas, consejos e informes PDF

Alcance confirmado: chatbot y sus informes PDF. Se amplían las skills editables
existentes, sin cambiar el panel administrativo ni el motor de consultas.

1. Añadir skills de estadística ampliada, explicación breve ampliable, consejos
   con evidencia y reportero estadístico. Registrar mediante migración repetible
   que conserve ediciones y desactivaciones existentes.
2. Admitir consejos con referencias verificadas y texto controlado por el servidor.
   Pedir al analista pocos hallazgos por defecto y más detalle a petición.
3. Incluir la respuesta verificada del chat en el PDF antes de las tablas.
4. Probar persistencia, instrucciones, referencias inválidas y contenido PDF;
   ejecutar las suites afectadas y revisar un PDF de demostración.

Se reutilizan Django, ReportLab y el contrato de evidencia. Añadir otro exportador
o permitir prosa factual libre introduciría duplicación o perdería verificabilidad.

## Verificación

- 118 pruebas de skills, IA, informes, PDF y capacidades: correctas.
- Navegador Edge aislado: creación, edición, activación, validación, capacidades,
  funcionamiento sin JavaScript, ambos temas y seis anchos: correcto.
- PDF de demostración generado, renderizado con Poppler y revisado visualmente:
  resumen, consejo y tabla legibles y sin recortes.
- Migración 0012 aplicada en la base local; las cuatro skills están activas.
  `makemigrations --check --dry-run` no detecta cambios pendientes.
- Las pruebas usan transporte simulado; no se evaluó la redacción de un proveedor
  externo real. El nivel de detalle se establece mediante la skill editable.
