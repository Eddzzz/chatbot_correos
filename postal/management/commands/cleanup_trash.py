from django.core.management.base import BaseCommand
from postal.conversations import purge_trash


class Command(BaseCommand):
    help = 'Elimina definitivamente chats con 30 días o más en la papelera.'

    def handle(self, **options):
        self.stdout.write(f'Conversaciones vencidas eliminadas: {purge_trash()}.')
