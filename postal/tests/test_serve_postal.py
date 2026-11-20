from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings

from postal.data import DataError, Stream


COMMAND = 'postal.management.commands.serve_postal'
PRODUCTION_ENV = {
    'BOLIPOST_HOST': 'postal.example.org',
    'DJANGO_SECRET_KEY': 'abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ',
}


@override_settings(HTTPS_ONLY=True, ALLOWED_HOSTS=['postal.example.org'])
class ProductionStartupTests(TestCase):
    def test_rejects_a_missing_production_secret_before_listening(self):
        with patch.dict('os.environ', {'DJANGO_SECRET_KEY': ''}), patch(f'{COMMAND}.serve') as serve:
            with self.assertRaisesRegex(CommandError, 'DJANGO_SECRET_KEY'):
                call_command('serve_postal')
        serve.assert_not_called()

    @override_settings(DATA_MODE='postgres', BUSINESS_DATABASE_URL='postgresql://reader@db/postal')
    def test_preflight_queries_postgres_through_the_read_only_source(self):
        with (
            TemporaryDirectory() as directory,
            override_settings(STATIC_ROOT=directory, SYSTEM_CONFIG_PATH=Path(directory) / 'settings.json'),
            patch.dict('os.environ', PRODUCTION_ENV),
            patch(f'{COMMAND}.serve') as serve,
            patch('postal.data.PostgresSource.catalog', return_value=[{'name': 'sucursales', 'queryable': True}]),
            patch('postal.data.PostgresSource.stream') as stream,
        ):
            for asset in ('postal/app.js', 'postal/app.css', 'vendor/chart.umd.js'):
                target = Path(directory) / asset
                target.parent.mkdir(exist_ok=True)
                target.touch()

            stream.side_effect = DataError('database_unavailable', 'Detalle interno de la conexión')
            with self.assertRaisesRegex(CommandError, '^No se pudo comprobar PostgreSQL'):
                call_command('serve_postal')
            serve.assert_not_called()

            stream.reset_mock(side_effect=True)
            rows = iter([{'available': 1}])
            stream.return_value.__enter__.return_value = Stream(['available'], rows, ['sucursales'])
            call_command('serve_postal', '--check-only', stdout=StringIO())
            stream.assert_called_once_with('SELECT 1 AS available FROM assistant."sucursales" LIMIT 1')
            self.assertEqual(list(rows), [])
            serve.assert_not_called()

    @override_settings(ALLOWED_HOSTS=['postal.example.org', '.example.org'])
    def test_rejects_wildcard_hosts(self):
        with patch.dict('os.environ', PRODUCTION_ENV):
            with self.assertRaisesRegex(CommandError, 'sin comodines'):
                call_command('serve_postal', '--check-only')

    def test_preflight_checks_migrations_and_collected_assets_without_listening(self):
        with (
            TemporaryDirectory() as directory,
            override_settings(STATIC_ROOT=directory, SYSTEM_CONFIG_PATH=Path(directory) / 'settings.json',
                              DATA_MODE='demo'),
            patch.dict('os.environ', PRODUCTION_ENV),
            patch(f'{COMMAND}.serve') as serve,
        ):
            with self.assertRaisesRegex(CommandError, 'collectstatic'):
                call_command('serve_postal', '--check-only')

            for asset in ('postal/app.js', 'postal/app.css', 'vendor/chart.umd.js'):
                target = Path(directory) / asset
                target.parent.mkdir(exist_ok=True)
                target.touch()

            with patch(f'{COMMAND}.MigrationExecutor') as executor:
                executor.return_value.migration_plan.return_value = [object()]
                with self.assertRaisesRegex(CommandError, 'migrate'):
                    call_command('serve_postal', '--check-only')

            output = StringIO()
            call_command('serve_postal', '--check-only', stdout=output)
            self.assertIn('Configuración de producción verificada', output.getvalue())
        serve.assert_not_called()
