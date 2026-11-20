from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('postal', '0008_functional_predefined_skills')]
    operations = [migrations.AddField(model_name='systemaudit', name='metadata',
                                    field=models.JSONField(blank=True, default=dict))]
