"""Develop explanations and reserve advice for explicit requests."""
import importlib

from django.db import migrations


INSTRUCTIONS = {
    'brief-explanations': 'Para respuestas directas usa uno a tres hallazgos relevantes. Cuando el usuario pida una explicación, desarrolla el alcance de los datos, la distribución, las diferencias entre grupos y la concentración verificable; no te limites a mencionar el máximo y el mínimo. Usa distribution sobre desgloses completos cuando corresponda. Si pide más detalle, amplía hasta ocho hallazgos según la evidencia disponible. Conserva período, servicio, ubicación y referente verificados en las continuaciones. No repitas todas las tablas ni pidas repetir la pregunta. Pedir una explicación no implica solicitar un informe completo, otro dashboard ni consejos. Incluye consejos únicamente si el usuario los pide expresamente. Conserva advertencias necesarias, referencias y el esquema JSON del agente; no agregues prosa libre ni cifras sin verificar.',
    'evidence-advice': 'Incluye consejos únicamente cuando el usuario los pida expresamente; pedir una explicación o interpretar datos no equivale a pedir consejos. Cuando los solicite, incluye como máximo un hallazgo kind advice con referencias a celdas relevantes de una misma fila. Diferencia una recomendación de un hecho observado. No atribuyas causas, incumplimientos, calidad de servicio o necesidades de personal a un volumen aislado; no inventes acciones, metas, plazos ni medidas institucionales. Conserva las referencias y el esquema JSON. Mantén el consejo breve y, si pide desarrollarlo, usa únicamente evidencia verificada del mismo contexto.',
}


def update_skills(apps, schema_editor):
    skills = apps.get_model('postal', 'AssistantSkill').objects.using(schema_editor.connection.alias)
    original = importlib.import_module('postal.migrations.0012_statistics_advice_reporter')
    previous = importlib.import_module('postal.migrations.0013_chat_response_skills')
    for preset in original.PREDEFINED_SKILLS:
        if preset['id'] in INSTRUCTIONS:
            defaults = [preset['instructions'], preset['instructions'] + previous.ADDITIONS[preset['id']]]
            skills.filter(preset_key=preset['id'], instructions__in=defaults).update(instructions=INSTRUCTIONS[preset['id']])


class Migration(migrations.Migration):
    dependencies = [('postal', '0013_chat_response_skills')]
    operations = [migrations.RunPython(update_skills, migrations.RunPython.noop)]
