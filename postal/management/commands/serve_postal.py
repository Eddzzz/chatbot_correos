import os
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.core.management.base import BaseCommand, CommandError
from django.core.wsgi import get_wsgi_application
from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor
from waitress import serve

from postal.data import DataError, get_source
from postal.policy import QueryRejected
from postal.system_config import configuration


class Command(BaseCommand):
    help = 'Sirve Bolipost en loopback para desarrollo HTTP o detrás del proxy HTTPS.'

    def add_arguments(self, parser):
        parser.add_argument('--port', type=int, default=8000)
        parser.add_argument('--local-http', action='store_true')
        parser.add_argument('--check-only', action='store_true', help='Comprueba el arranque HTTPS y termina.')

    def handle(self, *args, **options):
        local_http = options['local_http']
        if local_http == settings.HTTPS_ONLY:
            raise CommandError('Use DJANGO_HTTPS=false solo con --local-http. Para el proxy, habilite HTTPS.')
        if options['check_only'] and local_http:
            raise CommandError('--check-only requiere el modo HTTPS.')
        if not local_http:
            self.check_production()
            if options['check_only']:
                self.stdout.write(self.style.SUCCESS('Configuración de producción verificada.'))
                return

        application = get_wsgi_application()
        if local_http:
            application = StaticFilesHandler(application)
            proxy = {}
        else:
            proxy = {'trusted_proxy': '127.0.0.1',
                     'trusted_proxy_headers': {'x-forwarded-for', 'x-forwarded-proto'}}
        serve(application, host='127.0.0.1', port=options['port'], ident='Bolipost',
              max_request_body_size=8 * 1024 * 1024, **proxy)

    def check_production(self):
        secret = os.environ.get('DJANGO_SECRET_KEY', '')
        if len(secret) < 50 or len(set(secret)) < 5 or secret.startswith('django-insecure-'):
            raise CommandError('Configure DJANGO_SECRET_KEY con una clave aleatoria de al menos 50 caracteres.')

        public_host = os.environ.get('BOLIPOST_HOST', '').lower()
        if (not public_host or public_host not in settings.ALLOWED_HOSTS
                or any(host.startswith(('.', '*')) for host in settings.ALLOWED_HOSTS)):
            raise CommandError('Defina BOLIPOST_HOST e inclúyalo explícitamente en DJANGO_ALLOWED_HOSTS, sin comodines.')

        assets = ('postal/app.js', 'postal/app.css', 'vendor/chart.umd.js')
        if not all((Path(settings.STATIC_ROOT) / asset).is_file() for asset in assets):
            raise CommandError('Ejecute manage.py collectstatic --noinput antes de iniciar Caddy.')

        try:
            executor = MigrationExecutor(connection)
            pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        except DatabaseError:
            raise CommandError('No se pudo abrir la base de cuentas. Revise los permisos de .runtime.') from None
        if pending:
            raise CommandError('La base de cuentas tiene migraciones pendientes. Ejecute manage.py migrate --noinput.')

        try:
            config = configuration()
        except (OSError, ValueError):
            raise CommandError('Revise el archivo privado .runtime/system-settings.json.') from None
        if config['DATA_MODE'] not in ('demo', 'postgres'):
            raise CommandError('DATA_MODE debe ser demo o postgres.')
        if config['DATA_MODE'] == 'postgres':
            if not config['BUSINESS_DATABASE_URL']:
                raise CommandError('Configure BUSINESS_DATABASE_URL con el rol postal de solo lectura.')
            try:
                source = get_source()
                table = next((item['name'] for item in source.catalog() if item['queryable']), None)
                sql = f'SELECT 1 AS available FROM assistant."{table}" LIMIT 1' if table else 'SELECT 1 AS available'
                with source.stream(sql) as stream:
                    next(iter(stream.rows), None)
            except (DataError, QueryRejected):
                raise CommandError('No se pudo comprobar PostgreSQL. Revise la conexión, el modo de vistas y los permisos de lectura.') from None
