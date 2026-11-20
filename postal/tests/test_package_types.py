from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from postal.jobs import PAGE_SIZE, _package_type_answer
from postal.policy import catalog


class PackageTypeExplanationTests(SimpleTestCase):
    def explain(self, question, rows, *, sql=None, total=None, metadata=None):
        previous = SimpleNamespace(id='verified-result',
                                   sql=sql or 'SELECT tipo AS tipo_paquete FROM assistant.paquetes_ordi',
                                   row_count=len(rows) if total is None else total)
        with patch('postal.jobs.page_rows', return_value=rows):
            return _package_type_answer(question, previous, catalog() if metadata is None else metadata)

    def test_explanation_is_not_hardcoded_to_pg(self):
        result = self.explain('¿Qué significa XY?', [{'tipo_paquete': 'XY'}])
        self.assertIn('«XY»', result['answer'])
        self.assertNotIn('PG', result['answer'])

    def test_other_codes_and_business_requests_stay_with_planner(self):
        for question in ('¿Qué es ZZ?', '¿Cuántos PG hay?', 'Explica PG por ciudad'):
            with self.subTest(question=question):
                self.assertIsNone(self.explain(question, [{'tipo_paquete': 'PG'}]))

    def test_ambiguous_or_partial_results_do_not_resolve_pronouns(self):
        self.assertIsNone(self.explain('¿Qué significa ese tipo?', [{'tipo_paquete': 'PG'}, {'tipo_paquete': 'XY'}]))
        self.assertIsNone(self.explain('¿Qué significa ese tipo?', [{'tipo_paquete': 'PG'}], total=PAGE_SIZE + 1))

    def test_alias_cannot_turn_a_different_field_into_a_type(self):
        self.assertIsNone(self.explain('¿Qué es PG?', [{'tipo_paquete': 'PG'}],
                                      sql='SELECT codigo AS tipo_paquete FROM assistant.paquetes_ordi'))

    def test_documented_relation_is_left_for_planner_to_query(self):
        metadata = catalog()
        table = next(table for table in metadata if table['name'] == 'paquetes_ordi')
        table['relations'].append({'column': 'tipo', 'table': 'tipos', 'target': 'codigo'})
        self.assertIsNone(self.explain('¿Qué es PG?', [{'tipo_paquete': 'PG'}], metadata=metadata))

    def test_no_verified_context_does_not_claim_to_know_a_code(self):
        self.assertIsNone(_package_type_answer('¿Qué es PG?', None, catalog()))
