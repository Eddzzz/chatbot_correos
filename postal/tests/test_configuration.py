from io import StringIO
from pathlib import Path
import tempfile
from unittest.mock import patch

import psycopg
from dotenv import dotenv_values
from django.core.management import call_command, get_commands
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings


class ConfigurationTests(SimpleTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.base = Path(self.folder.name)
        self.env = self.base / '.env'
        self.example = self.base / '.env.example'
        self.example.write_text('DATA_MODE=demo\nGROQ_API_KEY=\nBUSINESS_READONLY_PASSWORD=\n', encoding='utf-8')
        self.override = override_settings(BASE_DIR=self.base)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.stdout = StringIO()

    def configure(self, answers, **options):
        with patch('postal.management.commands.configure_services.getpass', side_effect=answers), patch('postal.management.commands.configure_services.psycopg.connect') as connect:
            call_command('configure_services', stdout=self.stdout, **options)
            return connect

    def test_command_is_available(self):
        self.assertIn('configure_services', get_commands())

    def test_encodes_credentials_preserves_other_settings_and_does_not_print_secrets(self):
        self.env.write_text('# conservar\nCUSTOM_VALUE=original\nBUSINESS_READONLY_PASSWORD=reader@:/secret\nDATA_MODE=postgres\n', encoding='utf-8')
        connect = self.configure(['router-secret', 'admin@:/secret'])
        values = dotenv_values(self.env)
        self.assertEqual(values['CUSTOM_VALUE'], 'original')
        self.assertIn('# conservar', self.env.read_text(encoding='utf-8'))
        self.assertEqual(values['DATA_MODE'], 'demo')
        self.assertEqual(values['GROQ_API_KEY'], 'router-secret')
        self.assertEqual(values['BUSINESS_ADMIN_DATABASE_URL'], 'postgresql://postgres:admin%40%3A%2Fsecret@127.0.0.1:5432/postgres')
        self.assertEqual(values['BUSINESS_DATABASE_URL'], 'postgresql://bolipost_reader:reader%40%3A%2Fsecret@127.0.0.1:5432/bolipost_consulta')
        self.assertEqual(connect.call_args.kwargs['connect_timeout'], 5)
        connect.return_value.__enter__.return_value.execute.assert_called_once_with('SELECT 1')
        for secret in ['router-secret', 'admin@:/secret', 'admin%40%3A%2Fsecret', 'reader@:/secret']:
            self.assertNotIn(secret, self.stdout.getvalue())
        self.assertIn('restore_backup', self.stdout.getvalue())
        self.assertIn('prepare_business', self.stdout.getvalue())

    def test_enter_keeps_existing_key_and_generates_only_missing_reader_password(self):
        self.env.write_text('GROQ_API_KEY=existing-key\nBUSINESS_READONLY_PASSWORD=\n', encoding='utf-8')
        with patch('postal.management.commands.configure_services.secrets.token_urlsafe', return_value='new-reader-password') as generate:
            self.configure(['', 'postgres-password'], database='respaldo_nuevo', db_user='admin@local')
        values = dotenv_values(self.env)
        self.assertEqual(values['GROQ_API_KEY'], 'existing-key')
        self.assertEqual(values['BUSINESS_READONLY_PASSWORD'], 'new-reader-password')
        self.assertIn('admin%40local:', values['BUSINESS_ADMIN_DATABASE_URL'])
        self.assertTrue(values['BUSINESS_DATABASE_URL'].endswith('/respaldo_nuevo'))
        generate.assert_called_once_with(24)

    def test_missing_env_uses_example_after_success_and_does_not_invent_api_key(self):
        self.configure(['', 'postgres-password'])
        values = dotenv_values(self.env)
        self.assertEqual(values['GROQ_API_KEY'], '')
        self.assertGreaterEqual(len(values['BUSINESS_READONLY_PASSWORD']), 24)

    def test_connection_failure_preserves_existing_file_and_redacts_provider_message(self):
        original = 'GROQ_API_KEY=existing-key\nCUSTOM_VALUE=original\n'
        self.env.write_text(original, encoding='utf-8')
        with patch('postal.management.commands.configure_services.getpass', side_effect=['new-key', 'secret-password']), patch('postal.management.commands.configure_services.psycopg.connect', side_effect=psycopg.OperationalError('secret-password DSN')):
            with self.assertRaises(CommandError) as caught:
                call_command('configure_services', stdout=self.stdout)
        self.assertEqual(self.env.read_text(encoding='utf-8'), original)
        self.assertNotIn('secret-password', str(caught.exception))
        self.assertEqual(self.stdout.getvalue(), '')

    def test_failed_verification_does_not_create_env(self):
        with patch('postal.management.commands.configure_services.getpass', side_effect=['', 'secret']), patch('postal.management.commands.configure_services.psycopg.connect') as connect:
            connect.return_value.__enter__.return_value.execute.side_effect = psycopg.OperationalError('secret')
            with self.assertRaises(CommandError):
                call_command('configure_services', stdout=self.stdout)
        self.assertFalse(self.env.exists())
