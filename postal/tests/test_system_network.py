import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings


class NetworkSettingsTests(TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.config_path = Path(folder.name) / 'settings.json'
        overrides = override_settings(SYSTEM_CONFIG_PATH=self.config_path,
            RESULT_DIR=Path(folder.name) / 'results', DATA_MODE='demo',
            BUSINESS_DATABASE_URL='postgresql://private_user:private_password@postal.example/postal')
        overrides.enable()
        self.addCleanup(overrides.disable)
        self.admin = get_user_model().objects.create_superuser('network-admin', password='test-password')
        self.client.force_login(self.admin)

    def test_network_controls_and_private_connection_summary(self):
        response = self.client.get('/system/?view=network')
        self.assertContains(response, 'Editar origen postal')
        self.assertNotContains(response, 'id="id_AI_TIMEOUT"')
        self.assertNotContains(response, 'id="id_BUSINESS_DATABASE_URL"')
        self.assertContains(response, 'Comprobar conexión guardada')
        self.assertContains(response, 'postal.example')
        self.assertNotContains(response, 'private_user')
        self.assertNotContains(response, 'private_password')

    def test_only_selected_section_can_be_edited_and_saved(self):
        response = self.client.get('/system/?view=network&edit_network=ai')
        self.assertContains(response, 'id="id_AI_TIMEOUT"')
        self.assertNotContains(response, 'id="id_DB_CONNECT_TIMEOUT"')
        self.assertNotContains(response, 'id="id_BUSINESS_DATABASE_URL"')
        response = self.client.post('/system/?view=network&edit_network=ai', {
            'action': 'settings', 'settings_area': 'network', 'network_section': 'ai',
            'AI_TIMEOUT': '180', 'AI_CONNECT_TIMEOUT': '20', 'DB_CONNECT_TIMEOUT': '59'})
        self.assertEqual(response.status_code, 302)
        import json
        saved = json.loads(self.config_path.read_text())
        self.assertEqual(saved['AI_TIMEOUT'], 180)
        self.assertNotIn('DB_CONNECT_TIMEOUT', saved)

    def test_invalid_section_values_keep_editor_open(self):
        response = self.client.post('/system/?view=network&edit_network=ai', {
            'action': 'settings', 'settings_area': 'network', 'network_section': 'ai',
            'AI_TIMEOUT': '999', 'AI_CONNECT_TIMEOUT': '20'})
        self.assertContains(response, 'No se guardaron los cambios')
        self.assertContains(response, 'id="id_AI_TIMEOUT"')
        self.assertFalse(self.config_path.exists())

    @patch('postal.system_views.database_check', return_value='Conexión comprobada de prueba.')
    def test_check_stays_in_network_without_saving_draft(self, check):
        response = self.client.post('/system/?view=network', {
            'action': 'check_database', 'AI_TIMEOUT': '299',
            'BUSINESS_DATABASE_URL': 'postgresql://draft:secret@other.example/db'})
        self.assertEqual(response.context['active_view'], 'network')
        self.assertContains(response, 'Conexión comprobada de prueba.')
        self.assertContains(response, 'Editar origen postal')
        self.assertFalse(self.config_path.exists())
        self.assertNotContains(response, 'draft:secret')

    @patch('postal.system_views.database_check')
    def test_check_requires_administrator(self, check):
        user = get_user_model().objects.create_user('network-user')
        self.client.force_login(user)
        self.assertEqual(self.client.post('/system/?view=network', {'action': 'check_database'}).status_code, 403)
        check.assert_not_called()
