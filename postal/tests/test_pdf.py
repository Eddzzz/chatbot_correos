from django.test import SimpleTestCase
from unittest.mock import patch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table
from postal.pdf import render_pdf

class PDFTests(SimpleTestCase):
    def test_ems_report_keeps_the_calendar_and_city_detail(self):
        from io import BytesIO
        from pypdf import PdfReader

        daily = {'title': 'Envíos diarios EMS', 'columns': ['dia', 'total_envios'], 'row_count': 2,
                 'rows': [{'dia': '2026-06-01T00:00:00', 'total_envios': 98},
                          {'dia': '2026-06-03T00:00:00', 'total_envios': 0}],
                 'chart': {'kind': 'line', 'labels': ['2026-06-01T00:00:00', '2026-06-03T00:00:00'],
                           'values': [98, 0], 'label': 'Envíos'}}
        cities = {'title': 'Destinos EMS', 'columns': ['ciudad', 'total_envios', 'peso_total'],
                  'rows': [{'ciudad': 'LA PAZ', 'total_envios': 473, 'peso_total': '287.430'},
                           {'ciudad': 'ORURO', 'total_envios': 53, 'peso_total': '46.940'}],
                  'chart': {'kind': 'bar', 'view': 'horizontal', 'labels': ['LA PAZ', 'ORURO'],
                            'values': [473, 53], 'label': 'Envíos'}}
        for partial in (False, True):
            with self.subTest(partial=partial):
                data = render_pdf({'title': 'Reporte EMS de junio', 'panels': [{**daily, 'has_more': partial}, cities]})
                text = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(data)).pages)
                for expected in ('Envíos diarios EMS', 'Detalle por ciudad', '287,430', 'Destinos EMS'):
                    self.assertIn(expected, text)
                if partial:
                    self.assertIn('Detalle diario', text)
                    self.assertNotIn('Sin dato en el reporte', text)
                else:
                    self.assertIn('Junio de 2026', text)
                    self.assertIn('Sin dato en el reporte', text)
                    self.assertIn('Mié', text)
                    self.assertNotIn('2026-06-01T00:00:00', text)

    def test_charts_follow_the_chat_views_and_include_their_annotations(self):
        from io import BytesIO
        from pypdf import PdfReader

        cases = [
            ('horizontal', ['La Paz', 'Sin departamento'], [12, -3], ('-3',)),
            ('bar', ['La Paz', 'Beni'], [12, 3], ('movimientos · 2 categorías',)),
            ('doughnut', ['La Paz', 'Beni'], [12, 3], ('80%', '20%', 'Total')),
            ('pie', ['La Paz', 'Beni'], [12, 3], ('80%', '20%')),
            ('line', ['2026-06-01', '2026-07-01', 'Sin dato'], [12, 3, 2],
             ('jun 2026', 'jul 2026', 'Sin fecha: 2')),
            ('horizontal', ['La Paz'], [12], ('Movimientos', '12')),
        ]
        for view, labels, values, expected in cases:
            with self.subTest(view=view, values=values):
                # The table has different cell text so it can't satisfy the chart assertions.
                result = {'title': 'Actividad postal', 'columns': ['detalle'], 'rows': [{'detalle': 'Datos verificados'}],
                          'answer': 'Resumen visible.\n\nSegunda línea.',
                          'chart': {'kind': 'line' if view == 'line' else 'bar', 'view': view,
                                    'labels': labels, 'values': values, 'label': 'Movimientos'}}
                data = render_pdf(result)
                pages = PdfReader(BytesIO(data)).pages
                text = '\n'.join(page.extract_text() for page in pages)
                for label in (*expected, 'Datos verificados'):
                    self.assertIn(label, text)
                self.assertLess(text.index('Segunda línea.'), text.index(expected[0]))
                self.assertLess(text.index(expected[0]), text.index('Datos verificados'))

    def test_long_rankings_preserve_all_chart_categories_across_pages(self):
        from io import BytesIO
        from pypdf import PdfReader

        labels = [f'Categoría {index:03}' for index in range(100)]
        pdf = render_pdf({'title': 'Ranking de destinos', 'chart': {'kind': 'bar', 'view': 'horizontal',
                         'labels': labels, 'values': list(range(100)), 'label': 'Envíos'}})
        pages = PdfReader(BytesIO(pdf)).pages
        self.assertGreater(len(pages), 1)
        text = '\n'.join(page.extract_text() for page in pages)
        for label in labels:
            self.assertEqual(text.count(label), 1)

    def test_complete_scalar_result_uses_a_metric_without_a_table(self):
        from io import BytesIO
        from pypdf import PdfReader

        result = {'title': 'Total de envíos', 'status': 'ok', 'columns': ['total_envios'],
                  'rows': [{'total_envios': 1436}], 'row_count': 1}
        with patch('postal.pdf.LongTable') as table:
            data = render_pdf(result)
        table.assert_not_called()
        self.assertIn('1.436', PdfReader(BytesIO(data)).pages[0].extract_text())

    def test_generated_sql_filters_are_not_printed_in_reader_report(self):
        result = {'title': 'Envíos de Beni', 'columns': ['id', 'codigo'],
                  'rows': [{'id': 7, 'codigo': 'BO-001'}], 'row_count': 1,
                  'filters': {'fuentes': ['paquetes_ems'], 'condiciones': ['LOWER(TRIM(ciudad)) IN (\'beni\')']},
                  'answer': 'Envíos registrados en Beni.\nFuente: Paquetes EMS · id · fila 1'}
        with patch('postal.pdf.Paragraph', wraps=Paragraph) as paragraphs:
            render_pdf(result)
        text = '\n'.join(str(call.args[0]) for call in paragraphs.call_args_list)
        self.assertNotIn('LOWER(TRIM', text)
        self.assertNotIn('Fuente: Paquetes EMS', text)
        self.assertIn('Envíos registrados en Beni.', text)
        self.assertNotIn('Filtros de la consulta aplicados.', text)

    def test_export_omits_technical_metadata_for_all_panel_modes(self):
        panel = {'title': 'Envíos', 'columns': ['codigo'], 'rows': [{'codigo': 'BO-001'}],
                 'row_count': 261, 'page': 1, 'source_tables': ['sucursales', 'paquetes_ems'],
                 'filters': {'servicio': 'EMS', 'condiciones': ['ciudad = Trinidad']}}
        for panels in ([], [panel, {**panel, 'title': 'Sin resultados', 'rows': [], 'row_count': 0}]):
            with self.subTest(multiple=bool(panels)):
                with patch('postal.pdf.Paragraph', wraps=Paragraph) as paragraphs:
                    render_pdf({**panel, 'panels': panels, 'created_at': '2026-11-10T14:13:00-04:00'})
                text = '\n'.join(str(call.args[0]) for call in paragraphs.call_args_list)
                for forbidden in ('Alcance:', 'Consulta:', 'Página de resultados', 'filas exportadas',
                                  'Origen:', 'Filtros:', 'Filtros de la consulta aplicados.', 'paquetes_ems'):
                    self.assertNotIn(forbidden, text)
                self.assertIn('BO-001', text)

    def test_wide_shipment_tables_repeat_identifiers_in_every_group(self):
        from reportlab.platypus import LongTable
        columns = ['id', 'origen', 'tipo_correspondencia', 'cantidad', 'peso', 'codigo',
                   'precio', 'ciudad', 'created_at', 'updated_at', 'user_id', 'estado_id']
        rows = [{column: f'{column}-{index}' for column in columns} for index in range(2)]
        with patch('postal.pdf.LongTable', wraps=LongTable) as tables:
            render_pdf({'title': 'Beni', 'columns': columns, 'rows': rows, 'row_count': 2})
        for call in tables.call_args_list:
            cells = call.args[0]
            headers = [cell.getPlainText() for cell in cells[0]]
            self.assertIn('Identificador', headers)
            self.assertIn('Código', headers)
            self.assertIn('id-1', [cell.getPlainText() for cell in cells[2]])
            self.assertIn('codigo-1', [cell.getPlainText() for cell in cells[2]])
        for column in columns:
            self.assertTrue(any(f'{column}-1' == cell.getPlainText()
                                for call in tables.call_args_list for cell in call.args[0][2]))

    def test_export_uses_spanish_headers_and_preserves_values(self):
        from reportlab.platypus import LongTable
        result = {'title': 'Envíos', 'error': None, 'chart': {'kind': 'bar'}, 'columns': ['id', 'codigo', 'created_at', 'updated_at'],
                  'rows': [{'id': 7, 'codigo': 'BO-001', 'created_at': '2026-11-10', 'updated_at': None}],
                  'row_count': 1}
        with patch('postal.pdf.LongTable', wraps=LongTable) as table:
            render_pdf(result)
        cells = table.call_args.args[0]
        self.assertEqual([cell.getPlainText() for cell in cells[0]],
                         ['Identificador', 'Código', 'Fecha de creación', 'Fecha de actualización'])
        self.assertEqual([cell.getPlainText() for cell in cells[1]], ['7', 'BO-001', '2026-11-10', '—'])

    def test_single_records_follow_chat_layout_without_column_groups(self):
        from io import BytesIO
        from pypdf import PdfReader
        from reportlab.platypus import LongTable
        columns = ['id', 'codigoSucursal', 'puntoVenta', 'municipio', 'departamento',
                   'telefono', 'created_at', 'updated_at']
        record = {'title': 'Datos de sucursal', 'columns': columns,
                  'rows': [dict(zip(columns, [1, 'LA PAZ', 0, 'LA PAZ', 'LA PAZ',
                                              '2152423', '2026-06-25T15:50:17', None]))]}
        users = {'title': 'Usuarios', 'columns': ['id', 'nombre'],
                 'rows': [{'id': 16, 'nombre': 'Usuario uno'}, {'id': 17, 'nombre': 'Usuario dos'}]}
        with patch('postal.pdf.LongTable', wraps=LongTable) as tables:
            data = render_pdf({'title': 'Información completa', 'panels': [record, users]})
        self.assertEqual(tables.call_count, 1)
        reader = PdfReader(BytesIO(data))
        self.assertLess(reader.pages[0].mediabox.width, reader.pages[0].mediabox.height)
        text = '\n'.join(page.extract_text() for page in reader.pages)
        self.assertNotIn('Grupo de columnas', text)
        for expected in ('2152423', '2026-06-25T15:50:17', 'Usuario uno', 'Usuario dos', '—'):
            self.assertIn(expected, text)

    def test_spanish_and_user_text_render_as_document_not_markup(self):
        data = render_pdf({'title': 'Envíos y sucursales', 'answer': 'Información verificada.',
            'source_tables': ['sucursales'], 'filters': {'departamento': 'La Paz'}, 'page': 1,
            'row_count': 1, 'created_at': '2026-11-05T12:00:00-04:00', 'demo': True,
            'columns': ['ciudad', 'texto'], 'rows': [{'ciudad': 'Oruro', 'texto': '<b>Ñandú & recepción</b>'}]})
        self.assertTrue(data.startswith(b'%PDF-'))
        self.assertGreater(len(data), 1000)

    def test_report_exports_each_visible_panel_once_with_its_values(self):
        panel = {'index': 0, 'title': 'Por servicio', 'columns': ['servicio', 'total'],
                 'rows': [{'servicio': 'EMS', 'total': 12}], 'row_count': 12, 'page': 2,
                 'source_tables': ['envios_ems'], 'filters': {'gestion': 2025}}
        second = {'index': 1, 'title': 'Por estado', 'columns': ['estado', 'total'],
                  'rows': [{'estado': '<b>Recepción & revisión</b>', 'total': 7}], 'row_count': 7,
                  'page': 1, 'source_tables': ['movimientos'], 'filters': {'servicio': 'EMS'}}
        result = {**panel, 'title': 'Informe postal', 'answer': 'Resumen verificado.\n\nFuentes: envios_ems y movimientos.',
                  'panels': [panel, second], 'analysis': {'generated': True}}
        text = []
        original_build = SimpleDocTemplate.build

        def capture_build(doc, story, **kwargs):
            def collect(item):
                if isinstance(item, Paragraph):
                    text.append(item.getPlainText())
                elif isinstance(item, Table):
                    for row in item._cellvalues:
                        for cell in row:
                            for child in cell if isinstance(cell, (tuple, list)) else [cell]:
                                collect(child)
            for item in story:
                collect(item)
            return original_build(doc, story, **kwargs)

        with patch.object(SimpleDocTemplate, 'build', capture_build):
            data = render_pdf(result)
        self.assertTrue(data.startswith(b'%PDF-'))
        self.assertEqual(text.count('Por servicio'), 1)
        self.assertEqual(text.count('Por estado'), 1)
        combined = '\n'.join(text)
        self.assertIn('Resumen verificado.', combined)
        for forbidden in ['Fuentes: envios_ems y movimientos.', 'Análisis de IA',
                          'CONTENIDO DEL DOCUMENTO', 'filas visibles']:
            self.assertNotIn(forbidden, combined)
        for expected in ['EMS', '12', '7', '<b>Recepción & revisión</b>']:
            self.assertIn(expected, combined)

    def test_single_panel_has_one_title_and_includes_verified_summary(self):
        title = 'Datos de sucursales de la ubicación consultada'
        panel = {'title': title, 'columns': ['id', 'municipio'],
                 'rows': [{'id': 1, 'municipio': 'LA PAZ'}]}
        for generated in (True, False):
            with self.subTest(generated=generated):
                with patch('postal.pdf.Paragraph', wraps=Paragraph) as paragraphs:
                    render_pdf({**panel, 'panels': [panel], 'answer': 'id: 1; municipio: LA PAZ',
                                'analysis': {'generated': generated, 'warning': 'Datos incompletos.'}})
                texts = [call.args[0] for call in paragraphs.call_args_list]
                self.assertEqual(texts.count(title), 1)
                self.assertIn('id: 1; municipio: LA PAZ', texts)
                for forbidden in ('Análisis de IA', 'Resumen del informe',
                                  'FECHA DE EXPORTACIÓN', 'CONTENIDO DEL DOCUMENTO'):
                    self.assertNotIn(forbidden, texts)
                self.assertIn('Datos incompletos.', texts)
                self.assertIn('LA PAZ', texts)

    def test_wide_multipage_report_preserves_all_column_groups(self):
        columns = [f'campo_{index}' for index in range(11)]
        result = {'title': 'Informe extenso', 'columns': columns,
                  'rows': [{key: f'{key}: recepción <verificada> ' * 8 for key in columns} for _ in range(65)],
                  'row_count': 130, 'page': 2}
        from reportlab.platypus import LongTable
        with patch('postal.pdf.LongTable', wraps=LongTable) as table:
            data = render_pdf(result)
        self.assertTrue(data.startswith(b'%PDF-'))
        self.assertEqual(table.call_count, 3)
        self.assertEqual(sum(len(call.args[0][0]) for call in table.call_args_list), len(columns))
        self.assertTrue(all(len(call.args[0]) == 66 for call in table.call_args_list))
