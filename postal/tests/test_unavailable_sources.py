import json
from unittest.mock import patch

from django.test import TestCase, override_settings

from postal.ai import PlanningError, plan_question
from postal.context import advance_state
from postal.policy import QueryRejected, catalog, validate_ai_sql


@override_settings(AI_PROVIDER='groq', GROQ_API_KEY='test-key')
class UnavailableSourceTests(TestCase):
    def test_audit_clarification_reports_unavailable_data_instead_of_invalid_plan(self):
        state = advance_state({}, 'dame las auitorias de la apz', '¿A qué se refiere apz?')
        for table in ('auditoria', 'eventos_auditoria'):
            with self.subTest(table=table):
                sql = f'SELECT id FROM assistant.{table}'
                with patch('postal.ai._call_json', return_value={'sql': sql}) as provider:
                    with self.assertRaises(PlanningError) as caught:
                        plan_question('la paz', {'state': state}, catalog())
                self.assertEqual(caught.exception.code, 'clarification')
                self.assertIn(table, caught.exception.message)
                self.assertIn('no están habilitados', caught.exception.message)
                self.assertEqual(provider.call_count, 1)
                with self.assertRaises(QueryRejected):
                    validate_ai_sql(sql)

    def test_planner_knows_unavailable_names_without_receiving_restricted_columns(self):
        with patch('postal.ai._call_json', return_value={
                'sql': 'SELECT COUNT(*) AS total FROM assistant.paquetes_ems'}) as provider:
            plan_question('Cuántos envíos EMS hay', None, catalog())
        sent = json.loads(provider.call_args.args[0]['messages'][1]['content'])
        self.assertIn('auditoria', sent['unavailable_tables'])
        self.assertNotIn('paquetes_ems', sent['unavailable_tables'])
        self.assertNotIn('system_audit_logs', sent['unavailable_tables'])
        self.assertNotIn('sessions', sent['unavailable_tables'])
        self.assertTrue(all(t['table'] != 'assistant.auditoria' for t in sent['catalog']))

    def test_proposed_internal_sources_are_rejected_without_exposing_names(self):
        with patch('postal.ai._call_json', return_value={'sql': 'SELECT id FROM assistant.system_audit_logs'}) as provider:
            with self.assertRaises(PlanningError) as caught:
                plan_question('Dame los datos del sistema', None, catalog())
        self.assertEqual(caught.exception.code, 'restricted_request')
        self.assertNotIn('system_audit_logs', caught.exception.message)
        provider.assert_called_once()

    def test_invented_table_still_uses_invalid_plan_retry(self):
        with patch('postal.ai._call_json', return_value={
                'sql': 'SELECT id FROM assistant.inventada'}) as provider:
            with self.assertRaises(PlanningError) as caught:
                plan_question('Dame datos', None, catalog())
        self.assertEqual(caught.exception.code, 'invalid_plan')
        self.assertEqual(provider.call_count, 2)

    def test_cte_named_like_unavailable_table_can_read_authorized_data(self):
        sql = ('WITH auditoria AS (SELECT id FROM assistant.paquetes_ems) '
               'SELECT COUNT(*) AS total FROM auditoria')
        with patch('postal.ai._call_json', return_value={'sql': sql}):
            plan = plan_question('Cuenta los envíos EMS', None, catalog())
        validate_ai_sql(plan['sql'])
