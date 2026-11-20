from django.test import SimpleTestCase
from postal.labels import COLUMN_LABELS, column_label
from postal.policy import SAFE_COLUMNS


class ColumnLabelTests(SimpleTestCase):
    def test_every_queryable_field_has_an_explicit_spanish_label(self):
        fields = {column for columns in SAFE_COLUMNS.values() for column in columns}
        self.assertEqual(fields - COLUMN_LABELS.keys(), set())

    def test_aliases_are_readable_without_changing_result_keys(self):
        for key, label in [('total_shipments', 'Total envíos'), ('codigo_envio', 'Código envío'),
                           ('promedio_peso', 'Peso promedio'), ('municipio_sucursal', 'Municipio sucursal')]:
            with self.subTest(key=key):
                self.assertEqual(column_label(key), label)
