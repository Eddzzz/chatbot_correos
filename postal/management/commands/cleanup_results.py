from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from postal.jobs import cancel, spool_path
from postal.models import QueryJob


class Command(BaseCommand):
    help = 'Elimina resultados temporales vencidos y chats con 30 días en la papelera.'

    def handle(self, **options):
        from postal.conversations import purge_trash
        purged = purge_trash()
        count = 0
        for job in QueryJob.objects.exclude(status__in=['queued', 'running']).filter(updated_at__lt=timezone.now() - timedelta(hours=settings.RESULT_TTL_HOURS)).iterator():
            cancel(job.id)
            try:
                spool_path(job.id).unlink(missing_ok=True)
            except PermissionError:
                continue
            job.delete()
            count += 1
        self.stdout.write(f'Resultados vencidos eliminados: {count}.')
        self.stdout.write(f'Conversaciones vencidas eliminadas: {purged}.')
