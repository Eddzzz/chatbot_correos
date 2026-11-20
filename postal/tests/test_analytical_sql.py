from django.test import SimpleTestCase

from postal.policy import QueryRejected, validate_ai_sql


class AnalyticalSQLTests(SimpleTestCase):
    def test_accepts_percentages_derived_from_real_counts(self):
        for expression in (
            'COUNT(*) * 100.0 / (SELECT COUNT(*) FROM assistant.paquetes_ems)',
            '100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0)',
            'ROUND(COUNT(*) * 100.0 / NULLIF(SUM(COUNT(*)) OVER (), 0), 2)',
            '100 * (COUNT(*) / CAST(SUM(COUNT(*)) OVER () AS NUMERIC))',
        ):
            with self.subTest(expression=expression):
                validate_ai_sql('SELECT estado_id, ' + expression + ' AS porcentaje '
                                'FROM assistant.paquetes_ems GROUP BY estado_id')

    def test_accepts_null_counts_without_allowing_invented_values(self):
        for expression in (
            'SUM(CASE WHEN peso IS NULL THEN 1 ELSE 0 END)',
            'SUM(CASE WHEN peso IS NOT NULL THEN 1 ELSE 0 END)',
            'COUNT(CASE WHEN peso IS NULL THEN 1 END)',
            'COUNT(CASE WHEN peso IS NULL THEN 1 ELSE NULL END)',
            'COUNT(*) FILTER (WHERE peso IS NULL)',
        ):
            with self.subTest(expression=expression):
                validate_ai_sql('SELECT ' + expression + ' AS cantidad FROM assistant.paquetes_ems')

    def test_still_rejects_fabricated_counts_offsets_and_case_values(self):
        for expression in (
            '999999 AS cantidad', 'COUNT(*) + 100 AS cantidad',
            'COUNT(*) * 100 AS cantidad', 'COUNT(*) / 100 AS cantidad',
            '100 * (COUNT(*) / 2) AS cantidad',
            'COUNT(*) * 100 / (COUNT(*) + 100) AS cantidad',
            'COUNT(*) * 999999 / COUNT(*) AS cantidad',
            'SUM(CASE WHEN peso IS NULL THEN 999999 ELSE 0 END) AS cantidad',
            'SUM(CASE WHEN 1 = 1 THEN 1 ELSE 0 END) AS cantidad',
            'CASE WHEN peso IS NULL THEN 1 ELSE 0 END AS cantidad',
            'COUNT(CASE WHEN peso IS NULL THEN 1 ELSE 0 END) AS cantidad',
            'COALESCE(peso, 99999) AS peso',
            'COUNT(*) * 100 / (SELECT COUNT(*)) AS cantidad',
        ):
            with self.subTest(expression=expression), self.assertRaises(QueryRejected):
                validate_ai_sql('SELECT ' + expression + ' FROM assistant.paquetes_ems')
