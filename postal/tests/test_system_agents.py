import json
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings


class AgentSettingsTests(TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'settings.json'
        config = override_settings(SYSTEM_CONFIG_PATH=self.path, RESULT_DIR=Path(folder.name) / 'results')
        config.enable()
        self.addCleanup(config.disable)
        self.client.force_login(get_user_model().objects.create_superuser('agent-admin', password='test-password'))

    def test_initial_view_has_no_editable_controls(self):
        response = self.client.get('/system/?view=agents')
        self.assertContains(response, 'Editar planificador')
        self.assertContains(response, 'Editar analista')
        self.assertContains(response, 'Editar presupuesto')
        self.assertNotContains(response, '<textarea')
        self.assertNotContains(response, 'type="checkbox"')
        self.assertNotContains(response, 'type="range"')
        self.assertNotContains(response, 'Guardar cambios')

    def test_selected_planner_saves_only_its_fields(self):
        response = self.client.get('/system/?view=agents&edit_agent=planner')
        self.assertContains(response, 'id="id_PLANNER_INSTRUCTIONS"')
        self.assertNotContains(response, 'id="id_ANALYST_INSTRUCTIONS"')
        self.assertNotContains(response, 'id="id_AI_MAX_TOKENS"')
        response = self.client.post('/system/?view=agents&edit_agent=planner', {
            'action': 'settings', 'settings_area': 'agents', 'agent_section': 'planner',
            'PLANNER_ENABLED': 'on', 'PLANNER_INSTRUCTIONS': 'Prioriza las fechas.',
            'AI_MAX_TOKENS': '9999'})
        self.assertEqual(response.status_code, 302)
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved['PLANNER_INSTRUCTIONS'], 'Prioriza las fechas.')
        self.assertNotIn('AI_MAX_TOKENS', saved)
        self.assertNotIn('ANALYST_ENABLED', saved)

    def test_invalid_budget_preserves_editor(self):
        response = self.client.post('/system/?view=agents&edit_agent=tokens', {
            'action': 'settings', 'settings_area': 'agents', 'agent_section': 'tokens', 'AI_MAX_TOKENS': '12001'})
        self.assertContains(response, 'No se guardaron los cambios')
        self.assertContains(response, 'id="id_AI_MAX_TOKENS"')
        self.assertNotContains(response, '<textarea')
        self.assertFalse(self.path.exists())
