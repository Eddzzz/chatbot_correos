import copy

from django.test import SimpleTestCase
from sqlglot import exp

from postal.ai import _normalize_location_filters
from postal.context import compress_context
from postal.policy import validate_ai_sql


class GeographicContextTests(SimpleTestCase):
    def compress(self, question, context):
        return compress_context(question, context, normalize_location_sql=_normalize_location_filters)

    def assert_same_predicates(self, actual_sql, expected_sql):
        def without_parens(node):
            while isinstance(node, exp.Paren):
                node = node.this
            return node
        actual, _ = validate_ai_sql(actual_sql)
        expected, _ = validate_ai_sql(expected_sql)
        self.assertEqual(actual.transform(without_parens), expected.transform(without_parens))

    def test_expanded_department_preserves_dates_identifiers_and_unknown_row_references(self):
        original_sql = """SELECT p.codigo, p.created_at FROM assistant.paquetes_certi AS p
            WHERE p.cuidad = 'La Paz' AND p.created_at >= '2026-09-01'
            AND p.created_at < '2026-10-01' AND p.codigo <> 'BO-KEEP'
            ORDER BY p.codigo LIMIT 100"""
        expanded = _normalize_location_filters(original_sql)
        context = {'sql': expanded, 'total_rows': 2,
                   'preview_first_page': [{'codigo': 'BO-1'}, {'codigo': 'BO-2'}],
                   'preview_is_partial': False,
                   'filters': {'fuentes': ['paquetes_certi', 'sucursales'], 'condiciones': [expanded]},
                   'report_panels': [{'sql': expanded, 'row_count': 2, 'title': 'Certificado'}]}
        before = copy.deepcopy(context)

        sent = self.compress('Todos los datos del segundo', context)

        self.assertLess(len(sent['sql']), 700)
        self.assertIn("p.cuidad = 'la paz'", sent['sql'])
        for exact in ("'2026-09-01'", "'2026-10-01'", "p.codigo <> 'BO-KEEP'", 'ORDER BY p.codigo', 'LIMIT 100'):
            self.assertIn(exact, sent['sql'])
        self.assertEqual(sent['preview_first_page'], context['preview_first_page'])
        self.assertNotIn('sql', sent['report_panels'][0])
        self.assert_same_predicates(_normalize_location_filters(sent['sql']), expanded)
        self.assertEqual(context, before)

    def test_partial_department_predicate_is_never_replaced_with_full_department(self):
        expanded = _normalize_location_filters("SELECT p.codigo FROM assistant.paquetes_certi p WHERE p.cuidad = 'La Paz'")
        altered = expanded.replace("LIKE 'achacachi-%'", "LIKE 'custom-%'", 1)

        sent = self.compress('agosto', {'sql': altered})

        self.assertEqual(sent['sql'], altered)

    def test_compaction_preserves_boolean_scope_across_union_and_negation(self):
        original = """SELECT p.codigo FROM assistant.paquetes_certi p
            WHERE NOT (p.cuidad = 'Pando') AND p.created_at >= '2026-09-01'
            UNION ALL SELECT e.codigo FROM assistant.paquetes_ems e
            WHERE e.ciudad = 'Oruro' OR e.codigo = 'BO-ALWAYS'"""
        expanded = _normalize_location_filters(original)

        sent = self.compress('agosto', {'sql': expanded})

        self.assertLess(len(sent['sql']), 600)
        self.assert_same_predicates(_normalize_location_filters(sent['sql']), expanded)

    def test_unknown_location_is_left_intact(self):
        sql = "SELECT codigo FROM assistant.paquetes_certi WHERE cuidad = 'Villa Nube Postal'"
        self.assertEqual(self.compress('agosto', {'sql': sql})['sql'], sql)

    def test_multiple_locations_are_not_collapsed_into_the_first_location(self):
        expanded = _normalize_location_filters(
            "SELECT codigo FROM assistant.paquetes_certi WHERE cuidad IN ('Pando', 'Oruro')")
        sent = self.compress('agosto', {'sql': expanded})
        self.assertEqual(sent['sql'], expanded)

    def test_historical_result_gets_the_same_safe_compaction(self):
        expanded = _normalize_location_filters(
            "SELECT codigo FROM assistant.paquetes_certi WHERE cuidad = 'La Paz'")
        sent = self.compress('El segundo de aquel resultado', {'historical_result': {
            'sql': expanded, 'preview_first_page': [{'codigo': 'HISTORY-2'}]}})
        historical = sent['historical_result']
        self.assertLess(len(historical['sql']), 200)
        self.assertEqual(historical['preview_first_page'], [{'codigo': 'HISTORY-2'}])
        self.assert_same_predicates(_normalize_location_filters(historical['sql']), expanded)

