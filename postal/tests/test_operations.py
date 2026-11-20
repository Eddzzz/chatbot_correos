from postal.tests.demo_fixtures import demo_fixtures
from django.test import SimpleTestCase, override_settings
from postal.data import Cancellation, get_source
from postal.operations import dashboard_plan, tracking_plan
from unittest.mock import patch

@override_settings(DATA_MODE='demo')
class OperationTests(SimpleTestCase):
    def test_service_and_month_followups_keep_orphan_movements_and_the_week(self):
        from postal.operations import movement_report
        source = get_source()
        root = 'Dame el movimiento de paquetes de la primera semana de junio por departamentos.'
        service = 'Ahora solo EMS, mantén las mismas fechas y el desglose por departamentos.'
        month = 'Cambia únicamente el mes a julio; conserva el año, servicio y desglose.'
        fixtures = {'paquetes_ems': [{'id': 1, 'codigo': 'KNOWN'}],
                    'eventos_ems': [{'id': 1, 'codigo': 'KNOWN', 'created_at': '2026-06-02'},
                                    {'id': 2, 'codigo': 'ORPHAN', 'created_at': '2026-06-03'},
                                    {'id': 3, 'codigo': 'ORPHAN', 'created_at': '2026-07-02'}]}
        for question, history, start, end, count in (
                (service, [root, '2026'], '2026-06-01', '2026-06-08', 2),
                (month, [root, '2026', service], '2026-07-01', '2026-07-08', 1)):
            with self.subTest(question=question):
                plan = movement_report(question, source.catalog(), history)
                self.assertIsNotNone(plan)
                query = plan['queries'][0]
                self.assertEqual(query['params'], [start, end])
                self.assertIn('eventos_ems', query['sql'])
                self.assertNotIn('eventos_certi', query['sql'])
                with demo_fixtures(fixtures), source.stream(query['sql'], query['params']) as result:
                    self.assertEqual(sum(row['total_movimientos'] for row in result.rows), count)

    def test_movement_followup_does_not_cross_an_unrelated_topic(self):
        from postal.operations import movement_report
        root = 'Movimiento de paquetes la primera semana de junio de 2026 por departamentos'
        self.assertIsNone(movement_report('Ahora solo EMS', get_source().catalog(), [root, 'Dame los datos del paquete ABC']))

    def test_year_followup_keeps_movement_report_filters(self):
        from postal.operations import movement_report
        source = get_source()
        root = 'Movimiento de paquetes que hice la primera semana de junio por departamentos'
        for question in ('2025', 'del 2025', 'de 2025', 'del año 2025'):
            with self.subTest(question=question):
                plan = movement_report(question, source.catalog(), [root, '2024'])
                self.assertIsNotNone(plan)
                self.assertIn('junio de 2025', plan['title'])
                for query in plan['queries']:
                    self.assertEqual(query['params'], ['2025-06-01', '2025-06-08'] * (len(query['params']) // 2))
        self.assertIsNone(movement_report('del 2025', source.catalog(), [root, 'Dame los datos del paquete ABC']))

    def test_movement_report_counts_event_dates_once_and_keeps_missing_departments(self):
        from postal.operations import movement_report
        from postal.data import DemoSource
        fixtures = {
            'sucursales': [{'id': 1, 'departamento': 'LA PAZ'}, {'id': 2, 'departamento': 'BENI'},
                           {'id': 3, 'departamento': '   '}],
            'users': [{'id': 1, 'sucursal_id': 1}, {'id': 2, 'sucursal_id': 2}, {'id': 3, 'sucursal_id': 3}],
            'paquetes_ems': [{'id': 1, 'codigo': 'OLD', 'user_id': 1, 'created_at': '2025-01-01'},
                             {'id': 2, 'codigo': 'DUP', 'user_id': 1}, {'id': 3, 'codigo': 'DUP', 'user_id': 1},
                             {'id': 4, 'codigo': 'AMB', 'user_id': 1}, {'id': 5, 'codigo': 'AMB', 'user_id': 2},
                             {'id': 6, 'codigo': 'BLANK', 'user_id': 3}],
            'eventos_ems': [{'id': 1, 'codigo': 'OLD', 'created_at': '2026-06-01T00:00:00'},
                            {'id': 2, 'codigo': 'OLD', 'created_at': '2026-06-07T23:59:59'},
                            {'id': 3, 'codigo': 'DUP', 'created_at': '2026-06-04'},
                            {'id': 4, 'codigo': 'AMB', 'created_at': '2026-06-04'},
                            {'id': 5, 'codigo': 'ORPHAN', 'created_at': '2026-06-04'},
                            {'id': 6, 'codigo': 'BLANK', 'created_at': '2026-06-04'},
                            {'id': 7, 'codigo': 'OLD', 'created_at': '2026-06-08T00:00:00'},
                            {'id': 8, 'codigo': 'OLD', 'created_at': '2026-05-31T23:59:59'}],
            'paquetes_certi': [{'id': 1, 'codigo': 'CERT', 'cuidad': 'TRINIDAD'}],
            'eventos_certi': [{'id': 1, 'codigo': 'CERT', 'created_at': '2026-06-03'}],
        }
        source = DemoSource()
        plan = movement_report('Movimiento de paquetes la primera semana de junio de 2026 por departamentos', source.catalog())
        with demo_fixtures(fixtures):
            with source.stream(plan['queries'][0]['sql'], plan['queries'][0]['params']) as stream:
                rows = {row['departamento']: row for row in stream.rows}
        self.assertEqual(sum(row['total_movimientos'] for row in rows.values()), 7)
        self.assertEqual(rows['LA PAZ']['total_movimientos'], 3)
        self.assertEqual(rows['Sin departamento']['total_movimientos'], 4)
        self.assertEqual(rows['LA PAZ']['codigos_con_movimientos'], 2)
        self.assertNotIn('BENI', rows)
        self.assertIn('INTERNACIONAL', plan['note'])

    def test_movement_report_keeps_week_when_year_is_a_followup(self):
        from postal.operations import movement_report
        from postal.data import DataError
        source = get_source()
        question = 'Movimiento de paquetes que hice la primera semana de junio por departamentos'
        with self.assertRaises(DataError) as caught:
            movement_report(question, source.catalog())
        self.assertEqual(caught.exception.code, 'clarification')
        plan = movement_report('2026', source.catalog(), [question])
        self.assertEqual(plan['queries'][0]['params'][:2], ['2026-06-01', '2026-06-08'])
        self.assertIsNone(movement_report('Solo mis paquetes la primera semana de junio de 2026 por departamentos', source.catalog()))
        self.assertIsNone(movement_report('Otra pregunta sobre oficinas', source.catalog(), [question, '2026']))

    def test_dashboard_count_matches_complete_demo_set(self):
        source = get_source()
        plan = dashboard_plan('envios_por_servicio', source.catalog())
        with source.stream(plan['sql']) as stream:
            rows = list(stream.rows)
        ems = next(row for row in rows if row['servicio'] == 'EMS')
        self.assertEqual(ems['cantidad'], 80)

    def test_duplicate_tracking_returns_candidates_before_events(self):
        plan = tracking_plan('BO-DEMO-001', None, get_source(), Cancellation())
        self.assertTrue(plan['filters']['choose_service'])
        with get_source().stream(plan['sql'], plan['params']) as stream:
            self.assertGreater(len(list(stream.rows)), 1)

    def test_selected_service_only_returns_its_own_movements(self):
        plan = tracking_plan('BO-DEMO-001', 'EMS', get_source(), Cancellation())
        with get_source().stream(plan['sql'], plan['params']) as stream:
            rows = list(stream.rows)
        self.assertGreater(len(rows), 1)
        self.assertEqual({row['servicio'] for row in rows}, {'EMS'})

    def test_unknown_code_does_not_create_events(self):
        plan = tracking_plan('NO-EXISTE', None, get_source(), Cancellation())
        with get_source().stream(plan['sql'], plan['params']) as stream:
            self.assertEqual(list(stream.rows), [])
