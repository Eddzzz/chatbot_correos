"""Skills ampliadas sin sobrescribir personalizaciones existentes."""
from django.db import migrations

PREDEFINED_SKILLS = [{'id': 'extended-statistics',
  'name': 'Estadísticas ampliadas',
  'category': 'Estadísticas',
  'stage': 'both',
  'description': 'Rango, promedios, cobertura y variaciones sobre el conjunto completo.',
  'instructions': 'Cuando se pidan más estadísticas, consulta COUNT, SUM, AVG, MIN y MAX de peso, '
                  'precio u otras medidas pertinentes del conjunto completo filtrado. Incluye '
                  'conteo de valores válidos y nulos, rango MAX menos MIN y promedios por grupo '
                  'cuando correspondan. Usa solo expresiones SQL autorizadas; no solicites '
                  'funciones de mediana, percentiles o desviación no admitidas por el motor. No '
                  'promedies códigos, identificadores ni promedios de grupos sin ponderar. '
                  'Conserva unidades documentadas, período y filtros; no supongas moneda ni unidad '
                  'de peso. Para porcentajes y variaciones declara denominador y trata base cero '
                  'como no calculable. Presenta solo medidas consultadas, sin extrapolar filas '
                  'visibles ni confundir registros con envíos.'},
 {'id': 'brief-explanations',
  'name': 'Explicaciones breves y ampliables',
  'category': 'Respuestas',
  'stage': 'both',
  'description': 'Respuesta breve por defecto; más detalle cuando el usuario lo solicita.',
  'instructions': 'Responde con uno a tres hallazgos relevantes por defecto, empezando por el dato '
                  'que responde a la pregunta. Si el usuario pide ampliar, explicar en detalle, '
                  'más información o un reporte completo, desarrolla hasta ocho hallazgos según la '
                  'evidencia disponible. En continuaciones conserva período, servicio, ubicación y '
                  'referente verificados; amplía únicamente lo solicitado. No repitas todas las '
                  'tablas en el texto. Conserva advertencias necesarias, referencias y el esquema '
                  'JSON del agente; no agregues prosa libre ni cifras sin verificar.'},
 {'id': 'evidence-advice',
  'name': 'Consejos basados en evidencia',
  'category': 'Respuestas',
  'stage': 'analyst',
  'description': 'Un siguiente paso breve vinculado a las cifras consultadas.',
  'instructions': 'En análisis estadísticos, cuando ayude al usuario o pida consejos, incluye como '
                  'máximo un hallazgo kind advice con referencias a celdas relevantes de una misma '
                  'fila. El servidor redacta el consejo de revisar el desglose y comparar períodos '
                  'equivalentes antes de decidir. Diferencia siempre una recomendación de un hecho '
                  'observado. No atribuyas causas, incumplimientos, calidad de servicio o '
                  'necesidades de personal a un volumen aislado; no inventes acciones ya '
                  'realizadas, metas ni plazos institucionales. Conserva las referencias y no '
                  'añadas campos de texto libre al JSON.'},
 {'id': 'statistical-reporter',
  'name': 'Reportero estadístico y PDF',
  'category': 'Informes',
  'stage': 'both',
  'description': 'Informes con indicadores, comparaciones y consejos exportables a PDF.',
  'instructions': 'Si se solicita un reporte o informe estadístico, usa intent report y hasta seis '
                  'consultas autorizadas: indicadores globales, distribución por la categoría '
                  'pedida, evolución temporal y comparación cuando los datos lo permitan. Incluye '
                  'solo secciones pertinentes y conserva el mismo período, servicio y ubicación. '
                  'Usa barras o líneas admitidas sobre agregados completos; no inventes datos '
                  'faltantes. El analista organiza primero los principales indicadores, después '
                  'comparaciones verificadas y un consejo breve si procede. Amplía cuando el '
                  'usuario lo pida. La respuesta verificada y las tablas de las páginas '
                  'seleccionadas se incluyen en la exportación PDF existente; no afirmes que un '
                  'archivo fue creado o descargado por emitir una respuesta. No prometas que el '
                  'PDF contiene todas las filas si solo se exportan páginas seleccionadas.'}]


def seed_skills(apps, schema_editor):
    skills = apps.get_model('postal', 'AssistantSkill').objects.using(schema_editor.connection.alias)
    for preset in PREDEFINED_SKILLS:
        if skills.filter(preset_key=preset['id']).exists():
            continue
        existing = skills.filter(name=preset['name']).first()
        if existing is not None:
            if existing.preset_key is None:
                existing.preset_key = preset['id']
                existing.save(using=schema_editor.connection.alias, update_fields=['preset_key'])
            continue
        skills.create(preset_key=preset['id'], name=preset['name'], stage=preset['stage'],
                      instructions=preset['instructions'], enabled=True)


class Migration(migrations.Migration):
    dependencies = [('postal', '0011_agent_capabilities')]
    operations = [migrations.RunPython(seed_skills, migrations.RunPython.noop)]
