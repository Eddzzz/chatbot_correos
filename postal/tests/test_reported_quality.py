from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings

from .api_client import ApiTestCase

from postal.ai import _verification_notes, compose_response


@override_settings(JOBS_EAGER=True, DATA_MODE='demo', AI_PROVIDER='groq', GROQ_API_KEY='', OPENROUTER_API_KEY='')
class ReportedQualityTests(ApiTestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        override = override_settings(RESULT_DIR=Path(folder.name) / 'results',
                                    SYSTEM_CONFIG_PATH=Path(folder.name) / 'settings.json')
        override.enable()
        self.addCleanup(override.disable)
        self.client.force_login(get_user_model().objects.create_user('quality-audit'))

    def ask(self, question, previous=None):
        payload = {'question': question}
        if previous:
            payload['previous_id'] = previous['id']
        response = self.client.post('/api/chat/', payload, content_type='application/json')
        self.assertEqual(response.status_code, 202)
        return self.client.get('/api/results/' + response.json()['id'] + '/').json()

    def count_panel(self, table='paquetes_ems', count=6679):
        return {'title': table, 'sql': f'SELECT COUNT(*) AS total_envios FROM assistant.{table}',
                'columns': ['total_envios'], 'rows': [{'total_envios': count}], 'row_count': 1,
                'source_tables': [table], 'filters': {'condiciones': []}}

    def test_definition_is_not_a_database_search(self):
        with patch('postal.jobs.plan_question') as planner:
            result = self.ask('¿Qué significa EMS en el contexto postal? Explícalo y pon un ejemplo sin inventar tarifas ni plazos.')
        self.assertEqual(result['status'], 'ok')
        self.assertIn('Express Mail Service', result['answer'])
        self.assertIn('Ejemplo', result['answer'])
        self.assertIn('https://www.ems.post/en', result['answer'])
        planner.assert_not_called()

    def test_ambiguous_place_and_current_time_require_clarification(self):
        with patch('postal.jobs.plan_question', return_value={
                'sql': 'SELECT COUNT(*) AS total_envios FROM assistant.paquetes_ems', 'title': 'EMS'}) as planner:
            result = self.ask('¿Cuántos paquetes hay ahí ahora?')
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error']['code'], 'clarification')
        self.assertIn('lugar', result['answer'])
        self.assertIn('periodo', result['answer'])
        planner.assert_not_called()

    def test_unknown_branch_location_does_not_become_zero(self):
        plan = {'title': 'EMS', 'sql': "SELECT COUNT(*) AS total_envios FROM assistant.sucursales s WHERE LOWER(s.departamento) = 'planeta verde'"}
        with patch('postal.jobs.plan_question', return_value=plan):
            result = self.ask('Cuenta EMS de la sucursal Puerto Nube en Planeta Verde')
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error']['code'], 'clarification')
        self.assertIn('planeta verde', result['answer'].lower())

    def test_reported_unknown_branch_is_rejected_after_model_normalization(self):
        plan = {'title': 'EMS Puerto Nube', 'sql':
                'SELECT COUNT(p.id) AS total_envios FROM assistant.paquetes_ems p '
                'LEFT JOIN assistant.users u ON p.user_id = u.id '
                'LEFT JOIN assistant.sucursales s ON u.sucursal_id = s.id '
                'WHERE LOWER(TRIM(s."municipio")) = \'Puerto Nube\' '
                'AND LOWER(TRIM(s."departamento")) = \'Planeta Verde\''}
        with override_settings(GROQ_API_KEY='test-key'), patch('postal.ai._call_json', return_value=plan):
            result = self.ask('¿Cuántos paquetes EMS registró la sucursal de Puerto Nube, '
                              'en el departamento boliviano de Planeta Verde? '
                              'Si no reconoces el lugar, pídeme que lo corrija.')
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error']['code'], 'clarification')
        self.assertIn('puerto nube', result['answer'].lower())
        self.assertFalse(result['rows'])

    def test_unknown_branch_filters_cannot_bypass_location_validation(self):
        for predicate in (
            "'planeta verde' = LOWER(TRIM(s.departamento))",
            "LOWER(TRIM(s.municipio)) LIKE '%puerto nube%'",
            "s.municipio ILIKE '%Puerto Nube%'",
            "LOWER(TRIM(s.departamento)) IN ('la paz', 'planeta verde')",
        ):
            with self.subTest(predicate=predicate):
                plan = {'title': 'EMS', 'sql':
                        'SELECT COUNT(p.id) AS total_envios FROM assistant.paquetes_ems p '
                        'LEFT JOIN assistant.users u ON p.user_id = u.id '
                        'LEFT JOIN assistant.sucursales s ON u.sucursal_id = s.id WHERE ' + predicate}
                with override_settings(GROQ_API_KEY='test-key'), patch('postal.ai._call_json', return_value=plan):
                    result = self.ask('Cuenta EMS de las sucursales indicadas; pide corregir los lugares desconocidos.')
                self.assertEqual(result['status'], 'error')
                self.assertEqual(result['error']['code'], 'clarification')
                self.assertFalse(result['rows'])

    def test_branch_pattern_matching_existing_location_is_allowed(self):
        for predicate in ("LOWER(TRIM(s.municipio)) LIKE '%paz%'", "s.municipio ILIKE '%PAZ%'"):
            with self.subTest(predicate=predicate):
                plan = {'title': 'Sucursales', 'sql':
                        'SELECT COUNT(s.id) AS cantidad FROM assistant.sucursales s WHERE ' + predicate}
                with override_settings(GROQ_API_KEY='test-key'), patch('postal.ai._call_json', return_value=plan):
                    result = self.ask('Cuenta sucursales cuyo municipio contiene Paz.')
                self.assertEqual(result['status'], 'ok', result.get('error'))
                self.assertEqual(result['rows'], [{'cantidad': 1}])

    def test_recognized_branch_can_have_zero_shipments(self):
        plan = {'title': 'EMS La Paz', 'sql':
                'SELECT COUNT(p.id) AS total_envios FROM assistant.paquetes_ems p '
                'LEFT JOIN assistant.users u ON p.user_id = u.id '
                'LEFT JOIN assistant.sucursales s ON u.sucursal_id = s.id '
                "WHERE LOWER(TRIM(s.departamento)) = 'la paz' AND p.created_at < '1900-01-01'"}
        with patch('postal.jobs.plan_question', return_value=plan):
            result = self.ask('Cuenta EMS de la sucursal de La Paz anteriores a 1900.')
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(result['rows'], [{'total_envios': 0}])

    def test_a_previous_global_total_does_not_resolve_ahi(self):
        plan = {'title': 'EMS', 'sql': 'SELECT COUNT(*) AS total_envios FROM assistant.paquetes_ems'}
        with patch('postal.jobs.plan_question', return_value=plan):
            previous = self.ask('Cuenta todos los EMS')
            result = self.ask('¿Cuántos paquetes hay ahí ahora?', previous)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error']['code'], 'clarification')

    def test_source_and_filters_survive_missing_analyst(self):
        plan = {'title': 'EMS', 'sql': 'SELECT COUNT(*) AS total_envios FROM assistant.paquetes_ems'}
        with patch('postal.jobs.plan_question', return_value=plan):
            result = self.ask('Cuenta EMS e indica fuente y filtros')
        self.assertEqual(result['status'], 'ok')
        self.assertIn('respaldo histórico', result['answer'])
        self.assertNotIn('assistant.paquetes_ems', result['answer'])
        from postal.models import QueryJob
        provenance = QueryJob.objects.get(pk=result['id']).analysis['provenance'][0]
        self.assertIn('assistant.paquetes_ems', provenance)
        self.assertIn('Sin condiciones', provenance)

    def test_hypothetical_division_is_calculated_from_verified_count(self):
        notes, citations = _verification_notes('Reparte el total equitativamente entre 2 equipos. Muestra la operación y cuántos sobrarían; es hipotético.', [self.count_panel()])
        answer = '\n'.join(notes)
        for value in ('3339', '6679', '2', '1', 'hipotético'):
            self.assertIn(value, answer)
        self.assertTrue(citations)

    def test_service_comparison_calculates_difference(self):
        notes, citations = _verification_notes('Compara EMS y certificado, indica cuál tiene más y la diferencia absoluta.',
            [self.count_panel(), self.count_panel('paquetes_certi', 5231)])
        answer = '\n'.join(notes)
        for value in ('EMS', 'Certificado', '1448', '6679', '5231'):
            self.assertIn(value, answer)
        self.assertTrue(citations)

    def test_thousands_separator_is_not_truncated(self):
        notes, _ = _verification_notes('El total es exactamente 999.999 registros.', [self.count_panel()])
        self.assertIn('999999', '\n'.join(notes))

    def test_zero_count_does_not_claim_historical_coverage(self):
        panel = self.count_panel(count=0)
        panel['sql'] += " WHERE created_at >= '1900-01-01' AND created_at < '1900-02-01'"
        notes, _ = _verification_notes('Cuenta enero de 1900 y distingue cero de no verificado.', [panel])
        answer = '\n'.join(notes)
        self.assertIn('0', answer)
        self.assertIn('cobertura', answer)
        self.assertIn('no', answer.lower())

    def test_state_distribution_accepts_labels_and_explains_formula(self):
        panel = {'title': 'EMS por estado', 'columns': ['estado', 'cantidad_paquetes', 'total_envios', 'porcentaje_estado'],
                 'row_count': 2, 'source_tables': ['paquetes_ems', 'estados'],
                 'rows': [{'estado': 'ENTREGADO', 'cantidad_paquetes': 3, 'total_envios': 4, 'porcentaje_estado': 75},
                          {'estado': None, 'cantidad_paquetes': 1, 'total_envios': 4, 'porcentaje_estado': 25}]}
        proposal = {'paragraphs': [{'kind': 'distribution', 'references': [{'panel': 0, 'row': 0, 'column': 'cantidad_paquetes'}]}]}
        with patch('postal.ai._call_json', return_value=proposal):
            result = compose_response('Distribuye EMS por estado y explica cómo se calculan los porcentajes.', 'report', [panel])
        self.assertTrue(result.get('generated', True))
        self.assertIn('entregado', result['answer'].lower())
        self.assertIn('100', result['answer'])
        self.assertNotIn('no superó', result.get('note', ''))

    def test_division_followup_reuses_snapshot_without_provider_or_new_query(self):
        from postal.jobs import page_rows
        plan = {'title': 'EMS', 'sql': 'SELECT COUNT(*) AS total_envios FROM assistant.paquetes_ems'}
        with patch('postal.jobs.plan_question', return_value=plan):
            previous = self.ask('Cuenta todos los EMS')
        total = page_rows(previous['id'], 1)[0]['total_envios']
        with patch('postal.jobs.get_source') as source, patch('postal.jobs.compose_response') as analyst:
            result = self.ask('Usa el total anterior de EMS. Si se repartiera entre 2 equipos, ¿cuántos sobrarían?', previous)
        self.assertEqual(result['status'], 'ok')
        self.assertIn(f'{total} ÷ 2 = {total // 2}', result['answer'])
        source.assert_not_called()
        analyst.assert_not_called()

    def test_calculations_do_not_treat_a_sample_as_a_total(self):
        panel = self.count_panel()
        panel['row_count'] = 2
        notes, _ = _verification_notes('Reparte entre 2 equipos', [panel])
        self.assertFalse(notes)

    def test_comparison_does_not_compare_different_date_scopes(self):
        left, right = self.count_panel(), self.count_panel('paquetes_certi', 5231)
        right['filters'] = {'condiciones': ["created_at >= '2026-01-01'"]}
        notes, _ = _verification_notes('Compara y calcula la diferencia', [left, right])
        self.assertFalse(notes)

    def test_zero_teams_does_not_crash_or_invent_a_result(self):
        notes, _ = _verification_notes('Reparte entre 0 equipos', [self.count_panel()])
        self.assertFalse(notes)

    def test_percentage_formula_survives_invalid_model_narration(self):
        panel = {'title': 'EMS por estado', 'columns': ['estado', 'cantidad_paquetes', 'total_envios', 'porcentaje_estado'],
                 'row_count': 2, 'source_tables': ['paquetes_ems'],
                 'rows': [{'estado': 'ENTREGADO', 'cantidad_paquetes': 3, 'total_envios': '4', 'porcentaje_estado': '75'},
                          {'estado': None, 'cantidad_paquetes': 1, 'total_envios': '4', 'porcentaje_estado': '25'}]}
        with patch('postal.ai._call_json', return_value={'invalid': True}):
            result = compose_response('Explica cómo se calculan los porcentajes.', 'report', [panel])
        self.assertIn('× 100', result['answer'])
        self.assertIn('Total general: 4', result['answer'])
