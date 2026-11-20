from django.db import migrations


def remove_skill(apps, schema_editor):
    AssistantSkill = apps.get_model('postal', 'AssistantSkill')
    AssistantSkill.objects.using(schema_editor.connection.alias).filter(preset_key='brief-explanations').delete()


class Migration(migrations.Migration):
    dependencies = [('postal', '0015_requestquota')]

    operations = [migrations.RunPython(remove_skill)]
