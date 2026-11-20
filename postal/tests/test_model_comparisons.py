from unittest.mock import patch

from django.test import TestCase, override_settings

from postal.ai import PlanningError, plan_question
from postal.data import DemoSource
from postal.policy import catalog, validate_ai_sql


@override_settings(AI_PROVIDER='groq', GROQ_API_KEY='test-key')
class ModelComparisonTests(TestCase):
    def plan(self, sql, locations, column='p.destino'):
        response = {'title': 'Comparación', 'sql': sql,
                    'comparison': {'column': column, 'locations': locations}}
        with patch('postal.ai._call_json', return_value=response) as model:
            result = plan_question('Compara esos departamentos conservando el periodo y servicio.', None, catalog())
        model.assert_called_once()
        validate_ai_sql(result['sql'])
        return result

    def test_three_departments_keep_destination_dates_and_real_aggregate(self):
        result = self.plan("SELECT COUNT(*) AS total FROM assistant.paquetes_contrato p "
                           "WHERE p.created_at >= '2026-10-01' AND p.created_at < '2026-11-01'",
                           ['La Paz', 'Cochabamba', 'Tarija'])
        with DemoSource().stream(result['sql']) as stream:
            rows = list(stream.rows)
        self.assertEqual(rows, [{'la_paz': 0, 'cochabamba': 4, 'tarija': 0}])
        self.assertNotIn('p.origen', result['sql'])
        self.assertIn('2026-10-01', result['sql'])
        self.assertLess(len(result['sql']), 30000)

    def test_origin_weight_and_service_are_preserved(self):
        result = self.plan('SELECT SUM(p.peso) AS peso_total FROM assistant.paquetes_ems p',
                           ['La Paz', 'Santa Cruz'], 'p.origen')
        self.assertIn('SUM(p.peso)', result['sql'])
        self.assertIn('TRIM(p.origen)', result['sql'])

    def test_real_model_redundant_location_filter_preserves_dates(self):
        result = self.plan("SELECT COUNT(*) AS total_envios FROM assistant.paquetes_contrato p "
                           "WHERE p.destino IN ('Cochabamba','Potosí') "
                           "AND p.created_at >= '2026-09-01' AND p.created_at < '2026-10-01'",
                           ['Cochabamba', 'Potosí'])
        self.assertNotIn('p.destino IN', result['comparison']['base_sql'])
        self.assertIn('2026-09-01', result['comparison']['base_sql'])

    def test_bad_comparison_does_not_become_unfiltered_query(self):
        for comparison in ({'column': 'p.user_id', 'locations': ['Tarija', 'Oruro']},
                           {'column': 'p.ciudad', 'locations': ['Tarija', 'Lugar inventado']},
                           {'column': 'p.ciudad', 'locations': ['Tarija']},
                           {'column': 'p.ciudad', 'locations': ['Tarija', 'Tarija']}):
            response = {'sql': 'SELECT COUNT(*) AS total FROM assistant.paquetes_ems p',
                        'comparison': comparison}
            with self.subTest(comparison=comparison), patch('postal.ai._call_json', return_value=response):
                with self.assertRaises(PlanningError):
                    plan_question('Compara los departamentos', None, catalog())
