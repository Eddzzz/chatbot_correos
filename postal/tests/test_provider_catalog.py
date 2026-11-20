import tempfile
from pathlib import Path
from unittest.mock import patch

import httpx
from django.contrib.auth import get_user_model
from django.test import override_settings

from .api_client import ApiTestCase

from postal.models import AIProvider, ProviderModel, ProviderKey, ProviderSelection, SystemAudit


class ProviderCatalogTests(ApiTestCase):
    def test_reorder_promotes_first_model_and_rejects_stale_or_duplicate_lists(self):
        from postal.provider_catalog import active_connection
        provider, model, key = self.connection()
        self.client.post('/system/?view=models', {'action': 'catalog_backup_save', 'model': model.pk, 'priority': 2})
        primary = ProviderSelection.objects.get(pk=1).active_model_id
        data = {'action': 'catalog_reorder', 'model_ids': [str(model.pk), str(primary)]}
        response = self.client.post('/system/?view=models', data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.assertEqual(ProviderSelection.objects.get(pk=1).active_model_id, model.pk)
        self.assertEqual([item['config'][3] for item in active_connection()['configs']], [model.identifier, 'openai/gpt-oss-120b'])
        for ids in ([str(model.pk)], [str(model.pk), str(model.pk)], ['bad', str(primary)]):
            response = self.client.post('/system/?view=models', {'action': 'catalog_reorder', 'model_ids': ids})
            self.assertIn(response.status_code, (400, 409))
            self.assertEqual(ProviderSelection.objects.get(pk=1).active_model_id, model.pk)

    def test_add_backup_directly_and_reject_unconfigured_model(self):
        provider, model, key = self.connection()
        response = self.client.get('/system/?view=models&editor=backup')
        self.assertContains(response, 'Agregar respaldo')
        response = self.client.post('/system/?view=models', {'action': 'catalog_backup_save',
            'model': model.pk, 'priority': 3})
        self.assertEqual(response.status_code, 302)
        model.refresh_from_db()
        self.assertTrue(model.fallback_enabled)
        self.assertEqual(model.priority, 3)
        unready = ProviderModel.objects.create(provider=AIProvider.objects.create(name='Sin claves',
            endpoint='https://example.org/chat'), name='No listo', identifier='no-listo')
        response = self.client.post('/system/?view=models', {'action': 'catalog_backup_save',
            'model': unready.pk, 'priority': 4})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['catalog_form'].errors)
        unready.refresh_from_db()
        self.assertFalse(unready.fallback_enabled)

    def test_ordered_models_fallback_across_providers_only_on_quota(self):
        from postal.ai import _call_json
        from postal.provider_catalog import active_connection
        provider, model, key = self.connection()
        second = ProviderModel.objects.create(provider=provider, name='Segundo', identifier='modelo-2', fallback_enabled=True, priority=2)
        third_provider = AIProvider.objects.create(name='Tercer servicio', endpoint='https://third.example.com/v1/chat/completions')
        ProviderKey.objects.create(provider=third_provider, name='Clave', secret='third-secret')
        third = ProviderModel.objects.create(provider=third_provider, name='Tercero', identifier='modelo-3', fallback_enabled=True, priority=3)
        self.client.post('/system/?view=models', {'action': 'catalog_activate', 'object_id': model.pk})
        configs = active_connection()['configs']
        self.assertEqual([item['config'][3] for item in configs], ['modelo-1', 'modelo-2', 'modelo-3'])
        sent = []
        def reply(request):
            import json
            identifier = json.loads(request.content)['model']
            sent.append(identifier)
            if identifier != 'modelo-3':
                return httpx.Response(429, headers={'Retry-After': '9'})
            return httpx.Response(200, json={'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}]})
        real_client = httpx.Client
        with patch('postal.ai.httpx.Client', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(reply), **kw)):
            self.assertEqual(_call_json({'messages': []}), {'ok': True})
        self.assertEqual(sent, ['modelo-1', 'modelo-2', 'modelo-3'])
        second.enabled = False
        second.save()
        self.assertEqual([item['config'][3] for item in active_connection()['configs']], ['modelo-1', 'modelo-3'])

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        override = override_settings(SYSTEM_CONFIG_PATH=Path(folder.name) / 'settings.json',
            RESULT_DIR=Path(folder.name) / 'results', AI_PROVIDER='groq', GROQ_API_KEY='legacy-secret',
            GROQ_BACKUP_API_KEY='', OPENROUTER_API_KEY='', NVIDIA_API_KEY='', CLOUDFLARE_API_TOKEN='')
        override.enable()
        self.addCleanup(override.disable)
        self.admin = get_user_model().objects.create_superuser('gestor', password='qa-password')
        self.client.force_login(self.admin)

    def connection(self):
        self.client.get('/system/?view=models')
        provider = AIProvider.objects.create(name='Servicio nuevo', endpoint='https://example.com/v1/chat/completions')
        model = ProviderModel.objects.create(provider=provider, name='Modelo rápido', identifier='modelo-1')
        key = ProviderKey.objects.create(provider=provider, name='Principal', secret='new-secret')
        return provider, model, key

    def test_catalog_imports_existing_configuration_once_and_preserves_connection(self):
        from postal.ai import provider_config
        self.client.get('/system/?view=models')
        self.assertEqual(AIProvider.objects.count(), 4)
        self.assertTrue(ProviderKey.objects.filter(secret='legacy-secret').exists())
        self.assertIsNotNone(ProviderSelection.objects.get(pk=1).active_model_id)
        self.assertEqual(provider_config()[1], 'legacy-secret')
        self.client.get('/system/?view=models')
        self.assertEqual(AIProvider.objects.count(), 4)

    def test_add_provider_with_optional_initial_key(self):
        url = '/system/?view=models'
        response = self.client.get(url + '&editor=provider')
        self.assertContains(response, 'name="initial_secret"')
        self.assertNotContains(response, 'name="protocol"')
        active_id = ProviderSelection.objects.get(pk=1).active_model_id
        data = {'action': 'catalog_provider_save', 'name': 'Nuevo proveedor',
                'endpoint': 'https://example.com/v1/chat/completions',
                'enabled': 'on', 'initial_secret': 'qa-initial-secret'}

        response = self.client.post(url, {**data, 'initial_secret': 'qa-invalid\nsecret'})
        self.assertIn('initial_secret', response.context['catalog_form'].errors)
        self.assertFalse(AIProvider.objects.filter(name=data['name']).exists())

        response = self.client.post(url, {**data, 'endpoint': 'https://example.com/chat?key=invalid'})
        self.assertNotContains(response, data['initial_secret'])
        self.assertFalse(AIProvider.objects.filter(name=data['name']).exists())

        response = self.client.post(url, data, follow=True)
        provider = AIProvider.objects.get(name=data['name'])
        self.assertRedirects(response, f'{url}&selected_provider={provider.pk}')
        self.assertContains(response, 'Principal')
        self.assertNotContains(response, data['initial_secret'])
        key = provider.keys.get()
        self.assertEqual((key.name, key.priority, key.enabled, key.secret), ('Principal', 1, True, data['initial_secret']))
        entry = SystemAudit.objects.get(action='catalog_provider_save', detail=provider.name)
        self.assertNotIn(data['initial_secret'], str(entry.metadata))
        self.assertEqual(ProviderSelection.objects.get(pk=1).active_model_id, active_id)

        response = self.client.get(f'{url}&editor=provider&object_id={provider.pk}')
        self.assertNotContains(response, 'name="initial_secret"')
        self.assertNotContains(response, 'name="protocol"')
        self.assertNotContains(response, key.secret)
        self.client.post(url, {**data, 'object_id': provider.pk, 'initial_secret': 'ignored-secret'})
        self.assertEqual(list(provider.keys.values_list('secret', flat=True)), [key.secret])

        self.client.post(url, {**data, 'name': 'Proveedor sin clave', 'initial_secret': ''})
        self.assertFalse(AIProvider.objects.get(name='Proveedor sin clave').keys.exists())

    def test_crud_and_secret_replacement_never_return_credentials(self):
        provider, model, key = self.connection()
        response = self.client.post('/system/?view=models', {'action': 'catalog_key_save',
            'provider_id': provider.pk, 'object_id': key.pk, 'name': 'Rotada', 'secret': '', 'enabled': 'on', 'priority': 2})
        self.assertEqual(response.status_code, 302)
        key.refresh_from_db()
        self.assertEqual(key.secret, 'new-secret')
        response = self.client.get(f'/system/?view=models&editor=key&object_id={key.pk}&provider_id={provider.pk}')
        self.assertNotContains(response, 'new-secret')
        self.assertNotContains(response, 'legacy-secret')
        response = self.client.post('/system/?view=models', {'action': 'catalog_key_save',
            'provider_id': provider.pk, 'object_id': key.pk, 'name': 'Rotada', 'secret': 'replacement-secret',
            'enabled': 'on', 'priority': 2})
        self.assertEqual(response.status_code, 302)
        key.refresh_from_db()
        self.assertEqual(key.secret, 'replacement-secret')

    def test_active_connection_drives_ai_requests_and_tries_next_key_on_capacity_error(self):
        from postal.ai import _call_json, provider_config
        provider, model, key = self.connection()
        ProviderKey.objects.create(provider=provider, name='Respaldo', secret='backup-secret', priority=2)
        response = self.client.post('/system/?view=models', {'action': 'catalog_activate', 'object_id': model.pk})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(provider_config(), (provider.name, key.secret, provider.endpoint, model.identifier))
        sent = []
        def reply(request):
            import json
            sent.append((request.url, request.headers['authorization'], json.loads(request.content)))
            if request.headers['authorization'] == 'Bearer new-secret':
                return httpx.Response(429, headers={'Retry-After': '9'})
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}]})
        real_client = httpx.Client
        with patch('postal.ai.httpx.Client', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(reply), **kw)):
            self.assertEqual(_call_json({'messages': []}), {'ok': True})
        self.assertEqual([item[1] for item in sent], ['Bearer new-secret', 'Bearer backup-secret'])
        self.assertEqual(sent[-1][2]['model'], 'modelo-1')

    def test_cannot_activate_incomplete_or_delete_active_connection(self):
        provider, model, key = self.connection()
        original = ProviderSelection.objects.get(pk=1).active_model_id
        key.enabled = False
        key.save()
        self.client.post('/system/?view=models', {'action': 'catalog_activate', 'object_id': model.pk})
        self.assertEqual(ProviderSelection.objects.get(pk=1).active_model_id, original)
        key.enabled = True
        key.save()
        self.client.post('/system/?view=models', {'action': 'catalog_activate', 'object_id': model.pk})
        for kind, obj in [('provider', provider), ('model', model), ('key', key)]:
            self.client.post('/system/?view=models', {'action': 'catalog_delete', 'kind': kind, 'object_id': obj.pk})
            self.assertTrue(type(obj).objects.filter(pk=obj.pk).exists())

    def test_endpoint_validation_and_permissions(self):
        from postal.provider_catalog import ProviderForm
        for endpoint in ('http://example.com/chat', 'https://user:secret@example.com/chat', 'https://example.com/chat?key=secret'):
            form = ProviderForm({'name': 'Nuevo', 'endpoint': endpoint, 'protocol': 'openai', 'enabled': 'on'})
            self.assertFalse(form.is_valid(), endpoint)
        user = get_user_model().objects.create_user('normal')
        self.client.force_login(user)
        self.assertEqual(self.client.post('/system/?view=models', {'action': 'catalog_provider_save'}).status_code, 403)

    def test_provider_format_is_inferred_from_endpoint(self):
        url = '/system/?view=models'
        data = {'action': 'catalog_provider_save', 'name': 'Otro nombre', 'enabled': 'on'}
        router_url = 'https://openrouter.ai/api/v1/chat/completions'
        response = self.client.post(url, {**data, 'endpoint': router_url})
        self.assertEqual(response.status_code, 302)
        provider = AIProvider.objects.get(name=data['name'])
        self.assertEqual(provider.protocol, 'openrouter')

        proxy_url = 'https://openrouter.ai.example.test/v1/chat/completions'
        data.update(object_id=provider.pk, endpoint=proxy_url)
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        provider.refresh_from_db()
        self.assertEqual(provider.protocol, 'openai')

        provider.protocol = 'openrouter'
        provider.save(update_fields=['protocol'])
        response = self.client.post(url, {**data, 'name': 'Proxy existente'})
        self.assertEqual(response.status_code, 302)
        provider.refresh_from_db()
        self.assertEqual(provider.protocol, 'openrouter')

    def test_provider_selection_precedes_details_and_does_not_change_active_model(self):
        from postal.ai import provider_config
        provider, model, key = self.connection()
        active_before = provider_config()
        response = self.client.get('/system/?view=models')
        self.assertIsNone(response.context['catalog_selected_provider'])
        self.assertNotContains(response, model.name)
        response = self.client.get(f'/system/?view=models&selected_provider={provider.pk}')
        self.assertEqual(response.context['catalog_selected_provider'].pk, provider.pk)
        self.assertEqual(len(response.context['catalog_visible_providers']), 1)
        self.assertContains(response, model.name)
        self.assertEqual(provider_config(), active_before)
        for value in ('invalid', '999999'):
            self.assertEqual(self.client.get('/system/?view=models&selected_provider=' + value).status_code, 404)

    def test_last_active_key_cannot_be_disabled_and_unused_provider_can_be_deleted(self):
        provider, model, key = self.connection()
        original = ProviderSelection.objects.get(pk=1).active_model_id
        self.client.post('/system/?view=models', {'action': 'catalog_activate', 'object_id': model.pk})
        response = self.client.post('/system/?view=models', {'action': 'catalog_key_save', 'object_id': key.pk,
            'provider_id': provider.pk, 'name': key.name, 'secret': '', 'priority': 1})
        self.assertEqual(response.status_code, 200)
        key.refresh_from_db()
        self.assertTrue(key.enabled)
        self.client.post('/system/?view=models', {'action': 'catalog_activate', 'object_id': original})
        self.client.post('/system/?view=models', {'action': 'catalog_delete', 'kind': 'provider', 'object_id': provider.pk})
        self.assertFalse(AIProvider.objects.filter(pk=provider.pk).exists())
        self.assertFalse(ProviderKey.objects.filter(pk=key.pk).exists())
        self.assertFalse(ProviderModel.objects.filter(pk=model.pk).exists())

    def test_connection_snapshot_keeps_running_requests_on_the_original_key(self):
        from postal.ai import provider_config
        from postal.provider_catalog import active_connection
        from postal.system_config import _snapshot, configuration
        provider, model, key = self.connection()
        self.client.post('/system/?view=models', {'action': 'catalog_activate', 'object_id': model.pk})
        snapshot = {**configuration(), 'MANAGED_CONNECTION': active_connection()}
        key.secret = 'rotated-secret'
        key.save()
        token = _snapshot.set(snapshot)
        try:
            self.assertEqual(provider_config()[1], 'new-secret')
        finally:
            _snapshot.reset(token)
        self.assertEqual(provider_config()[1], 'rotated-secret')

    def test_auth_errors_do_not_cycle_credentials_and_openrouter_keeps_free_policy(self):
        from postal.ai import _call_json, PlanningError
        provider, model, key = self.connection()
        provider.endpoint = 'https://openrouter.ai/api/v1/chat/completions'
        provider.save()
        ProviderKey.objects.create(provider=provider, name='Otra', secret='other-secret', priority=2)
        self.client.post('/system/?view=models', {'action': 'catalog_activate', 'object_id': model.pk})
        sent = []
        def reply(request):
            import json
            sent.append(json.loads(request.content))
            return httpx.Response(401)
        real_client = httpx.Client
        with patch('postal.ai.httpx.Client', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(reply), **kw)):
            with self.assertRaises(PlanningError) as caught:
                _call_json({'messages': []})
        self.assertEqual(caught.exception.code, 'provider_auth')
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['provider']['max_price'], {'prompt': 0, 'completion': 0})
