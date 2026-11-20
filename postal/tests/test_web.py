import tempfile
from pathlib import Path
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import override_settings

from .api_client import ApiClient as Client, ApiTestCase

@override_settings(JOBS_EAGER=True, DATA_MODE='demo', GROQ_API_KEY='')
class WebBoundaryTests(ApiTestCase):
    def test_clarification_state_survives_using_only_latest_history_id(self):
        from postal.ai import PlanningError
        from postal.models import QueryJob
        first_question = 'Prepara un informe mensual de envíos'
        with patch('postal.jobs.plan_question', side_effect=PlanningError('clarification', '¿Año?')):
            first = self.client.post('/api/chat/', {'question': first_question}, content_type='application/json').json()['id']
        with patch('postal.jobs.plan_question', side_effect=PlanningError('clarification', '¿Servicio?')):
            second = self.client.post('/api/chat/', {'question': '2026', 'previous_id': first}, content_type='application/json').json()['id']
        with patch('postal.jobs.plan_question', side_effect=PlanningError('clarification', '¿Mes?')) as planner:
            self.client.post('/api/chat/', {'question': 'solo EMS', 'previous_id': second}, content_type='application/json')
        state = planner.call_args.args[1]['state']
        self.assertEqual(state['request'], first_question)
        self.assertEqual(state['updates']['year'], '2026')
        self.assertEqual(state['pending_clarification'], '¿Servicio?')
        self.assertEqual(QueryJob.objects.get(pk=second).context_state['updates']['year'], '2026')

    def test_client_cannot_supply_conversation_state(self):
        response = self.client.post('/api/chat/', {'question': 'Cuenta EMS', 'conversation_state': {'request': 'injected'}}, content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_clarification_only_reference_recovers_verified_rows(self):
        from postal.ai import PlanningError
        plan = {'sql': 'SELECT codigo FROM assistant.paquetes_ems ORDER BY id', 'title': 'Listado'}
        with patch('postal.jobs.plan_question', return_value=plan):
            first = self.client.post('/api/chat/', {'question': 'Lista paquetes EMS'}, content_type='application/json').json()['id']
        with patch('postal.jobs.plan_question', side_effect=PlanningError('clarification', '¿Cuál paquete?')):
            second = self.client.post('/api/chat/', {'question': 'Detalles', 'previous_id': first}, content_type='application/json').json()['id']
        with patch('postal.jobs.plan_question', return_value=plan) as planner:
            self.client.post('/api/chat/', {'question': 'El primero', 'previous_id': second}, content_type='application/json')
        context = planner.call_args.args[1]
        self.assertEqual(context['sql'], plan['sql'])
        self.assertEqual(context['preview_first_page'][0]['codigo'], 'BO-DEMO-001')
        self.assertEqual(context['state']['pending_clarification'], '¿Cuál paquete?')

    def test_original_result_can_be_recovered_beyond_recent_turns(self):
        from postal.models import QueryJob
        plan = {'sql': 'SELECT codigo FROM assistant.paquetes_ems ORDER BY id', 'title': 'Listado'}
        previous_id = None
        original_report = {'title': 'Servicios', 'intent': 'report', 'queries': [plan,
            {'sql': 'SELECT codigo FROM assistant.paquetes_certi ORDER BY id', 'title': 'Certificados'}]}
        with patch('postal.jobs.plan_question', side_effect=[original_report, plan, plan, plan, plan]):
            for question in ('Lista paquetes EMS', 'solo EMS', '2025', '2026', 'Solo CERTIFICADO'):
                response = self.client.post('/api/chat/', {'question': question,
                    **({'previous_id': previous_id} if previous_id else {})}, content_type='application/json')
                previous_id = response.json()['id']
        state = QueryJob.objects.get(pk=previous_id).context_state
        self.assertEqual(len(state['recent']), 3)
        self.assertEqual(len(state['results']), 5)
        with patch('postal.jobs.plan_question', return_value=plan) as planner:
            self.client.post('/api/chat/', {'question': 'Vuelve al listado inicial', 'previous_id': previous_id}, content_type='application/json')
        original = planner.call_args.args[1]['historical_result']
        self.assertEqual(original['question'], 'Lista paquetes EMS')
        self.assertEqual(original['preview_first_page'][0]['codigo'], 'BO-DEMO-001')
        self.assertEqual(len(original['report_panels']), 2)
        self.assertIn('paquetes_certi', original['report_panels'][1]['sql'])

    def test_clarification_cannot_resurrect_expired_verified_result(self):
        from datetime import timedelta
        from django.utils import timezone
        from postal.ai import PlanningError
        from postal.models import QueryJob
        plan = {'sql': 'SELECT codigo FROM assistant.paquetes_ems', 'title': 'Listado'}
        with patch('postal.jobs.plan_question', return_value=plan):
            first = self.client.post('/api/chat/', {'question': 'Lista paquetes EMS'}, content_type='application/json').json()['id']
        with patch('postal.jobs.plan_question', side_effect=PlanningError('clarification', '¿Cuál paquete?')):
            second = self.client.post('/api/chat/', {'question': 'Detalles', 'previous_id': first}, content_type='application/json').json()['id']
        QueryJob.objects.filter(pk=first).update(updated_at=timezone.now() - timedelta(hours=25))
        response = self.client.post('/api/chat/', {'question': 'El primero', 'previous_id': second}, content_type='application/json')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error']['code'], 'stale_context')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.override = override_settings(RESULT_DIR=Path(self.tmp.name))
        self.override.enable()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.override.disable)
        self.user = get_user_model().objects.create_user('operador', password='Postal-Prueba-2026')
        self.client.force_login(self.user)

    def test_data_api_requires_login(self):
        response = Client().get('/api/catalog/')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error']['code'], 'authentication_required')

    def test_conversation_url_loads_private_app(self):
        url = '/c/6af35085-8c38-83e9-8439-1db0b09ff1af'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'postal/app.html')
        self.assertContains(response, 'id="conversation-id"')
        self.assertEqual(response['Cache-Control'], 'no-store, private')
        response = Client().get(url)
        self.assertRedirects(response, '/accounts/login/?next=' + url)
        self.assertEqual(self.client.get('/c/not-a-uuid').status_code, 404)

    def test_creation_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post('/api/tracking/', {'code': 'BO-DEMO-001'}, content_type='application/json').status_code, 403)

    def test_bad_json_and_types_rejected(self):
        self.assertEqual(self.client.post('/api/chat/', '{', content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post('/api/tracking/', {'code': ['x']}, content_type='application/json').status_code, 400)

    def test_invalid_json_boundaries_return_structured_errors(self):
        bodies = ['{"question":"primera","question":"segunda"}',
                  '{"question":NaN}', '{"question":1e999}', '{"question":"\\ud800"}', '[' * 1100 + '0' + ']' * 1100,
                  '{"question":"' + 'x' * 70000 + '"}']
        for raw in bodies:
            with self.subTest(length=len(raw)):
                response = self.client.post('/api/chat/', raw, content_type='application/json')
                self.assertIn(response.status_code, (400, 413))
                self.assertIn('code', response.json()['error'])

    def test_explicit_invalid_context_is_rejected_before_job_creation(self):
        from postal.models import QueryJob
        for value in (False, 0, [], {}, '', None):
            with self.subTest(value=value):
                response = self.client.post('/api/chat/', {'question': 'Cuenta EMS', 'previous_id': value}, content_type='application/json')
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()['error']['code'], 'invalid_context')
        self.assertFalse(QueryJob.objects.exists())

    def test_year_reply_keeps_original_question_and_pending_clarification(self):
        from postal.ai import PlanningError
        from postal.models import QueryJob
        question = 'Envíos registrados en la primera semana de junio por departamentos'
        with patch('postal.jobs.plan_question', side_effect=PlanningError('clarification', '¿De qué año?')):
            first = self.client.post('/api/chat/', {'question': question}, content_type='application/json').json()['id']
        plan = {'sql': "SELECT s.departamento, COUNT(*) AS total_movimientos FROM assistant.paquetes_ems p "
                       "JOIN assistant.users u ON p.user_id=u.id JOIN assistant.sucursales s ON u.sucursal_id=s.id "
                       "WHERE p.created_at >= '2026-06-01' AND p.created_at < '2026-06-08' GROUP BY s.departamento",
                'title': 'Primera semana de junio de 2026 por departamento', 'chart': None, 'filters': {}}
        with patch('postal.jobs.plan_question', return_value=plan) as planner:
            response = self.client.post('/api/chat/', {'question': '2026', 'previous_id': first, 'history_ids': [first]},
                                        content_type='application/json')
        self.assertEqual(response.status_code, 202, response.content)
        self.assertTrue(planner.called)
        context = planner.call_args.args[1]
        self.assertEqual(context['conversation'], [{'question': question, 'clarification': '¿De qué año?'}])
        result = self.client.get(f"/api/results/{response.json()['id']}/").json()
        self.assertIn(result['status'], ('ok', 'no_matches', 'empty_table'))
        sql = QueryJob.objects.get(pk=result['id']).sql
        self.assertIn('2026-06-01', sql)
        self.assertIn('2026-06-08', sql)

    def test_original_que_hice_request_does_not_ask_for_user_or_package(self):
        question = 'hola quiero que me des el movimiento de paquetes que hice en la temporada la primera semana de junio por departamentos'
        with patch('postal.ai._call_json', return_value={'clarification': 'Indique su identificador de usuario o código de paquete'}) as provider:
            created = self.client.post('/api/chat/', {'question': question}, content_type='application/json')
        self.assertEqual(created.status_code, 202)
        result = self.client.get(f"/api/results/{created.json()['id']}/").json()
        self.assertEqual(result['error']['code'], 'clarification')
        self.assertEqual(result['error']['message'], '¿De qué año necesitas la primera semana de junio?')
        provider.assert_not_called()

    @override_settings(GROQ_API_KEY='test-key')
    def test_movement_year_change_does_not_call_rate_limited_provider(self):
        from postal.ai import PlanningError
        from postal.models import QueryJob
        question = 'hola quiero que me des el movimiento de paquetes que hice en la temporada la primera semana de junio por departamentos'
        history = []
        with patch('postal.ai._call_json', side_effect=PlanningError('provider_rate_limited', 'Límite de solicitudes')) as provider:
            for text in (question, '2024', 'del 2025'):
                response = self.client.post('/api/chat/', {'question': text, **({'history_ids': history, 'previous_id': history[-1]} if history else {})}, content_type='application/json')
                self.assertEqual(response.status_code, 202, response.content)
                history.append(response.json()['id'])
            result = self.client.get(f'/api/results/{history[-1]}/').json()
        provider.assert_not_called()
        self.assertIn(result['status'], ('ok', 'no_matches', 'empty_table'))
        self.assertIn('junio de 2025', result['title'])
        for panel in QueryJob.objects.get(pk=result['id']).panels:
            self.assertEqual(panel['filters']['Inicio'], '2025-06-01')
            self.assertEqual(panel['filters']['Fin exclusivo'], '2025-06-08')

    def test_short_replies_keep_all_prior_clarifications(self):
        from postal.ai import PlanningError
        history = []
        questions = ['Análisis de paquetes la primera semana de junio por departamentos', '2026', 'movimiento de paquetes', 'todo']
        with patch('postal.jobs.plan_question', side_effect=PlanningError('clarification', '¿Qué dato falta?')) as planner:
            for question in questions:
                response = self.client.post('/api/chat/', {'question': question, **({'history_ids': history, 'previous_id': history[-1]} if history else {})},
                                            content_type='application/json')
                self.assertEqual(response.status_code, 202, response.content)
                history.append(response.json()['id'])
        self.assertEqual([turn['question'] for turn in planner.call_args.args[1]['conversation']], questions[:-1])

    def test_history_rejects_other_sessions_and_invalid_lists(self):
        from postal.models import QueryJob
        foreign = QueryJob.objects.create(user=self.user, session_hash='different-session', kind='chat', status='error',
                                         error={'code': 'clarification', 'message': '¿De qué año?'})
        for history, status in (([str(foreign.id)], 404), ('invalid', 400), ([False], 400), (['x' * 36], 400),
                                ([str(foreign.id)] * 13, 400), ([str(foreign.id)] * 2, 400)):
            with self.subTest(history=history):
                response = self.client.post('/api/chat/', {'question': '2026', 'history_ids': history}, content_type='application/json')
                self.assertEqual(response.status_code, status)
        self.assertEqual(QueryJob.objects.count(), 1)

    def test_unknown_job_is_404(self):
        self.assertEqual(self.client.get('/api/results/00000000-0000-0000-0000-000000000001/').status_code, 404)

    def test_client_rows_are_never_verified_evidence(self):
        response = self.client.post('/api/chat/', {'question': 'Cuenta sucursales', 'rows': [{'fake': 500}]}, content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_result_belongs_to_user_and_session(self):
        from postal.models import QueryJob
        from postal.views import session_fingerprint
        job = QueryJob.objects.create(user=self.user, session_hash=session_fingerprint(self.client.session.session_key), kind='dashboard', status='ok', title='Resultado')
        self.assertEqual(self.client.get(f'/api/results/{job.id}/').status_code, 200)
        other_session = Client()
        other_session.force_login(self.user)
        self.assertEqual(other_session.get(f'/api/results/{job.id}/').status_code, 404)
        second = get_user_model().objects.create_user('segundo', password='Postal-Prueba-2026')
        other = Client()
        other.force_login(second)
        self.assertEqual(other.get(f'/api/results/{job.id}/').status_code, 404)

    def test_tracking_without_code_has_clear_error(self):
        self.assertEqual(self.client.post('/api/tracking/', {'code': ''}, content_type='application/json').status_code, 400)

    def test_status_does_not_expose_key(self):
        with override_settings(GROQ_API_KEY='private-key-test'):
            response = self.client.get('/api/status/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['assistant_configured'])
        self.assertNotIn('private-key-test', response.content.decode())

    def test_non_string_tracking_service_is_rejected(self):
        for service in ([], {}, 7, False):
            with self.subTest(service=service):
                response = self.client.post('/api/tracking/', {'code': 'ABC', 'service': service}, content_type='application/json')
                self.assertEqual(response.status_code, 400)

    def test_stale_tab_identity_cannot_start_job(self):
        response = self.client.post('/api/tracking/', {'code': 'ABC'}, content_type='application/json', HTTP_X_BOLIPOST_USER='999999')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error']['code'], 'identity_changed')

    def test_tracking_and_pdf_use_verified_owned_rows(self):
        created = self.client.post('/api/tracking/', {'code': 'BO-DEMO-001', 'service': 'EMS'}, content_type='application/json')
        self.assertEqual(created.status_code, 202)
        job_id = created.json()['id']
        data = self.client.get(f'/api/results/{job_id}/').json()
        self.assertEqual(data['status'], 'ok', data)
        self.assertGreater(len(data['rows']), 1)
        self.assertEqual({row['servicio'] for row in data['rows']}, {'EMS'})
        pdf = self.client.get(f'/api/results/{job_id}/pdf/')
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b'%PDF-'))
        self.assertRegex(pdf['Content-Disposition'], r'^attachment; filename="bolipost-[a-z0-9-]+-\d{4}-\d{2}-\d{2}\.pdf"$')
        self.assertNotIn(job_id, pdf['Content-Disposition'])

    def test_aggregate_chart_uses_full_verified_count(self):
        created = self.client.post('/api/dashboard/', {'metric': 'envios_por_servicio'}, content_type='application/json').json()
        data = self.client.get(f"/api/results/{created['id']}/").json()
        self.assertEqual(data['status'], 'ok', data)
        self.assertEqual(next(row['cantidad'] for row in data['rows'] if row['servicio'] == 'EMS'), 80)
        self.assertIsNotNone(data['chart'])

    def test_chat_missing_provider_key_stays_error(self):
        with override_settings(GROQ_API_KEY=''):
            created = self.client.post('/api/chat/', {'question': 'Cuenta los envíos'}, content_type='application/json').json()
        result = self.client.get(f"/api/results/{created['id']}/").json()
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error']['code'], 'missing_api_key')
        self.assertEqual(result['rows'], [])

    def test_metadata_question_does_not_publish_restricted_table(self):
        with patch('postal.jobs.plan_question') as planner:
            created = self.client.post('/api/chat/', {'question': 'Describe los campos de password_reset_tokens'}, content_type='application/json').json()
        result = self.client.get(f"/api/results/{created['id']}/").json()
        self.assertEqual(result['error']['code'], 'clarification')
        self.assertEqual(result['rows'], [])
        self.assertNotIn('password_reset_tokens', str(result))
        planner.assert_not_called()

    def test_chat_result_can_page_past_first_fifty_and_retains_server_context(self):
        plan = {'sql': 'SELECT id, codigo, ciudad FROM assistant.paquetes_ems ORDER BY id', 'title': 'EMS', 'chart': None, 'filters': {'servicio': 'EMS'}}
        with patch('postal.jobs.plan_question', return_value=plan):
            created = self.client.post('/api/chat/', {'question': 'Lista EMS'}, content_type='application/json').json()
        first = self.client.get(f"/api/results/{created['id']}/").json()
        self.assertEqual(first['status'], 'ok', first)
        self.assertEqual(len(first['rows']), 80)
        with patch('postal.jobs.plan_question', return_value=plan) as planner:
            followup = self.client.post('/api/chat/', {'question': '¿Y sus detalles?', 'previous_id': created['id']}, content_type='application/json')
        self.assertEqual(followup.status_code, 202)
        context = planner.call_args.args[1]
        self.assertEqual(context['filters'], {'fuentes': ['paquetes_ems'], 'condiciones': []})
        self.assertEqual(context['preview_first_page'][0]['codigo'], 'BO-DEMO-001')

    def test_package_type_definition_uses_verified_value_without_circular_question(self):
        from contextlib import contextmanager
        from postal.data import DemoSource, Stream

        class PackageSource(DemoSource):
            @contextmanager
            def stream(self, sql, params=None, cancellation=None):
                yield Stream(['tipo_paquete'], iter([{'tipo_paquete': 'PG'}]), ['paquetes_ordi'])

        plan = {'sql': 'SELECT tipo AS tipo_paquete FROM assistant.paquetes_ordi WHERE id = 6466',
                'title': 'Tipo de paquete'}
        with patch('postal.jobs.get_source', return_value=PackageSource()), patch('postal.jobs.plan_question', return_value=plan):
            first = self.client.post('/api/chat/', {'question': '¿Qué tipo de paquete es?'}, content_type='application/json').json()['id']
        for question in ('que es PG?', '¿Qué significa PG?', '¿Qué significa ese tipo?', 'Explica PG'):
            with self.subTest(question=question), patch('postal.jobs.plan_question') as planner:
                created = self.client.post('/api/chat/', {'question': question, 'previous_id': first}, content_type='application/json').json()
                result = self.client.get(f"/api/results/{created['id']}/").json()
                self.assertEqual(result['status'], 'ok', result)
                self.assertIn('PG', result['answer'])
                self.assertIn('no documenta', result['answer'])
                self.assertEqual(result['rows'], [{'tipo_paquete': 'PG'}])
                self.assertIsNone(result['error'])
                planner.assert_not_called()

    def test_empty_package_list_does_not_claim_a_first_package_was_identified(self):
        plan = {'title': 'Primer paquete de la lista', 'sql': "SELECT codigo FROM assistant.paquetes_ordi WHERE codigo = 'INVENTADO'"}
        with patch('postal.jobs.plan_question', return_value=plan):
            first = self.client.post('/api/chat/', {'question': 'Lista tres paquetes inventados'}, content_type='application/json').json()['id']
            second = self.client.post('/api/chat/', {'question': 'Dame todos los datos del primero de esos tres', 'previous_id': first}, content_type='application/json').json()['id']
        result = self.client.get(f'/api/results/{second}/').json()
        self.assertEqual(result['status'], 'no_matches')
        self.assertIn('no hay un paquete identificado', result['answer'])
        self.assertEqual(result['title'], 'No hay un paquete identificado')

    def test_no_matches_and_empty_table_are_distinct(self):
        from contextlib import contextmanager
        from postal.data import DemoSource, Stream
        class EmptySource(DemoSource):
            @contextmanager
            def stream(self, sql, params=None, cancellation=None):
                yield Stream(['id'], iter([]), ['paquetes_int'])
        plan = {'sql': 'SELECT id FROM assistant.paquetes_ems WHERE id = -1', 'title': 'Consulta', 'chart': None, 'filters': {}}
        with patch('postal.jobs.plan_question', return_value=plan):
            created = self.client.post('/api/chat/', {'question': 'Consulta de prueba'}, content_type='application/json').json()
        result = self.client.get(f"/api/results/{created['id']}/").json()
        self.assertEqual(result['status'], 'no_matches', result)
        with patch('postal.jobs.get_source', return_value=EmptySource()), patch('postal.jobs.plan_question', return_value=plan):
            created = self.client.post('/api/chat/', {'question': 'Consulta de prueba'}, content_type='application/json').json()
        result = self.client.get(f"/api/results/{created['id']}/").json()
        self.assertEqual(result['status'], 'empty_table', result)

    def test_model_cannot_publish_a_literal_as_verified_data(self):
        plan = {'sql': 'SELECT 999999 AS envios_verificados FROM assistant.paquetes_ems LIMIT 1', 'title': 'Envíos', 'chart': None, 'filters': {}}
        with patch('postal.jobs.plan_question', return_value=plan):
            created = self.client.post('/api/chat/', {'question': 'Cuenta los envíos'}, content_type='application/json').json()
        result = self.client.get(f"/api/results/{created['id']}/").json()
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error']['code'], 'query_rejected')
        self.assertEqual(result['rows'], [])

    def test_second_page_is_available_without_a_total_row_cap(self):
        sql = 'SELECT id, codigo FROM assistant.paquetes_ems UNION ALL SELECT id, codigo FROM assistant.paquetes_ems'
        with patch('postal.jobs.plan_question', return_value={'sql': sql, 'title': 'Dos lotes', 'chart': None, 'filters': {}}):
            created = self.client.post('/api/chat/', {'question': 'Lista ambos lotes'}, content_type='application/json').json()
        first = self.client.get(f"/api/results/{created['id']}/").json()
        second = self.client.get(f"/api/results/{created['id']}/?page=2").json()
        self.assertEqual(first['status'], 'ok', first)
        self.assertEqual(first['row_count'], 160)
        self.assertEqual(len(first['rows']), 100)
        self.assertTrue(first['has_more'])
        self.assertEqual(len(second['rows']), 60)
        self.assertFalse(second['has_more'])
        self.assertEqual(self.client.get(f"/api/results/{created['id']}/?page=3").status_code, 400)

    def test_abandonment_lease_cancels_without_limiting_active_query_duration(self):
        from postal import jobs
        from postal.data import Cancellation
        from postal.models import QueryJob
        token = Cancellation()
        job = QueryJob.objects.create(user=self.user, session_hash='test', kind='chat', status='running')
        with patch.dict(jobs._active, {str(job.id): token}, clear=True), patch.dict(jobs._seen, {str(job.id): 1.0}, clear=True):
            jobs.reap_abandoned(now=120)
            self.assertFalse(token.cancelled)
            jobs.reap_abandoned(now=122)
            self.assertTrue(token.cancelled)
        job.refresh_from_db()
        self.assertEqual(job.status, 'cancelled')

    def test_missing_connection_does_not_fall_back_to_demo(self):
        with override_settings(DATA_MODE='postgres', BUSINESS_DATABASE_URL=''):
            created = self.client.post('/api/tracking/', {'code': 'BO-DEMO-002'}, content_type='application/json').json()
        result = self.client.get(f"/api/results/{created['id']}/").json()
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error']['code'], 'database_configuration')
        self.assertFalse(result['demo'])

    def test_expired_results_are_not_exportable_and_are_cleaned(self):
        from datetime import timedelta
        from django.utils import timezone
        from postal import jobs
        from postal.models import QueryJob
        created = self.client.post('/api/dashboard/', {'metric': 'envios_por_servicio'}, content_type='application/json').json()
        job = QueryJob.objects.get(pk=created['id'])
        path = jobs.spool_path(job.id)
        self.assertTrue(path.exists())
        QueryJob.objects.filter(pk=job.id).update(updated_at=timezone.now() - timedelta(hours=25))
        self.assertEqual(self.client.get(f'/api/results/{job.id}/pdf/').status_code, 410)
        with patch('postal.jobs._last_cleanup', 0.0):
            jobs.maintain_results()
        self.assertFalse(path.exists())
        self.assertFalse(QueryJob.objects.filter(pk=job.id).exists())

    def test_jobs_from_previous_process_do_not_permanently_block_new_work(self):
        from datetime import timedelta
        from django.utils import timezone
        from postal.models import QueryJob
        from postal.views import session_fingerprint
        for _ in range(2):
            job = QueryJob.objects.create(user=self.user, session_hash=session_fingerprint(self.client.session.session_key), kind='chat', status='running')
            QueryJob.objects.filter(pk=job.id).update(updated_at=timezone.now() - timedelta(minutes=3))
        with patch('postal.jobs._last_cleanup', 0.0):
            response = self.client.post('/api/dashboard/', {'metric': 'envios_por_servicio'}, content_type='application/json')
        self.assertEqual(response.status_code, 202, response.content)
