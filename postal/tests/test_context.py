import copy
import json
from unittest.mock import patch

from django.test import TestCase, override_settings

from postal.ai import compose_response, plan_question


@override_settings(AI_PROVIDER='groq', GROQ_API_KEY='test-key')
class ContextCompressionTests(TestCase):
    def test_explanation_followup_recognizes_interpretation_but_not_new_scopes(self):
        from postal.context import explanation_followup
        for question in ['dame una explicacion de eso', 'dame una explicaion de eso', 'dame una explaicion de eso', 'explícame más', 'amplía', 'desarrolla el consejo',
                         'dame un consejo sobre el gráfico', 'más detalle']:
            with self.subTest(question=question):
                self.assertTrue(explanation_followup(question))
        for question in ['dame una explicación de Santa Cruz en 2026', 'resumen de EMS de enero',
                         'amplía a todas las ciudades', 'borra los paquetes', 'exploración de eso']:
            with self.subTest(question=question):
                self.assertFalse(explanation_followup(question))
    def test_private_archive_and_redundant_scope_are_not_sent(self):
        from postal.context import compress_context, settled_state
        state = settled_state('Lista EMS', 'first')
        state = settled_state('solo CERTIFICADO', 'second', state)
        sent = compress_context('2026', {'state': state, 'total_rows': 10})
        self.assertNotIn('results', sent['state'])
        self.assertNotIn('scope', sent['state'])

    def test_planner_receives_three_recent_turns_and_pending_request_state(self):
        history = [{'question': 'Informe de junio por departamentos', 'clarification': '¿Año?'},
                   *[{'question': str(year), 'clarification': '¿Servicio?'} for year in range(2020, 2027)]]
        with patch('postal.ai._call_json', return_value={'sql': 'SELECT COUNT(*) FROM assistant.paquetes_ems'}) as provider:
            plan_question('Solo EMS', {'conversation': history}, [])
        sent = json.loads(provider.call_args.args[0]['messages'][1]['content'])['previous_verified_context']
        self.assertEqual(len(sent['conversation']), 3)
        self.assertEqual(sent['state']['request'], history[0]['question'])
        self.assertEqual(sent['state']['updates']['year'], '2026')

    def test_planner_drops_rows_for_filter_change_and_deduplicates_primary_sql(self):
        sql = 'SELECT codigo FROM assistant.paquetes_ems ORDER BY codigo'
        context = {'question': 'Lista EMS', 'sql': sql, 'total_rows': 80,
                   'filters': {'fuentes': ['paquetes_ems'], 'condiciones': []},
                   'source_tables': ['paquetes_ems'],
                   'preview_first_page': [{'codigo': 'X' * 200} for _ in range(20)],
                   'preview_is_partial': True,
                   'report_panels': [{'sql': sql, 'title': 'EMS', 'filters': {'fuentes': ['paquetes_ems'], 'condiciones': []}, 'row_count': 80}]}
        original = copy.deepcopy(context)
        with patch('postal.ai._call_json', return_value={'sql': sql}) as provider:
            plan_question('Ahora solo CERTIFICADO', context, [])
        content = provider.call_args.args[0]['messages'][1]['content']
        sent = json.loads(content)['previous_verified_context']
        self.assertNotIn('preview_first_page', sent)
        self.assertEqual(content.count(sql), 1)
        self.assertLess(len(json.dumps(sent)), len(json.dumps(context)) // 2)
        self.assertEqual(context, original)
        self.assertNotIn(': ', content)

    def test_unknown_followup_keeps_row_references_and_exact_values(self):
        context = {'total_rows': 2, 'preview_first_page': [{'codigo': 'BO-1'}, {'codigo': 'BO-2'}]}
        with patch('postal.ai._call_json', return_value={'sql': 'SELECT codigo FROM assistant.paquetes_ems'}) as provider:
            plan_question('Todos los datos del segundo', context, [])
        sent = json.loads(provider.call_args.args[0]['messages'][1]['content'])['previous_verified_context']
        self.assertEqual(sent['preview_first_page'], context['preview_first_page'])

    def test_state_retains_anchor_and_latest_corrections_beyond_recent_window(self):
        from postal.context import advance_state
        state = {}
        for question in ['Movimientos en la primera semana de junio por departamentos', '2024', 'solo EMS',
                         '2025', 'solo CERTIFICADO', '2026', 'todo']:
            state = advance_state(state, question, '¿Qué año?')
        self.assertEqual(state['request'], 'Movimientos en la primera semana de junio por departamentos')
        self.assertEqual(state['updates']['year'], '2026')
        self.assertEqual(state['updates']['service'], 'solo CERTIFICADO')
        self.assertEqual(len(state['recent']), 3)
        self.assertEqual(state['pending_clarification'], '¿Qué año?')
        self.assertNotIn('2024', json.dumps(state))

    def test_ambiguous_or_unrecognized_constraints_are_not_discarded(self):
        from postal.context import advance_state
        state = advance_state({}, 'Compara paquetes EMS')
        state = advance_state(state, 'Excluye los devueltos y conserva el origen')
        state = advance_state(state, '2026')
        self.assertIn('Excluye los devueltos y conserva el origen', state['notes'])

    def test_analyst_preserves_complete_small_results_and_compacts_large_samples(self):
        panels = [{'title': 'Distribución', 'columns': ['ciudad', 'total'], 'row_count': 9,
                   'rows': [{'ciudad': str(i), 'total': i} for i in range(9)]},
                  {'title': 'Listado', 'columns': ['codigo', 'detalle'], 'row_count': 500,
                   'rows': [{'codigo': str(i), 'detalle': 'x' * 1800} for i in range(100)]}]
        original = copy.deepcopy(panels)
        with patch('postal.ai._call_json', return_value={'paragraphs': [
                {'kind': 'maximum', 'references': [{'panel': 0, 'row': 8, 'column': 'total'}]}]}) as provider:
            result = compose_response('Resume los resultados', 'report', panels)
        content = provider.call_args.args[0]['messages'][1]['content']
        evidence = json.loads(content)['verified_evidence']
        self.assertTrue(evidence[0]['complete'])
        self.assertEqual(len(evidence[0]['rows']), 9)
        self.assertFalse(evidence[1]['complete'])
        self.assertLessEqual(len(content), 26000)
        self.assertEqual(result['citations'][0]['row'], 8)
        self.assertEqual(panels, original)

    def test_complete_aggregate_larger_than_twenty_rows_keeps_its_maximum(self):
        panels = [{'title': 'Categorías', 'columns': ['categoria', 'total'], 'row_count': 21,
                   'rows': [{'categoria': str(index), 'total': index} for index in range(21)]}]
        with patch('postal.ai._call_json', return_value={'paragraphs': [
                {'kind': 'maximum', 'references': [{'panel': 0, 'row': 20, 'column': 'total'}]}]}) as provider:
            result = compose_response('¿Cuál es el máximo?', 'answer', panels)
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(result['citations'][0]['row'], 20)

    def test_provider_logs_only_usage_counts_and_stage(self):
        import httpx
        from postal.ai import _request_json
        real_client = httpx.Client
        def respond(request):
            return httpx.Response(200, json={'usage': {'prompt_tokens': 123, 'completion_tokens': 12, 'total_tokens': 135},
                'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}]})
        with patch('postal.ai.httpx.Client', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)):
            with self.assertLogs('postal.ai', level='INFO') as logs:
                _request_json({'messages': [{'role': 'system', 'content': 'Eres el planificador SQL'},
                                           {'role': 'user', 'content': 'PRIVATE-QUESTION'}]},
                              ('Groq', 'PRIVATE-KEY', 'https://example.test/chat', 'test-model'))
        logged = '\n'.join(logs.output)
        self.assertIn('prompt_tokens=123', logged)
        self.assertIn('stage=planner', logged)
        self.assertNotIn('PRIVATE', logged)
