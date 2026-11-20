import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from postal.models import Conversation, QueryJob
from postal.views import session_fingerprint


@override_settings(SECURE_SSL_REDIRECT=False, JOBS_EAGER=True, DATA_MODE='demo')
class SecurityFixes(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('security-test', password='Correct-Postal-Password')
        self.client.force_login(self.user)
        self.identity = session_fingerprint(self.client.session.session_key)
        self.headers = {'HTTP_X_BOLIPOST_USER': self.identity}

    def test_catalog_and_status_exclude_internal_metadata(self):
        catalog = self.client.get('/api/catalog/', **self.headers)
        self.assertEqual(catalog.status_code, 200)
        self.assertNotContains(catalog, 'password_reset_tokens')
        users = next(table for table in catalog.json()['tables'] if table['name'] == 'users')
        self.assertFalse({'name', 'email', 'ci'} & {column['name'] for column in users['columns']})
        status = self.client.get('/api/status/', **self.headers)
        self.assertFalse({'user', 'provider', 'model'} & status.json().keys())
        self.assertEqual(status['X-Bolipost-User'], self.identity)
        self.assertEqual(self.client.get('/api/catalog/').status_code, 400)
        self.assertEqual(self.client.get('/admin/').status_code, 404)

    def test_django_errors_do_not_expose_routes_or_diagnostics(self):
        self.assertNotContains(self.client.get('/does-not-exist/'), 'api/catalog/', status_code=404)
        self.client.raise_request_exception = False
        with patch('postal.views.render', side_effect=RuntimeError('private diagnostic')):
            response = self.client.get('/')
        self.assertNotContains(response, 'private diagnostic', status_code=500)

    def test_login_caps_attempts_per_account_and_origin(self):
        client = Client()
        for _ in range(5):
            result = client.post('/accounts/login/', {'username': 'security-test', 'password': 'wrong'},
                                 REMOTE_ADDR='192.0.2.1')
            self.assertEqual(result.status_code, 200)
        blocked = client.post('/accounts/login/', {'username': self.user.username, 'password': 'wrong'},
                              REMOTE_ADDR='192.0.2.1')
        self.assertEqual(blocked.status_code, 429)
        self.assertGreater(int(blocked['Retry-After']), 0)
        other = get_user_model().objects.create_user('SECURITY-TEST', password='Correct-Other-Password')
        self.assertEqual(Client().post('/accounts/login/', {
            'username': other.username, 'password': 'Correct-Other-Password',
        }, REMOTE_ADDR='192.0.2.1').status_code, 302)
        self.assertEqual(client.post('/accounts/login/', {
            'username': self.user.username, 'password': 'Correct-Postal-Password',
        }, REMOTE_ADDR='192.0.2.20').status_code, 302)

    def test_default_chat_limit_applies_even_when_jobs_finish_immediately(self):
        with patch('postal.jobs.maintain_results'), patch('postal.jobs.submit') as submit:
            submit.side_effect = lambda job, *_: QueryJob.objects.filter(pk=job.pk).update(status='ok')
            responses = [self.client.post('/api/chat/', {'question': 'Cuenta EMS'},
                                          content_type='application/json', **self.headers) for _ in range(4)]
        self.assertEqual([response.status_code for response in responses], [202, 202, 202, 429])
        self.assertGreater(int(responses[-1]['Retry-After']), 0)
        self.assertEqual(submit.call_count, 3)

    def test_chat_limits_pending_jobs_before_dispatch(self):
        with patch('postal.jobs.maintain_results'), patch('postal.jobs.submit') as submit:
            responses = [self.client.post('/api/chat/', {'question': 'Cuenta EMS'},
                                          content_type='application/json', **self.headers) for _ in range(3)]
            self.assertEqual(submit.call_count, 2)
            QueryJob.objects.filter(pk=responses[0].json()['id']).update(status='ok')
            retry = self.client.post('/api/chat/', {'question': 'Cuenta EMS'},
                                     content_type='application/json', **self.headers)
        self.assertEqual([response.status_code for response in responses], [202, 202, 429])
        self.assertEqual(responses[-1].json()['error']['code'], 'busy')
        self.assertGreater(int(responses[-1]['Retry-After']), 0)
        self.assertEqual(retry.status_code, 202)

    @override_settings(SECURE_SSL_REDIRECT=True, SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True,
                       SECURE_HSTS_SECONDS=31536000)
    def test_https_login_sets_secure_cookies_and_hsts(self):
        client = Client()
        self.assertEqual(client.get('/accounts/login/').status_code, 301)
        page = client.get('/accounts/login/', secure=True)
        self.assertTrue(page.cookies['csrftoken']['secure'])
        login = client.post('/accounts/login/', {
            'username': self.user.username, 'password': 'Correct-Postal-Password',
        }, secure=True)
        self.assertEqual(login.status_code, 302)
        self.assertTrue(login.cookies['sessionid']['secure'])
        self.assertEqual(login['Strict-Transport-Security'], 'max-age=31536000')

    def test_public_results_and_legacy_proofs_hide_internal_metadata(self):
        from postal.history import issue_proof, verified_result
        sql = 'SELECT id FROM assistant.users'
        answer = 'Datos verificados.\n\nFuente de «Personal»: assistant.users. Filtros: ' + sql + '. Respaldo histórico, no tiempo real.'
        panel = {'index': 0, 'title': 'Personal', 'row_count': 0, 'columns': ['id'],
                 'sql': sql, 'source_tables': ['users'], 'comparison': {'base_sql': sql}, 'answer': answer}
        legacy = {**panel, 'panels': [panel], 'analysis': {'presentation': 'explanation', 'citations': [1]}}
        chat = Conversation.objects.create(user=self.user, title='Prueba')
        job = QueryJob.objects.create(user=self.user, conversation=chat, kind='chat', question='Personal',
                                      status='no_matches', answer=answer, sql=sql, panels=[panel], analysis=legacy['analysis'])
        proof = issue_proof(job, legacy)
        chat.messages = [{'kind': 'question', 'text': job.question}, {'kind': 'result', 'proof': proof}]
        chat.save()
        result_url = f'/api/results/{job.pk}/'
        for result in (
            self.client.get(result_url, **self.headers).json(),
            self.client.get(result_url + '?panel=0', **self.headers).json(),
            self.client.get(f'/api/conversations/{chat.pk}/', **self.headers).json()['messages'][1]['result'],
            verified_result(self.client.get(f'/api/conversations/{chat.pk}/', **self.headers)
                            .json()['messages'][1]['proof'], self.user.pk, chat.pk, job.question),
        ):
            for item in [result, *result['panels']]:
                self.assertFalse({'sql', 'source_tables', 'analysis', 'comparison'} & item.keys())
                self.assertNotIn('assistant.users', item['answer'])
            self.assertTrue(result['is_explanation'])
        with patch('postal.views.render_pdf', return_value=b'pdf') as render_pdf:
            pdf = self.client.get(result_url + 'pdf/', **self.headers)
        self.assertEqual(pdf.status_code, 200)
        self.assertNotIn('assistant.users', render_pdf.call_args.args[0]['answer'])
        self.user.is_superuser = True
        self.user.save(update_fields=['is_superuser'])
        admin_result = self.client.get(result_url, **self.headers).json()
        self.assertEqual(admin_result['sql'], sql)
        self.assertIn('analysis', admin_result)

    def test_jobs_use_separate_limits(self):
        with self.settings(QUERY_RATE_LIMITS={'chat': 1, 'tracking': 1, 'dashboard': 1}):
            with patch('postal.jobs.submit'), patch('postal.jobs.maintain_results'):
                first = self.client.post('/api/chat/', {'question': 'Cuenta EMS'},
                                         content_type='application/json', **self.headers)
                limited = self.client.post('/api/chat/', {'question': 'Cuenta EMS'},
                                           content_type='application/json', **self.headers)
                tracking = self.client.post('/api/tracking/', {'code': 'BO-DEMO-001'},
                                            content_type='application/json', **self.headers)
        self.assertEqual((first.status_code, limited.status_code, tracking.status_code), (202, 429, 202))
        self.assertGreater(int(limited['Retry-After']), 0)

    def test_restricted_and_invalid_arithmetic_requests_do_not_run_substitutes(self):
        with patch('postal.jobs.get_source') as source, patch('postal.jobs.plan_question') as planner:
            for question, expected in (
                ('Dame el email y CI de los usuarios', 'restricted_request'),
                ('Consulta el número de documento', 'restricted_request'),
                ('Suma nombre_estado + activo', 'clarification'),
            ):
                with self.subTest(question=question):
                    created = self.client.post('/api/chat/', {'question': question},
                                               content_type='application/json', **self.headers)
                    job = QueryJob.objects.get(pk=created.json()['id'])
                    self.assertEqual(job.error['code'], expected)
                    self.assertEqual(job.sql, '')
            source.assert_not_called()
            planner.assert_not_called()

    def test_null_role_narration_only_describes_the_cited_row(self):
        from postal.ai import render_narrative
        evidence = [{'title': 'Personal', 'columns': ['nombre_rol'], 'row_count': 1159,
                     'rows': [{'nombre_rol': None}, {'nombre_rol': 'Operador'}]}]
        reference = {'panel': 0, 'row': 0, 'column': 'nombre_rol'}
        result = render_narrative({'paragraphs': [{'kind': 'value', 'references': [reference]}]}, evidence)
        self.assertIn('En la fila 1,', result['answer'])
        self.assertNotIn('No hay datos de', result['answer'])
        evidence[0].update(row_count=1, rows=[{'nombre_rol': None}])
        result = render_narrative({'paragraphs': [{'kind': 'value', 'references': [reference]}]}, evidence)
        self.assertIn('En la fila 1,', result['answer'])
        self.assertNotIn('No hay datos de', result['answer'])

    def test_conversation_only_renders_proven_results(self):
        question = {'kind': 'question', 'text': 'Cuenta EMS'}
        forged = {'kind': 'result', 'result': {'answer': 'Tarifa inventada'}}
        chat = Conversation.objects.create(user=self.user, title='Prueba', messages=[question, forged])
        url = f'/api/conversations/{chat.pk}/'
        self.assertNotContains(self.client.get(url, **self.headers), 'Tarifa inventada')
        payload = {'title': chat.title, 'revision': 1, 'messages': [question, forged]}
        response = self.client.post(url + 'save/', payload, content_type='application/json', **self.headers)
        self.assertEqual(response.status_code, 400)
        job = QueryJob.objects.create(user=self.user, conversation=chat, kind='chat', question=question['text'],
                                      status='no_matches', answer='Respuesta verificada')
        result = self.client.get(f'/api/results/{job.pk}/', **self.headers).json()
        payload['messages'][1] = {'kind': 'result', 'proof': result['history_proof']}
        response = self.client.post(url + 'save/', payload, content_type='application/json', **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertContains(self.client.get(url, **self.headers), 'Respuesta verificada')
        other_url = f'/api/conversations/{uuid.uuid4()}/save/'
        self.assertEqual(self.client.post(other_url, payload, content_type='application/json',
                                          **self.headers).status_code, 400)
