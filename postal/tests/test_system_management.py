import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings

from .api_client import ApiTestCase
from django.utils import timezone


@override_settings(JOBS_EAGER=True, SECURE_SSL_REDIRECT=False)
class SystemManagementTests(ApiTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.override = override_settings(SYSTEM_CONFIG_PATH=Path(self.tmp.name) / 'system.json',
                                          RESULT_DIR=Path(self.tmp.name) / 'results')
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.user = get_user_model().objects.create_user('operador')
        self.other = get_user_model().objects.create_user('otro')
        self.admin = get_user_model().objects.create_superuser('administrador', password='test-password')
        self.client.force_login(self.user)
        self.chat_id = uuid.uuid4()

    def save_chat(self, **extra):
        return self.client.post(f'/api/conversations/{self.chat_id}/save/', {
            'title': 'Prueba', 'messages': [{'kind': 'question', 'text': 'Cuenta EMS'}],
            'revision': 0, **extra}, content_type='application/json')

    def test_management_is_superuser_only(self):
        self.assertEqual(self.client.get('/system/').status_code, 403)
        self.user.is_staff = True
        self.user.save()
        self.assertEqual(self.client.get('/system/').status_code, 403)
        self.assertEqual(self.client.post('/system/', {'action': 'cleanup'}).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/system/').status_code, 200)

    def test_chats_are_private_and_survive_login(self):
        self.assertEqual(self.save_chat().status_code, 200)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(f'/api/conversations/{self.chat_id}/').status_code, 404)
        self.assertEqual(self.client.get('/api/conversations/').json()['conversations'], [])
        self.assertEqual(self.save_chat().status_code, 404)
        self.client.force_login(self.user)
        data = self.client.get(f'/api/conversations/{self.chat_id}/').json()
        self.assertEqual(data['messages'][0]['text'], 'Cuenta EMS')

    def test_trash_restore_and_stale_save(self):
        self.save_chat()
        base = f'/api/conversations/{self.chat_id}/'
        self.assertEqual(self.save_chat().status_code, 409)
        self.assertEqual(self.client.post(base + 'trash/', {}, content_type='application/json').status_code, 200)
        self.assertEqual(self.client.get('/api/conversations/').json()['conversations'], [])
        self.assertEqual(len(self.client.get('/api/conversations/?trash=1').json()['conversations']), 1)
        self.assertEqual(self.save_chat(revision=1).status_code, 409)
        self.assertEqual(self.client.get(base).status_code, 404)
        self.assertEqual(self.client.post(base + 'restore/', {}, content_type='application/json').status_code, 200)
        self.assertEqual(self.client.get(base).json()['messages'][0]['text'], 'Cuenta EMS')

    def test_purge_uses_deletion_time_and_removes_only_expired_trash(self):
        from postal.models import Conversation
        from postal.conversations import purge_trash
        now = timezone.now()
        for days in (29, 30, 31):
            Conversation.objects.create(user=self.user, title=str(days), deleted_at=now - timedelta(days=days))
        Conversation.objects.create(user=self.user, title='Activo')
        purge_trash(now=now)
        self.assertEqual(set(Conversation.objects.values_list('title', flat=True)), {'29', 'Activo'})

    def test_legacy_import_cannot_resurrect_permanently_purged_chat(self):
        from postal.models import Conversation
        from postal.conversations import purge_trash
        self.save_chat()
        Conversation.objects.filter(pk=self.chat_id).update(deleted_at=timezone.now() - timedelta(days=31))
        purge_trash()
        self.assertEqual(self.save_chat(import_only=True).status_code, 410)
        self.assertFalse(Conversation.objects.filter(pk=self.chat_id).exists())
        self.assertEqual(self.save_chat().status_code, 410)

    def test_import_never_overwrites_existing_or_revives_trash(self):
        self.save_chat()
        self.client.post(f'/api/conversations/{self.chat_id}/trash/', {}, content_type='application/json')
        self.assertEqual(self.save_chat(import_only=True).status_code, 409)
        self.assertEqual(self.client.get('/api/conversations/').json()['conversations'], [])

    def test_legacy_import_is_explicit_and_keeps_conflicting_data(self):
        self.assertEqual(self.save_chat(import_only=True).status_code, 201)
        replay = self.save_chat(import_only=True)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()['import_status'], 'already_imported')
        self.assertEqual(self.save_chat(import_only=True, title='Otro título').status_code, 409)

    def test_server_settings_change_provider_without_exposing_key(self):
        from postal.system_config import save_config
        from postal.ai import provider_config
        save_config({'AI_PROVIDER': 'nvidia', 'NVIDIA_MODEL': 'custom/model', 'NVIDIA_API_KEY': 'secret-example'})
        self.assertEqual(provider_config()[0], 'NVIDIA')
        self.assertEqual(provider_config()[1], 'secret-example')
        self.client.force_login(self.admin)
        response = self.client.get('/system/')
        self.assertNotContains(response, 'secret-example')
        self.assertContains(response, 'custom/model')

    def test_disabled_capability_is_enforced_on_server(self):
        from postal.system_config import save_config
        save_config({'SKILL_CHAT': False})
        response = self.client.post('/api/chat/', {'question': 'Cuenta EMS'}, content_type='application/json')
        self.assertEqual(response.status_code, 403)

    def test_chat_inspection_uses_saved_chat_renderer_and_remains_admin_only(self):
        from postal.models import Conversation
        chat = Conversation.objects.create(user=self.user, title='Revisión', messages=[
            {'kind': 'question', 'text': '</script><script>alert(1)</script>'},
            {'kind': 'result', 'result': {'status': 'ok', 'title': 'Detalle',
                'columns': ['nombre', 'total'], 'rows': [{'nombre': 'Ana', 'total': 0}]}}
        ])
        url = f'/system/chats/{chat.pk}/'
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.get(url)
        self.assertContains(response, 'id="inspect-conversation"')
        self.assertContains(response, 'id="inspect-messages"')
        self.assertContains(response, 'postal/app.js')
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertEqual(response.context['column_labels']['nombre'], 'Nombre')
        chat.refresh_from_db()
        self.assertEqual(chat.messages[1]['result']['rows'][0]['total'], 0)

    def test_admin_conversations_have_separate_history_and_trash_per_account(self):
        from postal.models import Conversation
        own = Conversation.objects.create(user=self.user, title='Historial operador')
        trashed = Conversation.objects.create(user=self.user, title='Papelera operador', deleted_at=timezone.now())
        other = Conversation.objects.create(user=self.other, title='Historial otro')
        self.client.force_login(self.admin)
        directory = self.client.get('/system/?view=chats')
        self.assertContains(directory, 'Conversaciones por cuenta')
        accounts = {u.pk: u for u in directory.context['chat_accounts']}
        self.assertEqual((accounts[self.user.pk].history_count, accounts[self.user.pk].trash_count), (1, 1))
        url = f'/system/?view=chats&user={self.user.pk}'
        history = self.client.get(url)
        self.assertEqual(list(history.context['chats']), [own])
        trash = self.client.get(url + '&trash=1')
        self.assertEqual(list(trash.context['chats']), [trashed])
        self.assertNotContains(history, other.title)
        self.assertContains(history, f'user={self.user.pk}&amp;trash=1')
        response = self.client.post(url, {'action': 'trash', 'chat_id': str(other.pk)})
        self.assertEqual(response.status_code, 404)
        response = self.client.post(url, {'action': 'trash', 'chat_id': str(own.pk)})
        self.assertEqual(response.url, url + '&trash=0')
        response = self.client.post(url + '&trash=1', {'action': 'restore', 'chat_id': str(trashed.pk)})
        self.assertEqual(response.url, url + '&trash=1')
        self.assertEqual(self.client.get('/system/?view=chats&user=invalid').status_code, 404)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get('/api/conversations/?trash=1').json()['conversations'], [])

    def test_account_picker_hides_conversations_until_user_is_selected(self):
        from postal.models import Conversation
        Conversation.objects.create(user=self.user, title='Contenido privado del chat')
        self.client.force_login(self.admin)
        response = self.client.get('/system/?view=chats')
        self.assertContains(response, 'Seleccionar usuario')
        self.assertContains(response, 'Ver resumen')
        self.assertNotContains(response, 'Contenido privado del chat')
        self.assertNotContains(response, 'aria-label="Conversaciones de la cuenta"')

    def test_selected_account_dashboard_has_historical_usage_without_join_duplication(self):
        from postal.models import AIUsage, Conversation
        Conversation.objects.create(user=self.user, title='Uno')
        Conversation.objects.create(user=self.user, title='Dos', deleted_at=timezone.now())
        for prompt, completion in [(100, 20), (100, 20)]:
            row = AIUsage.objects.create(user=self.user, provider='Groq', model='qa', stage='planner',
                prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion)
            AIUsage.objects.filter(pk=row.pk).update(created_at=timezone.now() - timedelta(days=90))
        AIUsage.objects.create(user=self.other, provider='Groq', model='qa', stage='planner', total_tokens=999)
        self.client.force_login(self.admin)
        response = self.client.get(f'/system/?view=chats&user={self.user.pk}')
        self.assertEqual(response.context['chat_usage']['tokens'], 240)
        self.assertEqual(response.context['chat_usage']['prompt'], 200)
        self.assertEqual(response.context['chat_usage']['completion'], 40)
        account = response.context['chat_account']
        self.assertEqual((account.history_count, account.trash_count), (1, 1))
        self.assertEqual(account.token_total, 240)
        self.assertContains(response, 'Resumen de la cuenta')
        filtered = self.client.get(f'/system/?view=chats&user={self.user.pk}&trash=1&q=Noexiste')
        self.assertEqual(filtered.context['chat_usage']['tokens'], 240)

    def test_usage_preserves_unknown_values_and_real_zero(self):
        from postal.models import AIUsage
        self.client.force_login(self.admin)
        empty = self.client.get(f'/system/?view=chats&user={self.user.pk}')
        self.assertIsNone(empty.context['chat_usage']['tokens'])
        self.assertContains(empty, 'Sin consumo registrado')
        for amount in (None, 0):
            AIUsage.objects.all().delete()
            AIUsage.objects.create(user=self.user, provider='Groq', model='qa', stage='planner', total_tokens=amount)
            response = self.client.get(f'/system/?view=chats&user={self.user.pk}')
            self.assertEqual(response.context['chat_usage']['tokens'], amount)
            self.assertEqual(response.context['chat_usage']['unreported'], 1 if amount is None else 0)

    def test_admin_can_restore_other_users_chat(self):
        self.save_chat()
        self.client.post(f'/api/conversations/{self.chat_id}/trash/', {}, content_type='application/json')
        self.client.force_login(self.admin)
        response = self.client.post('/system/', {'action': 'restore', 'chat_id': str(self.chat_id)})
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(f'/api/conversations/{self.chat_id}/').status_code, 200)

    def test_custom_skill_is_managed_and_used_by_agent(self):
        from postal.models import AssistantSkill
        self.client.force_login(self.admin)
        response = self.client.post('/system/', {'action': 'skill_save', 'skill-name': 'Respuesta breve',
            'skill-instructions': 'Prioriza un resumen breve.', 'skill-stage': 'planner', 'skill-enabled': 'on'})
        self.assertEqual(response.status_code, 302)
        skill = AssistantSkill.objects.get(name='Respuesta breve')
        self.assertTrue(skill.enabled)
        response = self.client.post('/system/', {'action': 'skill_save', 'skill_id': skill.pk,
            'skill-name': skill.name, 'skill-instructions': 'Resume.', 'skill-stage': 'analyst'})
        self.assertEqual(response.status_code, 302)
        skill.refresh_from_db()
        self.assertFalse(skill.enabled)
        self.assertEqual(skill.stage, 'analyst')

    @override_settings(JOBS_EAGER=True, DATA_MODE='demo', AI_PROVIDER='groq', GROQ_API_KEY='test-key')
    def test_linked_result_survives_login_and_is_blocked_in_trash(self):
        self.save_chat()
        response = self.client.post('/api/chat/', {'question': 'Describe los campos de sucursales',
            'chat_id': str(self.chat_id)}, content_type='application/json')
        self.assertEqual(response.status_code, 202)
        job_id = response.json()['id']
        self.client.logout()
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(f'/api/results/{job_id}/').status_code, 200)
        self.client.post(f'/api/conversations/{self.chat_id}/trash/', {}, content_type='application/json')
        self.assertEqual(self.client.get(f'/api/results/{job_id}/').status_code, 404)
        self.client.post(f'/api/conversations/{self.chat_id}/restore/', {}, content_type='application/json')
        self.assertEqual(self.client.get(f'/api/results/{job_id}/').status_code, 200)

    def test_user_cannot_restore_others_chat(self):
        self.save_chat()
        self.client.post(f'/api/conversations/{self.chat_id}/trash/', {}, content_type='application/json')
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(f'/api/conversations/{self.chat_id}/restore/', {}, content_type='application/json').status_code, 404)

    def test_admin_transcript_is_protected_and_escapes_messages(self):
        self.save_chat(messages=[{'kind': 'question', 'text': '<script>unsafe()</script>'}])
        url = f'/system/chats/{self.chat_id}/'
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.get(url)
        self.assertContains(response, '&lt;script&gt;unsafe()&lt;/script&gt;')
        self.assertNotContains(response, '<script>unsafe()</script>')

    def test_large_chat_snapshot_and_small_query_body_limit(self):
        messages = [{'kind': 'question', 'text': 'a' * 3000} for _ in range(30)]
        self.assertEqual(self.save_chat(messages=messages).status_code, 200)
        self.assertEqual(len(self.client.get(f'/api/conversations/{self.chat_id}/').json()['messages']), 30)
        response = self.client.post('/api/chat/', {'question': 'a' * 70000}, content_type='application/json')
        self.assertEqual(response.status_code, 413)

    def test_settings_form_rejects_invalid_network_values_without_saving(self):
        from postal.system_forms import SystemConfigForm
        from postal.system_config import configuration, overrides, SECRET_FIELDS
        self.client.force_login(self.admin)
        fields = {name: val for name, val in configuration().items() if name not in SECRET_FIELDS}
        response = self.client.post('/system/', {**fields, 'action': 'settings', 'AI_CONNECT_TIMEOUT': -1,
                                               'NVIDIA_API_KEY': 'must-not-appear'})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'must-not-appear')
        self.assertEqual(overrides(), {})

    def test_csrf_and_anonymous_access(self):
        from django.test import Client
        anonymous = Client()
        self.assertEqual(anonymous.get('/api/conversations/').status_code, 401)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.admin)
        self.assertEqual(protected.post('/system/', {'action': 'cleanup'}).status_code, 403)

    def test_usage_includes_truncated_attempt_and_actual_provider_model(self):
        import httpx
        from postal.ai import _call_json
        from postal.models import AIUsage
        from postal.system_config import save_config, usage_context
        save_config({'AI_PROVIDER': 'groq', 'GROQ_API_KEY': 'fake-key', 'AI_MAX_TOKENS': 512})
        requests = []
        def reply(request):
            requests.append(request)
            return httpx.Response(200, json={'choices': [{'finish_reason': 'length' if len(requests) == 1 else 'stop',
                'message': {'content': '{"ok":true}'}}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 4, 'total_tokens': 14}})
        real_client = httpx.Client
        token = usage_context.set((self.user.pk, uuid.uuid4()))
        try:
            with patch('postal.ai.httpx.Client', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(reply), **kw)):
                self.assertTrue(_call_json({'messages': []})['ok'])
        finally:
            usage_context.reset(token)
        self.assertEqual(AIUsage.objects.count(), 2)
        self.assertEqual(sum(AIUsage.objects.values_list('total_tokens', flat=True)), 28)

    @override_settings(DATA_MODE='demo', AI_PROVIDER='groq', GROQ_API_KEY='fake-key')
    def test_custom_skills_reach_only_the_selected_agent(self):
        import httpx
        import json
        from postal.models import AssistantSkill, QueryJob
        AssistantSkill.objects.create(name='Solo planificador', stage='planner', enabled=True,
                                      instructions='PREFERENCIA_PLANNER_QA')
        requests = []
        def reply(request):
            sent = json.loads(request.content)
            requests.append(sent)
            system = sent['messages'][0]['content']
            content = {'sql': 'SELECT COUNT(*) AS cantidad FROM assistant.paquetes_ems', 'title': 'EMS'} if 'planificador SQL' in system else {
                'paragraphs': [{'kind': 'value', 'references': [{'panel': 0, 'row': 0, 'column': 'cantidad'}]}]}
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(content)}}]})
        real_client = httpx.Client
        with patch('postal.ai.httpx.Client', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(reply), **kw)):
            response = self.client.post('/api/chat/', {'question': 'Cuenta los envíos EMS'}, content_type='application/json')
        self.assertEqual(response.status_code, 202)
        self.assertEqual(QueryJob.objects.get(pk=response.json()['id']).status, 'ok')
        planners = [sent for sent in requests if 'planificador SQL' in sent['messages'][0]['content']]
        analysts = [sent for sent in requests if 'analista postal' in sent['messages'][0]['content']]
        self.assertTrue(planners)
        self.assertTrue(analysts)
        self.assertIn('PREFERENCIA_PLANNER_QA', json.dumps(planners))
        self.assertNotIn('PREFERENCIA_PLANNER_QA', json.dumps(analysts))
