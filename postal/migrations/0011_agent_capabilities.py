from django.db import migrations


PREDEFINED_SKILLS = [{'id': 'delays',
  'name': 'Demoras y tiempos de tránsito',
  'stage': 'both',
  'instructions': 'Para analizar demoras o tiempos de tránsito, identifica primero las fechas autorizadas de '
                  'inicio y fin y su significado. La fecha de registro no implica admisión y el último '
                  'evento no implica entrega. Usa un evento de entrega solo con equivalencia documentada y '
                  'asociación inequívoca al envío y servicio. Agrega eventos antes de unir para no '
                  'multiplicar envíos; no mezcles códigos repetidos entre servicios ni registros ambiguos. '
                  'Calcula duraciones únicamente con fechas válidas, no nulas y ordenadas; informa excluidos '
                  'y tamaño del conjunto. Para pendientes pide o declara la fecha de corte y distingue '
                  'antigüedad de demora. Compara con un umbral solo si está documentado o lo proporciona el '
                  'usuario; sin él presenta tiempos observados y pide el criterio de retraso. No inventes '
                  'estados, tiempos, causas ni entregas.'},
 {'id': 'delivery-sla',
  'name': 'Cumplimiento de plazos de entrega',
  'stage': 'both',
  'instructions': 'Para evaluar cumplimiento de plazos o SLA, verifica el plazo aplicable por servicio, las '
                  'fechas de inicio y entrega, la zona horaria y si se cuentan días calendario o hábiles. Si '
                  'falta una regla esencial, solicita aclaración antes de clasificar; no supongas un SLA '
                  'institucional ni un calendario de feriados. Solo identifica entregas mediante eventos o '
                  'estados cuya equivalencia esté documentada. Consulta todo el conjunto filtrado, conserva '
                  'una fila por envío y separa entregados dentro de plazo, fuera de plazo, pendientes y no '
                  'evaluables. Declara el denominador de la tasa, el período, la fecha de corte, el criterio '
                  'inclusivo del límite y las exclusiones. No incluyas pendientes como entregas tardías ni '
                  'interpretes datos ausentes como cumplimiento. Los códigos duplicados sin relación '
                  'verificable son no evaluables. Fundamenta cada conclusión en agregados consultados.'},
 {'id': 'period-comparison',
  'name': 'Comparación entre períodos',
  'stage': 'both',
  'instructions': 'Para comparar períodos, confirma dos intervalos explícitos y la fecha usada para asignar '
                  'cada envío. Aplica la misma métrica, servicio, ubicación y filtros a ambos; usa inicio '
                  'inclusivo y fin exclusivo para fechas con hora. Si solo se indica un mes sin año y el '
                  'contexto no lo resuelve, pide el año. Consulta agregados del conjunto completo por '
                  'período antes de calcular diferencias absolutas y porcentuales. La variación porcentual '
                  'usa el período base como denominador; con base cero indica no calculable. Separa períodos '
                  'parciales de completos, explica diferencias de duración y cobertura y usa promedios por '
                  'día solo si tiene sentido y declaras el denominador. Distingue falta de datos de cero '
                  'real y no atribuyas causalidad a la variación. Conserva las unidades y usa barras o '
                  'líneas admitidas con valores verificados.'}]


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
    dependencies = [('postal', '0010_model_fallback_order')]
    operations = [migrations.RunPython(seed_skills, migrations.RunPython.noop)]
