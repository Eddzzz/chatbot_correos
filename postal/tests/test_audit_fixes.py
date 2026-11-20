from unittest.mock import patch

from django.test import TestCase, override_settings

from postal.ai import PlanningError, _verification_notes, _normalize_location_filters, plan_question
import json


@override_settings(AI_PROVIDER='groq', GROQ_API_KEY='test-key')
class AuditRegressionTests(TestCase):
    def panel(self, suffix='', rows=None, row_count=2):
        return {'title': 'Movimientos EMS', 'sql':
                'SELECT departamento, COUNT(*) AS total FROM assistant.sucursales '
                'GROUP BY departamento' + suffix,
                'row_count': row_count,
                'rows': rows if rows is not None else [{'departamento': None, 'total': 315},
                                                      {'departamento': 'LA PAZ', 'total': 642}]}

    def test_false_total_is_compared_with_complete_grouped_count_including_null(self):
        notes, citations = _verification_notes(
            'Fueron exactamente 999999999 movimientos. Comprueba el total incluyendo sin departamento.',
            [self.panel()])
        answer = '\n'.join(notes)
        self.assertIn('957', answer)
        self.assertIn('999999999', answer)
        self.assertIn('no coincide', answer)
        self.assertEqual({citation['row'] for citation in citations}, {0, 1})

    def test_matching_grouped_total_is_confirmed(self):
        notes, _ = _verification_notes('¿Son exactamente 957 movimientos en total?', [self.panel()])
        self.assertIn('coincide', '\n'.join(notes))

    def test_partial_or_filtered_groups_are_not_reported_as_a_grand_total(self):
        for panel in (self.panel(row_count=3), self.panel(' LIMIT 2'),
                      self.panel(' HAVING COUNT(*) > 5'),
                      {**self.panel(), 'sql': 'SELECT DISTINCT COUNT(*) AS total '
                       'FROM assistant.sucursales GROUP BY departamento'},
                      {**self.panel(), 'sql': 'SELECT departamento, COUNT(DISTINCT municipio) AS total '
                       'FROM assistant.sucursales GROUP BY departamento'}):
            with self.subTest(panel=panel):
                notes, citations = _verification_notes('¿Fueron exactamente 999999999 en total?', [panel])
                self.assertFalse(notes)
                self.assertFalse(citations)

    def test_ambiguous_comparison_is_not_coerced_into_a_query(self):
        with patch('postal.ai._call_json', return_value={'clarification': '¿Qué otros resultados quieres comparar?'}) as provider:
            with self.assertRaises(PlanningError) as caught:
                plan_question('Compara esos resultados con los otros.',
                              {'question': 'Cuenta paquetes EMS', 'total_rows': 1}, [])
        self.assertEqual(caught.exception.code, 'clarification')
        self.assertEqual(provider.call_count, 1)

    def test_planner_receives_compact_verified_geography(self):
        expanded = _normalize_location_filters(
            "SELECT COUNT(*) AS total FROM assistant.paquetes_certi WHERE cuidad = 'La Paz' "
            "AND created_at >= '2026-09-01' AND created_at < '2026-10-01'")
        with patch('postal.ai._call_json', return_value={
                'sql': "SELECT COUNT(*) FROM assistant.paquetes_certi WHERE cuidad = 'La Paz'"}) as provider:
            plan_question('Cambia únicamente el mes a agosto; conserva año, destino y servicio.',
                          {'sql': expanded, 'total_rows': 1}, [])
        context = json.loads(provider.call_args.args[0]['messages'][1]['content'])['previous_verified_context']
        self.assertLess(len(context['sql']), 500)
        self.assertIn('2026-09-01', context['sql'])
        self.assertIn("cuidad = 'la paz'", context['sql'])

    def test_known_details_followup_with_punctuation_can_still_use_context(self):
        with patch('postal.ai._call_json', side_effect=[{'clarification': '¿De qué paquete?'},
                {'sql': "SELECT codigo FROM assistant.paquetes_ems WHERE codigo = 'FAKE-1'"}]) as provider:
            result = plan_question('¿Todos los datos?', {'total_rows': 1,
                                   'preview_first_page': [{'codigo': 'FAKE-1'}]}, [])
        self.assertIn('FAKE-1', result['sql'])
        self.assertEqual(provider.call_count, 2)
