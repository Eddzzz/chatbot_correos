from django.core.management.base import BaseCommand, CommandError

from postal.policy import available_columns
from postal.table_permissions import prepare_table


class Command(BaseCommand):
    help = 'Actualiza la vista de asignaciones de roles en el respaldo aislado configurado.'

    def handle(self, *args, **options):
        columns = available_columns()['user_roles']
        if not columns:
            return
        try:
            prepare_table('user_roles', columns)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write('Vista assistant.user_roles preparada para el lector configurado.')
