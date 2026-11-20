from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings

from .api_client import ApiTestCase

from postal.data import get_source
from postal.models import QueryJob


@override_settings(DATA_MODE='demo', JOBS_EAGER=True, GROQ_API_KEY='', OPENROUTER_API_KEY='')
class PackageSampleTests(ApiTestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        settings = override_settings(RESULT_DIR=Path(folder.name))
        settings.enable()
        self.addCleanup(settings.disable)
        self.client.force_login(get_user_model().objects.create_user('sample-audit'))

    def ask(self, question, **context):
        response = self.client.post('/api/chat/', {'question': question, **context}, content_type='application/json')
        self.assertEqual(response.status_code, 202)
        return self.client.get(f"/api/results/{response.json()['id']}/").json()

    def assert_real_package(self, result):
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(result['row_count'], 1)
        row = result['rows'][0]
        from postal.operations import SERVICES
        table = SERVICES[row['servicio']][0]
        with get_source().stream(f'SELECT codigo FROM assistant.{table} WHERE codigo = %s', [row['codigo']]) as stream:
            self.assertTrue(list(stream.rows))

    def test_direct_request_returns_existing_code_without_provider_or_filters(self):
        with patch('postal.jobs.plan_question', side_effect=AssertionError('Unexpected provider')):
            self.assert_real_package(self.ask('dame un codigo de paquete'))

    def test_random_reply_completes_legacy_clarification(self):
        from postal.context import advance_state
        from postal.views import session_fingerprint
        question, clarification = 'dame un codigo de paquete', 'Por favor indique el servicio y algún criterio'
        previous = QueryJob.objects.create(user=get_user_model().objects.get(username='sample-audit'),
            session_hash=session_fingerprint(self.client.session.session_key), kind='chat', status='error',
            question=question, error={'code': 'clarification', 'message': clarification},
            context_state=advance_state({}, question, clarification))
        with patch('postal.jobs.plan_question', side_effect=AssertionError('Unexpected provider')):
            self.assert_real_package(self.ask('aleatorio', history_ids=[str(previous.id)]))

    def test_explicit_service_is_respected(self):
        with patch('postal.jobs.plan_question', side_effect=AssertionError('Unexpected provider')):
            result = self.ask('Dame un código de paquete EMS aleatorio.')
        self.assert_real_package(result)
        self.assertEqual(result['rows'][0]['servicio'], 'EMS')

    def test_repeated_random_followups_keep_the_package_request(self):
        with patch('postal.jobs.plan_question', side_effect=AssertionError('Unexpected provider')):
            first = self.ask('Dame un código de paquete.')
            second = self.ask('aleatorio', history_ids=[first['id']])
            third = self.ask('aleatorio', history_ids=[second['id']])
        self.assert_real_package(second)
        self.assert_real_package(third)

    def test_random_alone_without_reference_stays_ambiguous(self):
        from postal.ai import PlanningError
        with patch('postal.jobs.plan_question', side_effect=PlanningError('clarification', '¿Qué necesitas?')) as planner:
            result = self.ask('aleatorio')
        self.assertEqual(result['error']['code'], 'clarification')
        planner.assert_called_once()

    def test_filters_or_an_existing_identifier_are_not_replaced_by_a_random_package(self):
        from postal.ai import PlanningError
        for question in ('Dame un código de paquete para La Paz.',
                         'Dame el código del paquete ZZ000000000ZZ.',
                         'Dame un código de paquete EMS creado en septiembre de 2026.'):
            with self.subTest(question=question), patch('postal.jobs.plan_question',
                    side_effect=PlanningError('clarification', 'Consulta específica')) as planner:
                self.ask(question)
                planner.assert_called_once()

    def test_empty_sources_do_not_claim_that_a_code_was_selected(self):
        original = Path.read_text
        def read(path, *args, **kwargs):
            return '{}' if path.name == 'demo.json' else original(path, *args, **kwargs)
        with patch('postal.data.Path.read_text', autospec=True, side_effect=read), \
             patch('postal.jobs.plan_question', side_effect=AssertionError('Unexpected provider')):
            result = self.ask('Dame un código de paquete aleatorio.')
        self.assertIn(result['status'], ('no_matches', 'empty_table'))
        self.assertEqual(result['rows'], [])
        self.assertIn('No se encontraron', result['answer'])
