import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import override_settings

from .api_client import ApiTestCase

from postal.models import AssistantSkill


class SystemSkillsTests(ApiTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        override = override_settings(SYSTEM_CONFIG_PATH=Path(folder.name) / 'system.json',
                                     RESULT_DIR=Path(folder.name) / 'results')
        override.enable()
        self.addCleanup(override.disable)
        self.admin = get_user_model().objects.create_superuser('skills-admin')
        self.client.force_login(self.admin)

    def test_predefined_skills_are_saved_active_and_editor_is_hidden(self):
        response = self.client.get('/system/?view=skills')
        self.assertContains(response, 'Skills predefinidas')
        self.assertContains(response, 'Estadística descriptiva')
        self.assertContains(response, 'Gráficas de barras y líneas')
        self.assertNotContains(response, 'Explicaciones breves y ampliables')
        self.assertFalse(AssistantSkill.objects.filter(preset_key='brief-explanations').exists())
        self.assertNotContains(response, 'id="skill-editor"')
        self.assertEqual(len(response.context['skill_presets']), 14)
        self.assertEqual(AssistantSkill.objects.filter(preset_key__isnull=False, enabled=True).count(), 14)
        self.assertNotContains(response, 'Usar plantilla')
        self.assertContains(response, 'Desactivar Estadística descriptiva')
        response = self.client.get('/system/?view=skills&new_skill=1')
        self.assertContains(response, 'id="skill-editor"')
        self.assertFalse(response.context['skill_form'].is_bound)

    def test_each_predefined_skill_can_be_edited_without_creating_duplicates(self):
        from postal.skill_presets import SKILL_PRESETS
        for preset in SKILL_PRESETS:
            skill = AssistantSkill.objects.get(preset_key=preset['id'])
            response = self.client.get(f'/system/?view=skills&edit_skill={skill.pk}')
            self.assertContains(response, 'id="skill-editor"')
            form = response.context['skill_form']
            self.assertEqual(form.instance, skill)
            result = self.client.post('/system/?view=skills', {
                'action': 'skill_save', 'skill_id': skill.pk, 'skill-name': preset['name'] + ' editada',
                'skill-instructions': 'Instrucción personalizada.',
                'skill-stage': 'analyst'})
            self.assertRedirects(result, '/system/?view=skills')
            skill.refresh_from_db()
            self.assertEqual(skill.instructions, 'Instrucción personalizada.')
            self.assertEqual(skill.stage, 'analyst')
            self.assertFalse(skill.enabled)
            self.client.get('/system/?view=skills')
            skill.refresh_from_db()
            self.assertFalse(skill.enabled)
            self.assertEqual(skill.name, preset['name'] + ' editada')
        self.assertEqual(AssistantSkill.objects.count(), 14)

    def test_unknown_preset_is_404_and_non_admin_is_forbidden(self):
        self.assertEqual(self.client.get('/system/?view=skills&preset=unknown').status_code, 404)
        user = get_user_model().objects.create_user('skills-user')
        self.client.force_login(user)
        self.assertEqual(self.client.get('/system/?view=skills&preset=charts').status_code, 403)

    def test_editor_stays_open_on_validation_errors_and_when_editing(self):
        skill = AssistantSkill.objects.create(name='Existente', stage='analyst', instructions='Resume.')
        response = self.client.get(f'/system/?view=skills&edit_skill={skill.pk}')
        self.assertContains(response, 'id="skill-editor"')
        response = self.client.post('/system/?view=skills', {'action': 'skill_save',
            'skill-name': 'Existente', 'skill-instructions': 'Texto pendiente', 'skill-stage': 'both'})
        self.assertContains(response, 'id="skill-editor"')
        self.assertEqual(response.context['skill_form']['instructions'].value(), 'Texto pendiente')
        self.assertTrue(response.context['skill_form'].errors)
        self.assertEqual(AssistantSkill.objects.count(), 15)

    def test_set_enabled_is_persistent_idempotent_and_validated(self):
        skill = AssistantSkill.objects.get(preset_key='charts')
        for value in ('0', '0', '1', '1'):
            response = self.client.post('/system/?view=skills', {
                'action': 'skill_toggle', 'skill_id': skill.pk, 'enabled': value})
            self.assertEqual(response.status_code, 302)
            skill.refresh_from_db()
            self.assertEqual(skill.enabled, value == '1')
        for data in ({'skill_id': skill.pk, 'enabled': 'bad'}, {'enabled': '0'},
                     {'skill_id': 'bad', 'enabled': '0'}):
            self.assertEqual(self.client.post('/system/?view=skills', {'action': 'skill_toggle', **data}).status_code, 403)
        self.assertEqual(self.client.post('/system/?view=skills', {
            'action': 'skill_delete', 'skill_id': skill.pk}).status_code, 403)
        self.client.force_login(get_user_model().objects.create_user('operator'))
        self.assertEqual(self.client.post('/system/?view=skills', {
            'action': 'skill_toggle', 'skill_id': skill.pk, 'enabled': '0'}).status_code, 403)

    def test_seed_preserves_existing_customization_and_does_not_duplicate(self):
        import importlib
        from types import SimpleNamespace
        from django.apps import apps
        seed = importlib.import_module('postal.migrations.0008_functional_predefined_skills').seed_skills
        AssistantSkill.objects.get(preset_key='charts').delete()
        existing = AssistantSkill.objects.create(name='Gráficas de barras y líneas',
            instructions='Texto propio anterior.', stage='analyst', enabled=False)
        editor = SimpleNamespace(connection=SimpleNamespace(alias='default'))
        seed(apps, editor)
        existing.refresh_from_db()
        self.assertEqual(existing.preset_key, 'charts')
        self.assertEqual(existing.instructions, 'Texto propio anterior.')
        self.assertFalse(existing.enabled)
        existing.name = 'Nombre personalizado'
        existing.save()
        seed(apps, editor)
        self.assertEqual(AssistantSkill.objects.count(), 14)
        existing.refresh_from_db()
        self.assertEqual(existing.name, 'Nombre personalizado')

    @override_settings(JOBS_EAGER=True, DATA_MODE='demo', AI_PROVIDER='groq', GROQ_API_KEY='fake-key')
    def test_predefined_instructions_reach_agents_only_when_enabled(self):
        import json
        import httpx
        from unittest.mock import patch
        from django.core.cache import cache
        from postal.models import QueryJob
        AssistantSkill.objects.update(enabled=False)
        skill = AssistantSkill.objects.get(preset_key='charts')
        skill.instructions = 'PREDEFINED_FUNCTIONAL_QA'
        skill.save()
        real_client = httpx.Client
        for enabled, stage in ((True, 'planner'), (False, 'planner'), (True, 'analyst')):
            cache.clear()
            skill.stage = stage
            skill.save()
            self.client.post('/system/?view=skills', {'action': 'skill_toggle',
                'skill_id': skill.pk, 'enabled': '1' if enabled else '0'})
            requests = []
            def reply(request):
                sent = json.loads(request.content)
                requests.append(sent)
                content = {'sql': 'SELECT COUNT(*) AS cantidad FROM assistant.paquetes_ems', 'title': 'EMS'} if 'planificador SQL' in sent['messages'][0]['content'] else {
                    'paragraphs': [{'kind': 'value', 'references': [{'panel': 0, 'row': 0, 'column': 'cantidad'}]}]}
                return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(content)}}]})
            with patch('postal.ai.httpx.Client', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(reply), **kw)):
                response = self.client.post('/api/chat/', {'question': 'Cuenta los envíos EMS'}, content_type='application/json')
            self.assertEqual(QueryJob.objects.get(pk=response.json()['id']).status, 'ok')
            for agent, marker in (('planner', 'planificador SQL'), ('analyst', 'analista postal')):
                sent = [item for item in requests if marker in item['messages'][0]['content']]
                self.assertTrue(sent)
                self.assertEqual('PREDEFINED_FUNCTIONAL_QA' in json.dumps(sent), enabled and stage == agent)
