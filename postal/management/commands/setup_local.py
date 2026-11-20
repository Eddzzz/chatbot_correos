"""Inicializa una cuenta local sin contraseñas fijas ni secretos en stdout."""
import secrets
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Crea una cuenta administrativa local y guarda el acceso en .runtime/local-access.txt (ignorado por Git).'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='administrador')

    def handle(self, **options):
        username = options['username']
        model = get_user_model()
        if model.objects.filter(username=username).exists():
            self.stdout.write('La cuenta ya existe. No se modificó su contraseña.')
            return
        target = settings.RUNTIME_DIR / 'local-access.txt'
        if target.exists():
            raise CommandError('Ya existe un archivo de acceso local. Administre cuentas con createsuperuser o changepassword.')
        password = secrets.token_urlsafe(24)
        account = model.objects.create_superuser(username=username, email='', password=password)
        try:
            with target.open('x', encoding='utf-8') as stream:
                stream.write(f'Bolipost · acceso local\nURL: http://127.0.0.1:8000\nUsuario: {username}\nContraseña: {password}\n\nCambie la contraseña desde /admin/password_change/.\nEste archivo contiene un secreto: no lo comparta ni lo suba a Git.\n')
            target.chmod(0o600)
        except OSError:
            account.delete()
            raise CommandError('No se pudo guardar el acceso local. La cuenta nueva se revirtió.') from None
        self.stdout.write('Cuenta creada. Abra .runtime/local-access.txt para ingresar; no se imprimieron secretos.')
