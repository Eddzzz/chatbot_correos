"""Collect local secrets without displaying them or changing the business database."""
from getpass import getpass
from pathlib import Path
import secrets
import sys
from urllib.parse import quote

import psycopg
from dotenv import dotenv_values, set_key
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from .restore_backup import check_name


class Command(BaseCommand):
    help = 'Configura credenciales locales y verifica PostgreSQL sin restaurar ni crear roles.'

    def add_arguments(self, parser):
        parser.add_argument('--db-user', default='postgres')
        parser.add_argument('--host', default='127.0.0.1')
        parser.add_argument('--port', type=int, default=5432)
        parser.add_argument('--database', default='bolipost_consulta')
        parser.add_argument('--role', default='bolipost_reader')

    def handle(self, *args, **options):
        check_name(options['database'])
        check_name(options['role'])
        if not 1 <= options['port'] <= 65535:
            raise CommandError('El puerto PostgreSQL no es válido.')
        env_path = Path(settings.BASE_DIR) / '.env'
        template = env_path if env_path.exists() else Path(settings.BASE_DIR) / '.env.example'
        existing = dotenv_values(template)
        try:
            api_key = getpass('Clave Groq (Enter conserva la existente): ')
            admin_password = getpass('Contraseña PostgreSQL: ')
        except (EOFError, KeyboardInterrupt):
            raise CommandError('Configuración cancelada; no se guardaron cambios.') from None
        if not admin_password:
            raise CommandError('Introduzca la contraseña PostgreSQL; no se guardaron cambios.')

        def url(user, password, database):
            return 'postgresql://{}:{}@{}:{}/{}'.format(
                quote(user, safe=''), quote(password, safe=''), quote(options['host'], safe=''),
                options['port'], quote(database, safe=''))

        admin_url = url(options['db_user'], admin_password, 'postgres')
        try:
            with psycopg.connect(admin_url, connect_timeout=5) as connection:
                connection.execute('SELECT 1')
        except psycopg.Error:
            raise CommandError('No se pudo verificar PostgreSQL. Revise usuario, contraseña y conexión; no se guardaron cambios.') from None

        reader_password = existing.get('BUSINESS_READONLY_PASSWORD') or secrets.token_urlsafe(24)
        values = {
            'BUSINESS_ADMIN_DATABASE_URL': admin_url,
            'BUSINESS_DATABASE_URL': url(options['role'], reader_password, options['database']),
            'BUSINESS_READONLY_PASSWORD': reader_password,
            'DATA_MODE': 'demo',
        }
        if api_key:
            values['GROQ_API_KEY'] = api_key
        if not env_path.exists():
            env_path.write_text(template.read_text(encoding='utf-8'), encoding='utf-8')
        for key, value in values.items():
            set_key(str(env_path), key, value)
        self.stdout.write('Configuración guardada.')
        runner = f'"{sys.executable}" "{Path(settings.BASE_DIR) / "manage.py"}"'
        pg_restore = Path(settings.PG_BIN) / ('pg_restore.exe' if sys.platform == 'win32' else 'pg_restore')
        self.stdout.write(f'& {runner} restore_backup "{settings.BACKUP_PATH}" --database {options["database"]} --pg-restore "{pg_restore}"')
        self.stdout.write(f'& {runner} prepare_business --database {options["database"]} --role {options["role"]}')
        self.stdout.write('Para usar esa restauración aislada, configure DATA_MODE=postgres y BUSINESS_USE_ISOLATED_VIEWS=1 en .env y reinicie el servidor.')
