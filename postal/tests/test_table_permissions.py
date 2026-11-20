from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from postal.data import DemoSource
from postal.policy import QueryRejected, catalog, validate_sql
from postal.system_config import configuration, save_config


@override_settings(DATA_MODE='demo', JOBS_EAGER=True)
class TablePermissionsTests(TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        settings = override_settings(SYSTEM_CONFIG_PATH=Path(folder.name) / 'settings.json', RESULT_DIR=Path(folder.name) / 'results')
        settings.enable()
        self.addCleanup(settings.disable)
        self.admin = get_user_model().objects.create_superuser('table-admin', password='test-pass')
        self.client.force_login(self.admin)

    def toggle(self, table, enabled):
        return self.client.post('/system/?view=tables', {'action': 'table_toggle', 'table': table, 'enabled': str(int(enabled))})

    def save_columns(self, table, columns):
        return self.client.post('/system/?view=tables', {'action': 'table_columns', 'table': table, 'columns': columns})

    def test_columns_can_be_authorized_and_protected_in_sql(self):
        self.assertEqual(self.save_columns('users', ['id', 'role_id', 'ciudad']).status_code, 302)
        validate_sql('SELECT ciudad FROM assistant.users')
        self.assertEqual(self.save_columns('users', ['id', 'role_id']).status_code, 302)
        with self.assertRaises(QueryRejected):
            validate_sql('SELECT ciudad FROM assistant.users')
        with self.assertRaises(QueryRejected):
            validate_sql("SELECT id FROM assistant.users WHERE ciudad='La Paz'")

    def test_failed_field_preparation_does_not_grant_access(self):
        with override_settings(DATA_MODE='postgres', BUSINESS_USE_ISOLATED_VIEWS=True), patch('postal.table_permissions.prepare_table', side_effect=ValueError('Preparación fallida')):
            self.assertEqual(self.save_columns('users', ['id', 'ciudad']).status_code, 302)
        with self.assertRaises(QueryRejected):
            validate_sql('SELECT ciudad FROM assistant.users')

    def test_credentials_and_unknown_columns_cannot_be_authorized(self):
        for columns in (['id', 'password'], ['id', 'remember_token'], ['id', 'name'], ['id', 'alias'], ['id', 'email'], ['id', 'ci'], ['id', 'inventada']):
            with self.subTest(columns=columns):
                self.assertEqual(self.save_columns('users', columns).status_code, 400)
        with self.assertRaises(QueryRejected):
            validate_sql('SELECT password FROM assistant.users')

    def test_default_projections_contain_no_permanently_locked_fields(self):
        from postal.policy import available_columns, configurable_columns
        editable = configurable_columns()
        for name, columns in available_columns().items():
            with self.subTest(table=name):
                self.assertTrue(set(columns) <= set(editable[name]))

    def test_physical_table_counts_exclude_the_derived_role_source(self):
        response = self.client.get('/system/?view=tables')
        self.assertEqual(response.context['table_counts'], {'total': 122, 'allowed': 16, 'blocked': 106})
        self.assertContains(response, 'Fuente derivada')

    @override_settings(DATA_MODE='postgres', BUSINESS_USE_ISOLATED_VIEWS=False)
    def test_production_permission_updates_are_local(self):
        with patch('postal.table_permissions.prepare_table') as prepare:
            self.assertEqual(self.toggle('auditoria', True).status_code, 302)
            self.assertEqual(self.save_columns('auditoria', ['id']).status_code, 302)
        prepare.assert_not_called()
        validate_sql('SELECT id FROM assistant.auditoria')

    def test_fields_editor_lists_selected_and_locked_fields(self):
        response = self.client.get('/system/?view=tables&edit_fields=users')
        self.assertContains(response, 'Editar campos de users')
        self.assertContains(response, 'name="columns" value="role_id" checked')
        self.assertContains(response, 'Protección obligatoria')

    def test_editing_fields_does_not_enable_a_blocked_table(self):
        self.toggle('users', False)
        self.save_columns('users', ['id', 'ciudad'])
        self.assertFalse(next(t for t in catalog() if t['name'] == 'users')['queryable'])

    def test_no_authorized_fields_blocks_the_table(self):
        self.save_columns('users', [])
        self.assertFalse(next(t for t in catalog() if t['name'] == 'users')['queryable'])
        self.assertFalse(configuration()['TABLE_PERMISSIONS']['users'])

    def test_field_changes_preserve_other_tables_and_are_audited(self):
        from postal.models import SystemAudit
        self.save_columns('users', ['id', 'ciudad'])
        self.save_columns('paquetes_ems', ['id', 'codigo'])
        self.assertEqual(configuration()['COLUMN_PERMISSIONS']['users'], ['id', 'ciudad'])
        self.assertTrue(SystemAudit.objects.filter(action='table_columns', user=self.admin).exists())

    def test_ordinary_user_cannot_change_fields(self):
        self.client.force_login(get_user_model().objects.create_user('field-operator'))
        self.assertEqual(self.save_columns('users', ['id', 'ciudad']).status_code, 403)

    def test_page_defaults_to_permitted_tables(self):
        response = self.client.get('/system/?view=tables')
        self.assertContains(response, 'Permisos de tablas')
        self.assertContains(response, 'paquetes_ems')
        self.assertNotContains(response, 'name="table" value="auditoria"')
        self.assertEqual(response.context['table_permission'], 'allowed')
        self.assertContains(response, 'No permitidas')
        self.assertContains(response, 'Bloquear')

    def test_prohibited_tables_have_their_own_view(self):
        response = self.client.get('/system/?view=tables&permission=blocked')
        self.assertContains(response, 'name="table" value="auditoria"')
        self.assertNotContains(response, 'name="table" value="paquetes_ems"')
        self.assertEqual(response.context['table_permission'], 'blocked')

    def test_invalid_filter_falls_back_to_permitted_tables(self):
        response = self.client.get('/system/?view=tables&permission=invalid')
        self.assertEqual(response.context['table_permission'], 'allowed')
        self.assertNotContains(response, 'name="table" value="auditoria"')

    def test_block_and_reenable_existing_table_changes_actual_sql_policy(self):
        self.assertEqual(self.toggle('paquetes_ems', False).status_code, 302)
        for sql in ('SELECT COUNT(*) FROM assistant.paquetes_ems',
                    'WITH x AS (SELECT id FROM assistant.paquetes_ems) SELECT COUNT(*) FROM x',
                    'SELECT p.id FROM assistant.users u JOIN assistant.paquetes_ems p ON p.user_id=u.id'):
            with self.subTest(sql=sql), self.assertRaises(QueryRejected):
                validate_sql(sql)
        self.assertFalse(next(t for t in catalog() if t['name'] == 'paquetes_ems')['queryable'])
        self.assertEqual(self.toggle('paquetes_ems', True).status_code, 302)
        with DemoSource().stream('SELECT COUNT(*) AS total FROM assistant.paquetes_ems') as stream:
            self.assertGreater(next(stream.rows)['total'], 0)

    def test_enable_previously_prohibited_table_keeps_sensitive_fields_denied(self):
        self.assertEqual(self.toggle('auditoria', True).status_code, 302)
        table = next(t for t in catalog() if t['name'] == 'auditoria')
        self.assertTrue(table['queryable'])
        validate_sql('SELECT id, nombre_evento FROM assistant.auditoria')
        with DemoSource().stream('SELECT COUNT(*) AS total FROM assistant.auditoria') as stream:
            self.assertEqual(next(stream.rows)['total'], 0)
        self.assertEqual(self.toggle('personal_access_tokens', True).status_code, 400)
        with self.assertRaises(QueryRejected):
            validate_sql('SELECT id FROM assistant.personal_access_tokens')
        for sql in ('SELECT password FROM assistant.users', 'SELECT token FROM assistant.password_reset_tokens'):
            with self.subTest(sql=sql), self.assertRaises(QueryRejected):
                validate_sql(sql)
        with self.assertRaises(QueryRejected):
            validate_sql('SELECT token FROM assistant.personal_access_tokens')

    def test_failed_postgres_preparation_does_not_enable_table(self):
        with override_settings(DATA_MODE='postgres', BUSINESS_USE_ISOLATED_VIEWS=True), patch('postal.table_permissions.prepare_table', side_effect=ValueError('Preparación fallida')):
            response = self.toggle('auditoria', True)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(next(t for t in catalog() if t['name'] == 'auditoria')['queryable'])

    def test_session_identifiers_are_not_available_when_enabling_sessions(self):
        self.assertEqual(self.toggle('sessions', True).status_code, 400)
        with self.assertRaises(QueryRejected):
            validate_sql('SELECT id FROM assistant.sessions')

    def test_successive_changes_keep_other_table_permissions(self):
        self.toggle('paquetes_ems', False)
        self.toggle('users', False)
        self.assertEqual(configuration()['TABLE_PERMISSIONS'], {'paquetes_ems': False, 'users': False})

    def test_normal_users_cannot_change_permissions(self):
        self.client.force_login(get_user_model().objects.create_user('operator'))
        self.assertEqual(self.toggle('paquetes_ems', False).status_code, 403)
        validate_sql('SELECT id FROM assistant.paquetes_ems')

    def test_unknown_table_and_forged_state_are_rejected(self):
        for data in ({'table': 'inventada', 'enabled': '1'}, {'table': 'users', 'enabled': 'yes'}):
            response = self.client.post('/system/?view=tables', {'action': 'table_toggle', **data})
            self.assertEqual(response.status_code, 400)

    def test_changes_preserve_other_settings_and_are_audited(self):
        from postal.models import SystemAudit
        save_config({'AI_TIMEOUT': 77})
        self.toggle('paquetes_ems', False)
        self.assertEqual(configuration()['AI_TIMEOUT'], 77)
        self.assertTrue(SystemAudit.objects.filter(action='table_toggle', user=self.admin).exists())

    def test_search_and_state_filter(self):
        response = self.client.get('/system/?view=tables&q=auditoria&permission=blocked')
        self.assertContains(response, 'auditoria')
        self.assertNotContains(response, 'name="table" value="paquetes_ems"')

    def test_geographic_count_works_without_a_blocked_branch_catalog(self):
        from postal.ai import _normalize_location_filters
        self.toggle('sucursales', False)
        sql = _normalize_location_filters("SELECT COUNT(*) AS total FROM assistant.paquetes_ems p WHERE p.ciudad='La Paz'")
        self.assertNotIn('assistant.sucursales', sql)
        with DemoSource().stream(sql) as stream:
            self.assertGreater(next(stream.rows)['total'], 0)

    def test_connection_check_uses_an_available_table(self):
        from postal.system_views import database_check
        self.toggle('sucursales', False)
        self.assertIn('Conexión correcta', database_check())
