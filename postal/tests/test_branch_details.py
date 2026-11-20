from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from postal.ai import PlanningError, plan_question
from postal.data import DemoSource
from postal.policy import catalog, validate_ai_sql


@override_settings(AI_PROVIDER='groq', GROQ_API_KEY='test-key')
class BranchDetailsTests(TestCase):
    previous = {
        'question': 'si',
        'sql': "SELECT p.codigo FROM assistant.paquetes_ems p LEFT JOIN assistant.users u "
               "ON p.user_id = u.id LEFT JOIN assistant.sucursales s ON u.sucursal_id = s.id "
               "WHERE LOWER(TRIM(s.departamento)) = 'santa cruz'",
        'total_rows': 562,
        'conversation': [{'question': 'dame los datos de santacruz, todos sus datos'},
                         {'question': 'si'}],
    }
    branches = {'sql': 'SELECT s.id, s."codigoSucursal", s."puntoVenta", s.municipio, '
                       's.departamento FROM assistant.sucursales s '
                       "WHERE LOWER(TRIM(s.departamento)) = 'santa cruz'",
                'title': 'Sucursales de Santa Cruz'}

    def test_branch_details_replan_instead_of_repeating_packages_joined_to_branch(self):
        before = deepcopy(self.previous)
        wrong = {'sql': self.previous['sql'], 'title': 'Paquetes EMS en Santa Cruz'}
        with patch('postal.ai._call_json', side_effect=[wrong, self.branches]) as provider:
            plan = plan_question('dame los datos de sucursal de Santa Cruz', self.previous, catalog())
        _, sources = validate_ai_sql(plan['sql'])
        self.assertEqual(sources, ['sucursales'])
        read_text = Path.read_text
        def fixtures(path, *args, **kwargs):
            content = read_text(path, *args, **kwargs)
            if path.name != 'demo.json':
                return content
            data = json.loads(content)
            data['sucursales'].append({'id': 3, 'codigoSucursal': 301, 'puntoVenta': 3,
                                      'municipio': 'Santa Cruz', 'departamento': 'SANTA CRUZ'})
            return json.dumps(data)
        with patch('postal.data.Path.read_text', autospec=True, side_effect=fixtures):
            with DemoSource().stream(plan['sql']) as result:
                rows = list(result.rows)
        self.assertTrue(rows)
        self.assertEqual(rows[0]['departamento'], 'SANTA CRUZ')
        self.assertIn('codigoSucursal', rows[0])
        self.assertNotIn('codigo', rows[0])
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(self.previous, before)

    def test_repeated_wrong_entity_is_rejected_after_one_retry(self):
        wrong = {'sql': self.previous['sql']}
        with patch('postal.ai._call_json', return_value=wrong) as provider:
            with self.assertRaises(PlanningError) as caught:
                plan_question('dame los datos de la sucursal de Santa Cruz', self.previous, catalog())
        self.assertEqual(caught.exception.code, 'invalid_plan')
        self.assertEqual(provider.call_count, 2)

    def test_branch_request_accepts_correct_entity_without_retry(self):
        with patch('postal.ai._call_json', return_value=self.branches) as provider:
            plan = plan_question('dame todos los datos de las sucursales de Santa Cruz', None, catalog())
        self.assertEqual(validate_ai_sql(plan['sql'])[1], ['sucursales'])
        self.assertEqual(provider.call_count, 1)

    def test_package_request_by_branch_keeps_package_scope(self):
        with patch('postal.ai._call_json', return_value={'sql': self.previous['sql']}) as provider:
            plan = plan_question('dame los datos de paquetes de la sucursal Santa Cruz', self.previous, catalog())
        self.assertIn('paquetes_ems', validate_ai_sql(plan['sql'])[1])
        self.assertEqual(provider.call_count, 1)

    def test_generic_branch_followup_preserves_verified_location_without_provider(self):
        with patch('postal.ai._call_json', side_effect=AssertionError('Unexpected provider')):
            plan = plan_question('dame los datos de sucursal', self.previous, catalog())
        tree, sources = validate_ai_sql(plan['sql'])
        self.assertEqual(sources, ['sucursales'])
        self.assertIn("'santa cruz'", tree.args['where'].sql())
        self.assertEqual({field.alias_or_name for field in tree.expressions},
                         {'id', 'codigoSucursal', 'puntoVenta', 'municipio', 'departamento',
                          'telefono', 'created_at', 'updated_at'})

    def test_explicit_new_location_overrides_previous_branch_location(self):
        new_branch = {**self.branches, 'sql': self.branches['sql'].replace('santa cruz', 'la paz')}
        for question in ('dame los datos de sucursal de La Paz', 'en La Paz dame los datos de sucursal'):
            with self.subTest(question=question), patch('postal.ai._call_json', return_value=new_branch) as provider:
                plan = plan_question(question, self.previous, catalog())
            self.assertIn("'la paz'", plan['sql'])
            self.assertNotIn("'santa cruz'", plan['sql'])
            self.assertEqual(provider.call_count, 1)

    def test_entity_change_does_not_carry_package_dates_or_identifiers(self):
        previous = {**self.previous, 'sql': self.previous['sql'] +
                    " AND p.created_at >= '2026-07-01' AND p.codigo = 'BO-ONE'"}
        with patch('postal.ai._call_json', side_effect=AssertionError('Unexpected provider')):
            plan = plan_question('dame los datos de sucursal', previous, catalog())
        self.assertIn("'santa cruz'", plan['sql'])
        self.assertNotIn('created_at', validate_ai_sql(plan['sql'])[0].args['where'].sql())
        self.assertNotIn('BO-ONE', plan['sql'])

    def test_package_destination_does_not_invent_branch_location(self):
        previous = {'sql': "SELECT p.codigo FROM assistant.paquetes_ems p WHERE p.ciudad = 'Santa Cruz'"}
        with patch('postal.ai._call_json', return_value=self.branches) as provider:
            plan = plan_question('dame los datos de sucursal', previous, catalog())
        self.assertEqual(validate_ai_sql(plan['sql'])[1], ['sucursales'])
        self.assertEqual(provider.call_count, 1)

    def test_typo_in_branch_followup_keeps_la_paz_from_users(self):
        previous = {
            'question': 'dame lo datos de los user de la paz',
            'sql': 'SELECT u.id, u.role_id, u.sucursal_id, COALESCE(r.nombre, r.name) AS nombre_rol '
                   'FROM assistant.users u LEFT JOIN assistant.roles r ON u.role_id = r.id '
                   'LEFT JOIN assistant.sucursales s ON u.sucursal_id = s.id '
                   "WHERE LOWER(TRIM(s.departamento)) IN ('la paz')",
        }
        with patch('postal.ai._call_json', side_effect=AssertionError('Unexpected provider')):
            plan = plan_question('dama los datos de la sucursal', previous, catalog())
        self.assertEqual(validate_ai_sql(plan['sql'])[1], ['sucursales'])
        with DemoSource().stream(plan['sql']) as result:
            rows = list(result.rows)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], 1)
        self.assertEqual(rows[0]['departamento'], 'La Paz')

    def test_branch_details_include_contact_and_record_dates(self):
        with patch('postal.ai._call_json', side_effect=AssertionError('Unexpected provider')):
            plan = plan_question('dame los datos de sucursal', self.previous, catalog())
        fields = {field.alias_or_name for field in validate_ai_sql(plan['sql'])[0].expressions}
        self.assertTrue({'telefono', 'created_at', 'updated_at'} <= fields, fields)
        self.assertNotIn('password', fields)
        self.assertNotIn('remember_token', fields)

    def test_branch_report_adds_users_and_only_linked_service_totals(self):
        context = {'sql': self.branches['sql'].replace('santa cruz', 'la paz')}
        with patch('postal.ai._call_json', side_effect=AssertionError('Unexpected provider')):
            plan = plan_question('mas dato', context, catalog())
        self.assertEqual(plan['intent'], 'report')
        self.assertEqual(len(plan['queries']), 4)
        data = []
        for query in plan['queries']:
            with DemoSource().stream(query['sql']) as result:
                data.append(list(result.rows))
        self.assertEqual(len(data[0]), 1)
        self.assertEqual(data[0][0]['departamento'], 'La Paz')
        self.assertTrue(data[1])
        self.assertTrue(all(row['sucursal_id'] == 1 for row in data[1]))
        for rows in data[2:]:
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['nombre_sucursal'], 'La Paz')
            self.assertIn('total_envios', rows[0])
        sources = {source for query in plan['queries'] for source in validate_ai_sql(query['sql'])[1]}
        self.assertIn('paquetes_ems', sources)
        self.assertIn('paquetes_contrato', sources)
        self.assertFalse({'paquetes_certi', 'paquetes_ordi', 'paquetes_int'} & sources)

    def test_report_preserves_users_without_roles_and_zero_shipments(self):
        context = {'sql': 'SELECT s.id FROM assistant.sucursales s WHERE s.id = 1'}
        with patch('postal.ai._call_json', side_effect=AssertionError('Unexpected provider')):
            plan = plan_question('más datos', context, catalog())
        fixture = {
            'sucursales': [{'id': 1, 'municipio': 'La Paz'}, {'id': 2, 'municipio': 'Cochabamba'}],
            'users': [{'id': 10, 'name': 'Usuario sin rol', 'sucursal_id': 1, 'role_id': None},
                      {'id': 11, 'sucursal_id': 1, 'role_id': None},
                      {'id': 20, 'name': 'Otra sucursal', 'sucursal_id': 2}],
            'user_roles': [{'user_id': 11, 'role_id': 1}, {'user_id': 11, 'role_id': 2}],
            'roles': [{'id': 1, 'nombre': 'Operador'}, {'id': 2, 'nombre': 'Supervisor'}],
            'paquetes_ems': [{'id': 1, 'user_id': 10, 'peso': 2, 'precio': 17},
                             {'id': 2, 'user_id': 20, 'peso': 100, 'precio': 500}],
        }
        read_text = Path.read_text
        def fixtures(path, *args, **kwargs):
            return json.dumps(fixture) if path.name == 'demo.json' else read_text(path, *args, **kwargs)
        data = []
        with patch('postal.data.Path.read_text', autospec=True, side_effect=fixtures):
            for query in plan['queries']:
                with DemoSource().stream(query['sql']) as result:
                    data.append(list(result.rows))
        self.assertEqual([(row['id'], row['nombre_rol']) for row in data[1]],
                         [(10, None), (11, 'Operador'), (11, 'Supervisor')])
        self.assertEqual(data[2][0]['total_envios'], 1)
        self.assertEqual(data[2][0]['peso_total'], 2)
        self.assertEqual(data[2][0]['precio_total'], 17)
        self.assertEqual(data[3][0]['total_envios'], 0)

    def test_model_retries_a_plan_using_the_legacy_role_column(self):
        legacy = {'sql': 'SELECT u.id, u.role_id FROM assistant.users u', 'title': 'Roles', 'chart': None}
        fixed = {**legacy, 'sql': 'SELECT u.id, a.role_id FROM assistant.users u '
                                  'LEFT JOIN assistant.user_roles a ON a.user_id = u.id'}
        with patch('postal.ai._check_provider'), patch('postal.ai._call_json', side_effect=[legacy, fixed]) as model:
            plan = plan_question('Lista los usuarios y sus roles', None, catalog())
        self.assertEqual(model.call_count, 2)
        self.assertIn('user_roles', plan['sql'])
