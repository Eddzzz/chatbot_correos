import json
from pathlib import Path
import tempfile
from unittest.mock import patch, MagicMock

from django.contrib.auth import get_user_model
from django.test import override_settings

from .api_client import ApiTestCase

from postal.ai import PlanningError, validate_plan


class ReportRoutingTests(ApiTestCase):
    def test_branch_name_lookup_uses_sales_point_and_never_guesses_ambiguous_codes(self):
        from postal.views import _name_branches
        source = MagicMock()
        source.stream.return_value.__enter__.return_value.rows = [
            {'codigoSucursal': 0, 'puntoVenta': 0, 'municipio': 'LA PAZ'},
            {'codigoSucursal': 0, 'puntoVenta': 1, 'municipio': 'EL ALTO'}]
        panels = [{'columns': ['sucursal_codigo', 'punto_venta', 'total'], 'source_tables': ['sucursales'],
                   'rows': [{'sucursal_codigo': 0, 'punto_venta': 0, 'total': 12},
                            {'sucursal_codigo': 0, 'punto_venta': 1, 'total': 7},
                            {'sucursal_codigo': 999, 'punto_venta': 0, 'total': 2}]},
                  {'columns': ['sucursal_codigo', 'total'], 'source_tables': ['sucursales'],
                   'rows': [{'sucursal_codigo': 0, 'total': 19}]}]
        _name_branches(panels, source)
        self.assertEqual([row['nombre_sucursal'] for row in panels[0]['rows']],
                         ['LA PAZ', 'EL ALTO', 'Sucursal sin nombre (código 999)'])
        self.assertEqual(panels[1]['rows'][0]['nombre_sucursal'], 'Sucursal sin nombre (código 0)')
        self.assertEqual([row['total'] for row in panels[0]['rows']], [12, 7, 2])

    def test_report_about_tables_is_not_mistaken_for_a_schema_request(self):
        from postal.jobs import _catalog_answer
        from postal.policy import catalog
        self.assertIsNone(_catalog_answer('Genera un reporte de las tablas paquetes_ems y sucursales', catalog()))


@override_settings(JOBS_EAGER=True, DATA_MODE='demo', GROQ_API_KEY='test-only-not-real')
class AssistantReportTests(ApiTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.override = override_settings(RESULT_DIR=Path(self.folder.name))
        self.override.enable()
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(self.override.disable)
        user = get_user_model().objects.create_superuser('analista', password='Postal-Analista-Prueba')
        self.client.force_login(user)
        self.plan = validate_plan({'intent': 'dashboard', 'title': 'Dashboard EMS', 'queries': [
            {'title': 'Total EMS', 'sql': 'SELECT COUNT(*) AS total FROM assistant.paquetes_ems'},
            {'title': 'Por ciudad', 'sql': 'SELECT ciudad, COUNT(*) AS total FROM assistant.paquetes_ems GROUP BY ciudad',
             'chart': {'kind': 'bar', 'label_column': 'ciudad', 'value_column': 'total', 'label': 'Envíos'}}]})

    def create(self):
        response = self.client.post('/api/chat/', {'question': 'Genera un dashboard y resumen de los envíos EMS'}, content_type='application/json')
        self.assertEqual(response.status_code, 202, response.content)
        return response.json()['id']

    def test_explanation_followup_uses_analyst_skills_and_saved_evidence_without_querying(self):
        from postal.models import AssistantSkill
        AssistantSkill.objects.create(name='QA explicación activa', stage='analyst', instructions='QA_ANALYST_EXPLANATION', enabled=True)
        AssistantSkill.objects.create(name='QA explicación desactivada', stage='analyst', instructions='QA_DISABLED_EXPLANATION', enabled=False)
        AssistantSkill.objects.create(name='QA planificación', stage='planner', instructions='QA_ONLY_PLANNER', enabled=True)
        with patch('postal.jobs.plan_question', return_value=self.plan), patch('postal.jobs.compose_response', return_value={'answer': 'Datos', 'citations': []}):
            original = self.create()
        paragraphs = [{'kind': 'value', 'references': [{'panel': 0, 'row': 0, 'column': 'total'}]},
                      {'kind': 'advice', 'references': [{'panel': 0, 'row': 0, 'column': 'total'}]}]
        with patch('postal.jobs.get_source', side_effect=AssertionError('No debe volver a consultar la base postal')), \
                patch('postal.jobs.plan_question', side_effect=AssertionError('No debe generar otro plan SQL')), \
                patch('postal.ai._request_json', return_value={'paragraphs': paragraphs}) as analyst:
            response = self.client.post('/api/chat/', {'question': 'dame una explicaion de eso', 'previous_id': original}, content_type='application/json')
        result = self.client.get(f"/api/results/{response.json()['id']}/").json()
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['analysis']['presentation'], 'explanation')
        self.assertIn('80', result['answer'])
        self.assertNotIn('Consejo:', result['answer'])
        sent = analyst.call_args.args[0]
        instructions = '\n'.join(message['content'] for message in sent['messages'] if message['role'] == 'system')
        self.assertIn('QA_ANALYST_EXPLANATION', instructions)
        self.assertNotIn('QA_DISABLED_EXPLANATION', instructions)
        self.assertNotIn('QA_ONLY_PLANNER', instructions)
        self.assertIn(AssistantSkill.objects.get(preset_key='evidence-advice').instructions, instructions)
        self.assertIn('Explica los resultados en párrafos', instructions)
        self.assertIn('Reserva las listas para', instructions)
        evidence = json.loads(sent['messages'][1]['content'])['verified_evidence']
        self.assertEqual(evidence[0]['rows'], [{'total': 80}])
        self.assertTrue(evidence[0]['complete'])
        self.assertEqual(result['response_type'], 'dashboard')
        with patch('postal.jobs.get_source', side_effect=AssertionError('No debe volver a consultar la base postal')), \
                patch('postal.jobs.plan_question', side_effect=AssertionError('No debe generar otro plan SQL')), \
                patch('postal.ai._request_json', return_value={'paragraphs': paragraphs}):
            response = self.client.post('/api/chat/', {'question': 'explícame más', 'previous_id': result['id']}, content_type='application/json')
        expanded = self.client.get(f"/api/results/{response.json()['id']}/").json()
        self.assertEqual(expanded['status'], 'ok', expanded)
        self.assertEqual(expanded['panels'][0]['rows'], result['panels'][0]['rows'])
        self.assertEqual(expanded['analysis']['presentation'], 'explanation')

    def test_explanation_followup_uses_verified_data_when_analyst_is_disabled(self):
        from postal.system_config import configuration
        with patch('postal.jobs.plan_question', return_value=self.plan), patch('postal.jobs.compose_response', return_value={'answer': 'Datos', 'citations': []}):
            original = self.create()
        snapshot = {**configuration(), 'ANALYST_ENABLED': False}
        with patch('postal.jobs.configuration', return_value=snapshot), patch('postal.jobs.plan_question') as planner:
            response = self.client.post('/api/chat/', {'question': 'explica eso', 'previous_id': original}, content_type='application/json')
        result = self.client.get(f"/api/results/{response.json()['id']}/").json()
        self.assertEqual(result['status'], 'ok')
        self.assertIn('80', result['answer'])
        self.assertFalse(result['analysis']['generated'])
        self.assertIn('warning', result['analysis'])
        planner.assert_not_called()

    def test_chart_followups_keep_verified_queries_and_accept_pie_with_advice(self):
        narration = {'answer': 'Explicación breve.\n\nConsejo: compara períodos equivalentes.', 'citations': [], 'generated': True}
        self.plan['queries'][1] = validate_plan({'title': 'Por estado',
            'sql': 'SELECT estado_id, COUNT(*) AS total FROM assistant.paquetes_ems GROUP BY estado_id',
            'chart': {'kind': 'bar', 'label_column': 'estado_id', 'value_column': 'total', 'label': 'Envíos'}})
        with patch('postal.jobs.plan_question', return_value=self.plan), patch('postal.jobs.compose_response', return_value=narration):
            original = self.create()
        before = self.client.get(f'/api/results/{original}/').json()
        # Existing conversations from before this fix have no saved chart specification.
        from postal.models import QueryJob
        saved = QueryJob.objects.get(pk=original)
        for panel in saved.panels:
            panel.pop('chart_spec', None)
        saved.save(update_fields=['panels'])
        with patch('postal.ai._call_json', return_value={'view': 'bar'}) as chooser, patch('postal.jobs.compose_response', return_value=narration):
            response = self.client.post('/api/chat/', {'question': 'cambia de grafica', 'previous_id': original}, content_type='application/json')
        changed = self.client.get(f"/api/results/{response.json()['id']}/").json()
        self.assertEqual(changed['status'], 'ok', changed)
        self.assertEqual(changed['panels'][1]['chart']['view'], 'bar')
        chooser.assert_called_once()
        with patch('postal.ai._call_json') as planner, patch('postal.jobs.compose_response', return_value=narration):
            response = self.client.post('/api/chat/', {'question': 'pastel integrar Consejos y Explicación breves y ampliar i el user lo pide',
                                                      'previous_id': changed['id']}, content_type='application/json')
        after = self.client.get(f"/api/results/{response.json()['id']}/").json()
        self.assertEqual(after['status'], 'ok', after)
        self.assertEqual(after['response_type'], 'dashboard')
        self.assertEqual(after['panels'][1]['chart']['view'], 'pie')
        self.assertEqual(after['answer'], narration['answer'])
        for old, new in zip(before['panels'], after['panels']):
            for field in ('sql', 'filters', 'rows', 'row_count'):
                self.assertEqual(old[field], new[field])
        planner.assert_not_called()

    def test_deletion_refusal_in_api_never_offers_to_delete_later(self):
        with patch('postal.ai._call_json', return_value={'clarification':
                'No puedo borrar paquetes. ¿Deseas revisarlos antes de proceder con la eliminación?'}):
            response = self.client.post('/api/chat/', {'question': 'Borra todos los paquetes EMS.'}, content_type='application/json')
        result = self.client.get(f"/api/results/{response.json()['id']}/").json()
        self.assertEqual(result['error']['code'], 'restricted_request')
        self.assertIn('No puede borrar', result['answer'])
        self.assertNotIn('antes de proceder', json.dumps(result, ensure_ascii=False))
        self.assertEqual(result['rows'], [])

    def test_zero_delivery_explanation_survives_narration_failure(self):
        plan = validate_plan({'title': 'Registros de entrega',
            'sql': "SELECT COUNT(*) AS total_entregas FROM assistant.eventos_certi WHERE codigo = 'ZZ000000000ZZ'"})
        with patch('postal.jobs.plan_question', return_value=plan), patch('postal.jobs.compose_response',
                side_effect=PlanningError('provider_request', 'No se pudo generar la explicación.')):
            response = self.client.post('/api/chat/', {'question': 'Si no aparece significa que fue entregado?'}, content_type='application/json')
        result = self.client.get(f"/api/results/{response.json()['id']}/").json()
        self.assertEqual(result['status'], 'ok')
        self.assertIn('conteo consultado es 0', result['answer'])
        self.assertIn('no confirma', result['answer'])
        self.assertIn('estado actual', result['answer'])
        self.assertEqual(result['analysis']['citations'][0]['value'], 0)

    def test_unexpected_failure_logs_location_without_sensitive_exception_text(self):
        secret = 'private-provider-payload-and-database-url'
        with patch('postal.jobs.plan_question', side_effect=RuntimeError(secret)), self.assertLogs('postal.jobs', level='ERROR') as logs:
            job_id = self.create()
        result = self.client.get(f'/api/results/{job_id}/').json()
        self.assertEqual(result['error']['code'], 'execution_error')
        logged = '\n'.join(logs.output)
        self.assertIn('RuntimeError', logged)
        self.assertIn('jobs.py:', logged)
        self.assertNotIn(secret, logged)
        self.assertNotIn(secret, json.dumps(result))

    def test_movement_report_uses_real_events_after_year_clarification_without_provider(self):
        question = 'hola quiero que me des el movimiento de paquetes que hice en la temporada la primera semana de junio por departamentos'
        with patch('postal.jobs.plan_question', side_effect=AssertionError('Must use verified event report')):
            first = self.client.post('/api/chat/', {'question': question}, content_type='application/json').json()['id']
            first_result = self.client.get(f'/api/results/{first}/').json()
            self.assertEqual(first_result['error']['message'], '¿De qué año necesitas la primera semana de junio?')
            response = self.client.post('/api/chat/', {'question': '2026', 'history_ids': [first], 'previous_id': first}, content_type='application/json')
        self.assertEqual(response.status_code, 202)
        result = self.client.get(f"/api/results/{response.json()['id']}/").json()
        self.assertIn(result['status'], ('ok', 'no_matches', 'empty_table'))
        self.assertIn('total_movimientos', result['columns'])
        self.assertNotIn('total_envios', result['columns'])
        self.assertIn('Sin departamento', result['analysis']['note'])
        for panel in result['panels']:
            self.assertTrue(any(source.startswith('eventos_') for source in panel['source_tables']))
            self.assertEqual(panel['filters']['Fecha'], 'Fecha del evento')
        pdf = self.client.get(f"/api/results/{response.json()['id']}/pdf/")
        self.assertEqual(pdf.status_code, 200)

    def test_branch_names_replace_codes_in_table_chart_and_pdf(self):
        from io import BytesIO
        from pypdf import PdfReader
        from postal.data import DemoSource
        from reportlab.platypus import LongTable
        plan = validate_plan({'title': 'Envíos por sucursal',
            'sql': 'SELECT s."codigoSucursal" AS sucursal_codigo, s."puntoVenta" AS punto_venta, COUNT(*) AS total_envios '
                   'FROM assistant.sucursales s GROUP BY s."codigoSucursal", s."puntoVenta"',
            'chart': {'kind': 'bar', 'label_column': 'sucursal_codigo', 'value_column': 'total_envios'}})
        with patch('postal.jobs.plan_question', return_value=plan), patch('postal.jobs.compose_response',
                return_value={'answer': '', 'citations': []}):
            job_id = self.create()
        with DemoSource().stream(plan['sql']) as stream:
            original_rows = list(stream.rows)
        with DemoSource().stream('SELECT "codigoSucursal", municipio FROM assistant.sucursales') as stream:
            names = {str(row['codigoSucursal']): row['municipio'] for row in stream.rows}
        result = self.client.get(f'/api/results/{job_id}/').json()
        self.assertIn('nombre_sucursal', result['columns'])
        self.assertNotIn('sucursal_codigo', result['columns'])
        self.assertEqual([row['nombre_sucursal'] for row in result['rows']],
                         [names[str(row['sucursal_codigo'])] for row in original_rows])
        self.assertEqual([row['total_envios'] for row in result['rows']], [row['total_envios'] for row in original_rows])
        self.assertEqual(result['chart']['labels'], [row['nombre_sucursal'] for row in result['rows']])
        with patch('postal.pdf.LongTable', wraps=LongTable) as table:
            pdf = self.client.get(f'/api/results/{job_id}/pdf/')
        self.assertEqual(pdf.status_code, 200)
        text = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages)
        self.assertIn(f"{len(result['chart']['labels'])} categorías", text)
        self.assertEqual(table.call_args.args[0][0][0].getPlainText(), 'Sucursal')
        self.assertEqual(table.call_args.args[0][1][0].getPlainText(), result['rows'][0]['nombre_sucursal'])

    def test_service_status_report_works_when_provider_is_unavailable(self):
        with patch('postal.jobs.plan_question', side_effect=AssertionError('Unexpected provider call')):
            response = self.client.post('/api/chat/', {
                'question': 'Genera un reporte de envíos por servicio y por estado, con sus fuentes y filtros.'
            }, content_type='application/json')
        self.assertEqual(response.status_code, 202)
        job = self.client.get(f"/api/results/{response.json()['id']}/").json()
        self.assertEqual(job['status'], 'ok', job.get('error'))
        self.assertEqual(job['response_type'], 'report')
        totals, states = job['panels']
        self.assertEqual(totals['filters']['Periodo'], 'Todo el respaldo')
        self.assertNotIn('paquetes_ems_formulario', totals['source_tables'])
        self.assertEqual(sum(row['cantidad'] for row in totals['rows']), sum(row['cantidad'] for row in states['rows']))

    def test_service_summary_works_without_a_provider_call(self):
        with patch('postal.jobs.plan_question', side_effect=AssertionError('Unexpected provider call')):
            response = self.client.post('/api/chat/', {
                'question': 'Resume los envíos por servicio postal.'
            }, content_type='application/json')
        self.assertEqual(response.status_code, 202)
        job = self.client.get(f"/api/results/{response.json()['id']}/").json()
        self.assertEqual(job['status'], 'ok', job.get('error'))
        self.assertEqual(job['response_type'], 'summary')
        self.assertNotIn('paquetes_ems_formulario', job['source_tables'])

    def test_suggested_dashboard_uses_verified_queries_for_all_three_charts(self):
        with patch('postal.jobs.plan_question', side_effect=AssertionError('Unexpected provider call')):
            response = self.client.post('/api/chat/', {
                'question': 'Crea un dashboard con envíos por servicio, por estado y su evolución mensual.'
            }, content_type='application/json')
        self.assertEqual(response.status_code, 202)
        job = self.client.get(f"/api/results/{response.json()['id']}/").json()
        self.assertEqual(job['status'], 'ok', job.get('error'))
        self.assertEqual(job['response_type'], 'dashboard')
        self.assertEqual([panel['chart']['kind'] for panel in job['panels']], ['bar', 'bar', 'line'])
        self.assertNotIn('paquetes_ems_formulario', job['source_tables'])
        self.assertEqual(sum(job['panels'][0]['chart']['values']), sum(job['panels'][1]['chart']['values']))

    def test_dashboard_followup_filters_by_verified_branch_relation(self):
        with patch('postal.jobs.plan_question', side_effect=AssertionError('Unexpected provider call')):
            dashboard = self.client.post('/api/chat/', {
                'question': 'Crea un dashboard con envíos por servicio, por estado y su evolución mensual.'
            }, content_type='application/json')
            response = self.client.post('/api/chat/', {
                'question': 'de sucural de la paz', 'previous_id': dashboard.json()['id']
            }, content_type='application/json')
        self.assertEqual(response.status_code, 202)
        job = self.client.get(f"/api/results/{response.json()['id']}/").json()
        self.assertEqual(job['status'], 'ok', job.get('error'))
        self.assertEqual(len(job['panels']), 3)
        self.assertEqual(job['filters']['Municipio de la sucursal'], 'La Paz')
        self.assertEqual({row['servicio'] for row in job['panels'][0]['rows']}, {'EMS', 'CONTRATO'})
        self.assertIn('sucursales', job['source_tables'])
        self.assertNotIn('paquetes_int', job['source_tables'])

    def test_end_to_end_model_plans_and_explains_real_query_results(self):
        import httpx
        requests = []
        def handle(request):
            payload = json.loads(request.content)
            requests.append(payload)
            if len(requests) == 1:
                content = {'intent': 'dashboard', 'title': 'Dashboard EMS', 'queries': self.plan['queries']}
            else:
                content = {'paragraphs': [{'kind': 'value', 'references': [{'panel': 0, 'row': 0, 'column': 'total'}]}]}
            return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(content)}}]})
        real_client = httpx.Client
        with patch('postal.ai.httpx.Client', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw)):
            job_id = self.create()
        result = self.client.get(f'/api/results/{job_id}/').json()
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['response_type'], 'dashboard')
        self.assertTrue(result['analysis']['generated'])
        self.assertIn('Se registra un total de 80.', result['answer'])
        self.assertEqual(len(result['panels']), 2)
        self.assertEqual(result['panels'][0]['rows'], [{'total': 80}])
        self.assertIsNotNone(result['panels'][1]['chart'])
        self.assertEqual(len(requests), 2)
        evidence = json.loads(requests[1]['messages'][1]['content'])['verified_evidence']
        self.assertEqual(evidence[0]['rows'], [{'total': 80}])
        self.assertNotIn('password', json.dumps(evidence))

    def test_narrative_failure_keeps_verified_report_and_warns(self):
        with patch('postal.jobs.plan_question', return_value=self.plan), patch('postal.jobs.compose_response', side_effect=PlanningError('invalid_narrative', 'No hay explicación verificable.')):
            job_id = self.create()
        result = self.client.get(f'/api/results/{job_id}/').json()
        self.assertEqual(result['status'], 'ok', result)
        self.assertFalse(result['analysis']['generated'])
        self.assertIn('warning', result['analysis'])
        self.assertIn('Se registra un total de 80.', result['answer'])
        self.assertEqual(result['panels'][0]['rows'], [{'total': 80}])

    def test_each_report_panel_has_independent_pagination_and_pdf_scope(self):
        self.plan['queries'][1] = {'title': 'Detalle', 'sql': 'SELECT id, codigo FROM assistant.paquetes_ems UNION ALL SELECT id, codigo FROM assistant.paquetes_ems', 'filters': {}, 'chart': None}
        with patch('postal.jobs.plan_question', return_value=self.plan), patch('postal.jobs.compose_response', return_value={'answer': 'Análisis con evidencia.', 'citations': []}):
            job_id = self.create()
        result = self.client.get(f'/api/results/{job_id}/?panel=1&page=2').json()
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(len(result['rows']), 60)
        self.assertEqual(result['row_count'], 160)
        self.assertEqual(result['panel_index'], 1)
        self.assertFalse(result['panels'])
        pdf = self.client.get(f'/api/results/{job_id}/pdf/?panel_pages=0:1,1:2')
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b'%PDF-'))
        self.assertEqual(self.client.get(f'/api/results/{job_id}/?panel=9').status_code, 400)
        self.assertEqual(self.client.get(f'/api/results/{job_id}/pdf/?panel_pages=1:9').status_code, 400)
