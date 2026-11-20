from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings

from .api_client import ApiTestCase

from postal.models import QueryJob
from postal.ai import PlanningError


@override_settings(DATA_MODE='demo', JOBS_EAGER=True, GROQ_API_KEY='', OPENROUTER_API_KEY='')
class LocationCountTests(ApiTestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        config = override_settings(RESULT_DIR=Path(folder.name))
        config.enable()
        self.addCleanup(config.disable)
        self.client.force_login(get_user_model().objects.create_user('location-counts'))

    def ask(self, question, **context):
        response = self.client.post('/api/chat/', {'question': question, **context}, content_type='application/json')
        self.assertEqual(response.status_code, 202)
        return self.client.get(f"/api/results/{response.json()['id']}/").json()

    def test_count_and_comparison_work_without_provider_and_keep_zero_services(self):
        with patch('postal.jobs.plan_question', side_effect=PlanningError('provider_busy', 'Cuota agotada')), \
                patch('postal.jobs.compose_response', side_effect=AssertionError('Unexpected narration')):
            first = self.ask('hola quiero que me digas cuantos paquetes tengo en tarija')
            self.assertEqual(first['status'], 'ok', first.get('error'))
            self.assertEqual(len(first['panels']), 5)
            compared = self.ask('puedes comparar la carga con oruro', history_ids=[first['id']])
        self.assertEqual(compared['status'], 'ok', compared.get('error'))
        self.assertEqual(len(compared['panels']), 5)
        for panel in compared['panels']:
            self.assertEqual(panel['columns'], ['tarija', 'oruro'])
            self.assertEqual(len(panel['rows']), 1)
        self.assertNotIn('warning', compared)
        self.assertIn('destino', compared['answer'].lower())
        contract = next(p for p in compared['panels'] if 'CONTRATO' in p['title'])
        stored_panel = QueryJob.objects.get(pk=compared['id']).panels[contract['index']]
        self.assertNotIn('p.origen', stored_panel['sql'])

    def test_explicit_service_is_preserved_on_repeated_comparisons(self):
        with patch('postal.jobs.plan_question', side_effect=PlanningError('provider_busy', 'Cuota agotada')):
            first = self.ask('Cuántos paquetes EMS tengo en Tarija?')
            second = self.ask('Compara la carga con Oruro', history_ids=[first['id']])
            third = self.ask('Compara la carga con Potosí', history_ids=[second['id']])
        self.assertEqual(third['status'], 'ok', third.get('error'))
        self.assertEqual(len(third['panels']), 1)
        self.assertEqual(third['panels'][0]['columns'], ['tarija', 'potosi'])

    def test_contract_origin_is_not_counted_as_destination(self):
        with patch('postal.jobs.plan_question', side_effect=PlanningError('provider_busy', 'Cuota agotada')):
            first = self.ask('Cuántos paquetes contrato tengo en La Paz?')
            compared = self.ask('Compara la carga con Cochabamba', history_ids=[first['id']])
        self.assertEqual(compared['status'], 'ok', compared.get('error'))
        self.assertEqual(compared['rows'], [{'la_paz': 0, 'cochabamba': 4}])

    def test_model_gets_comparison_before_any_local_fallback(self):
        reply = {'sql': 'SELECT COUNT(*) AS total FROM assistant.paquetes_ems p',
                 'comparison': {'column': 'p.ciudad', 'locations': ['Tarija', 'Oruro']}}
        with override_settings(GROQ_API_KEY='model-test'), \
                patch('postal.ai._call_json', return_value=reply) as model, \
                patch('postal.jobs.location_count_report', side_effect=AssertionError('Unexpected local route')), \
                patch('postal.jobs.compose_response', side_effect=PlanningError('provider_busy', 'Quota')):
            result = self.ask('Compara los paquetes EMS con destino a Tarija y Oruro')
        self.assertEqual(result['status'], 'ok', result.get('error'))
        model.assert_called_once()
        saved = QueryJob.objects.get(id=result['id'])
        from postal.jobs import _verified_context
        from postal.context import compress_context
        context = compress_context('Compara esa carga con Potosí', _verified_context(saved, 'Compara esa carga con Potosí'))
        self.assertEqual(context['comparison']['locations'], ['Tarija', 'Oruro'])
        self.assertIn('base_sql', context['comparison'])
        self.assertNotIn('sql', context)

    def test_comparison_does_not_drop_constraints_from_a_legacy_result(self):
        from types import SimpleNamespace
        from postal.operations import location_count_report
        from postal.policy import catalog
        for sql in (
            "SELECT COUNT(*) AS total FROM assistant.paquetes_ems WHERE ciudad = 'Tarija' AND created_at >= '2026-09-01'",
            "SELECT COUNT(*) AS total FROM assistant.paquetes_ems WHERE ciudad = 'Tarija' AND origen = 'La Paz'",
            "SELECT COUNT(*) AS total FROM (SELECT id, ciudad FROM assistant.paquetes_ems WHERE user_id = 1) p WHERE ciudad = 'Tarija'",
            "SELECT COUNT(DISTINCT codigo) AS total FROM assistant.paquetes_ems WHERE ciudad = 'Tarija'",
            "SELECT COUNT(CASE WHEN user_id = 1 THEN id END) AS total FROM assistant.paquetes_ems WHERE ciudad = 'Tarija'",
        ):
            previous = SimpleNamespace(question='Cuántos paquetes EMS tengo en Tarija', filters={},
                source_tables=['paquetes_ems'], panels=[], sql=sql)
            with self.subTest(sql=sql):
                self.assertIsNone(location_count_report('Compara la carga con Oruro', catalog(), previous))

    def test_filtered_or_personal_requests_are_not_replaced_by_unfiltered_counts(self):
        from postal.ai import PlanningError
        for question in ('Cuántos paquetes tengo en Tarija en septiembre de 2026',
                         'Cuántos paquetes tengo en Tarija sin entregar',
                         'Cuántos paquetes tengo en Tarija y Oruro',
                         'Cuántos paquetes tengo exclusivamente de mi usuario en Tarija'):
            with self.subTest(question=question), patch('postal.jobs.plan_question',
                    side_effect=PlanningError('clarification', 'Consulta específica')) as planner:
                self.ask(question)
                planner.assert_called_once()

    def test_existing_tarija_result_can_be_compared_and_contract_is_recomputed_by_destination(self):
        from postal.views import session_fingerprint
        previous = QueryJob.objects.create(user=get_user_model().objects.get(username='location-counts'),
            session_hash=session_fingerprint(self.client.session.session_key), kind='chat', status='ok',
            question='hola quiero que me digas cuantos paquetes tengo en tarija',
            source_tables=['paquetes_ems', 'paquetes_contrato'],
            sql="SELECT COUNT(*) AS total FROM assistant.paquetes_ems WHERE ciudad = 'Tarija'")
        with patch('postal.jobs.plan_question', side_effect=PlanningError('provider_busy', 'Cuota agotada')):
            compared = self.ask('puedes comparar la carga con oruro', previous_id=str(previous.id))
        self.assertEqual(compared['status'], 'ok', compared.get('error'))
        self.assertEqual(len(compared['panels']), 2)
        self.assertNotIn('origen', QueryJob.objects.get(pk=compared['id']).panels[1]['sql'])
