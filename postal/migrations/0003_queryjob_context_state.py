from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('postal', '0002_queryjob_analysis_queryjob_panels_and_more')]

    operations = [migrations.AddField(
        model_name='queryjob', name='context_state', field=models.JSONField(default=dict))]
