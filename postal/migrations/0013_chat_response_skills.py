"""Traslada las preferencias del chat a skills editables sin pisar cambios propios."""
import importlib

from django.db import migrations


ADDITIONS = {
    'brief-explanations': ' Interpreta «amplía», «explícame más», «más detalle» y «desarrolla el consejo» como continuaciones de la consulta anterior. No pidas repetir la pregunta ni cambies sus filtros o su referente. Pedir una explicación o un consejo no implica solicitar un informe completo ni un dashboard. El límite breve de uno a tres hallazgos incluye el consejo; también se aplica a reportes y dashboards sin petición de detalle.',
    'evidence-advice': ' Mantén el consejo breve y evita consejos de relleno. Si el usuario pide desarrollar el consejo, amplía su explicación únicamente con evidencia verificada del mismo contexto, sin inventar causas ni medidas institucionales.',
}


def update_skills(apps, schema_editor):
    skills = apps.get_model('postal', 'AssistantSkill').objects.using(schema_editor.connection.alias)
    original = importlib.import_module('postal.migrations.0012_statistics_advice_reporter')
    for preset in original.PREDEFINED_SKILLS:
        addition = ADDITIONS.get(preset['id'])
        if addition:
            skills.filter(preset_key=preset['id'], instructions=preset['instructions']).update(
                instructions=preset['instructions'] + addition)


class Migration(migrations.Migration):
    dependencies = [('postal', '0012_statistics_advice_reporter')]
    operations = [migrations.RunPython(update_skills, migrations.RunPython.noop)]
