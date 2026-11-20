import unittest
from django.test import SimpleTestCase, override_settings
from postal.data import DemoSource, Cancellation, DataError
from postal.policy import validate_sql, QueryRejected

class PolicyTests(unittest.TestCase):
    def test_compound_filters_select_the_correct_rows(self):
        for predicate, expected in (
            ("id >= 1 AND id < 3", [{'id': 1}, {'id': 2}]),
            ("id = 1 OR id = 3", [{'id': 1}, {'id': 3}]),
        ):
            with self.subTest(predicate=predicate):
                with DemoSource().stream('SELECT id FROM assistant.paquetes_ems WHERE ' + predicate + ' ORDER BY id') as result:
                    self.assertEqual(list(result.rows), expected)

    def test_postgres_mixed_case_columns_keep_their_exact_names(self):
        tree, _ = validate_sql('SELECT s."codigoSucursal" FROM assistant.sucursales s')
        self.assertIn('s."codigoSucursal"', tree.sql(dialect='postgres'))
        with self.assertRaises(QueryRejected):
            validate_sql('SELECT s.codigoSucursal FROM assistant.sucursales s')
        tree, _ = validate_sql('SELECT * FROM assistant.sucursales')
        self.assertIn('sucursales."codigoSucursal"', tree.sql(dialect='postgres'))

    def test_reject_unsafe_queries(self):
        attacks = [
            'DELETE FROM assistant.paquetes_ems',
            'SELECT 1; SELECT 2',
            'WITH a AS (DELETE FROM assistant.paquetes_ems RETURNING *) SELECT * FROM a',
            'SELECT * INTO x FROM assistant.paquetes_ems',
            'SELECT pg_sleep(2)', 'SELECT set_config(\'search_path\',\'public\',false)',
            'SELECT * FROM public.users', 'SELECT * FROM pg_catalog.pg_authid',
            'SELECT password FROM assistant.users',
            'SELECT u.password AS name FROM assistant.users u',
            "SELECT id FROM assistant.users WHERE id = 1 AND password = 'secret'",
            "SELECT id FROM assistant.users WHERE id = 1 OR pg_sleep(2) IS NULL",
            'WITH x AS (SELECT * FROM assistant.users) SELECT password FROM x',
            "SELECT CAST('public.users' AS regclass)",
            'SELECT public.evil(id) FROM assistant.users',
            'SELECT * FROM assistant.users FOR UPDATE',
            'SELECT u FROM assistant.users u',
            'SELECT * FROM assistant.users u JOIN assistant.users v ON u.password=v.password',
        ]
        for query in attacks:
            with self.subTest(query=query), self.assertRaises(QueryRejected): validate_sql(query)

    def test_accept_joins_cte_and_aggregate(self):
        for query in [
            'SELECT p.codigo, e.nombre_evento FROM assistant.eventos_ems p JOIN assistant.eventos e ON p.evento_id=e.id',
            'WITH x AS (SELECT estado_id, count(*) AS total FROM assistant.paquetes_ems GROUP BY estado_id) SELECT * FROM x',
            'SELECT count(*) AS total FROM assistant.paquetes_ems',
        ]: validate_sql(query)

class DemoTests(unittest.TestCase):
    def test_catalog_real_metadata_and_no_sensitive_query_fields(self):
        catalog = DemoSource().catalog()
        self.assertEqual(len(catalog),123)
        users = next(t for t in catalog if t['name']=='users')
        roles = next(t for t in catalog if t['name']=='user_roles')
        self.assertEqual(roles['allowed_columns'], ['user_id', 'role_id'])
        self.assertNotIn('password', users['allowed_columns'])
        self.assertTrue(any(c['name']=='password' and not c['allowed'] for c in users['columns']))

    def test_stream_has_no_fifty_row_cap(self):
        with DemoSource().stream('SELECT codigo FROM assistant.paquetes_ems ORDER BY id') as result:
            rows=list(result.rows)
            self.assertGreater(len(rows),50)
            self.assertEqual(rows[0]['codigo'],'BO-DEMO-001')
            self.assertEqual(result.sources,['paquetes_ems'])

    def test_parameters_and_cancellation(self):
        source=DemoSource()
        with source.stream('SELECT codigo FROM assistant.paquetes_ems WHERE codigo = %s',['BO-DEMO-001']) as result:
            self.assertEqual(list(result.rows),[{'codigo':'BO-DEMO-001'}])
        token=Cancellation(); called=[]
        token.register(lambda:called.append(True)); token.cancel()
        self.assertEqual(called,[True])
        with self.assertRaises(DataError):
            with source.stream('SELECT * FROM assistant.users',cancellation=token): pass

    def test_month_aggregate_matches_all_demo_rows(self):
        with DemoSource().stream("SELECT date_trunc('month',created_at) AS mes, count(*) AS total FROM assistant.paquetes_ems GROUP BY date_trunc('month',created_at)") as result:
            self.assertEqual(list(result.rows),[{'mes':'2026-10-01 00:00:00','total':80}])

    def test_month_aggregate_preserves_dates_with_explicit_timestamp_casts(self):
        expressions=(
            'created_at::timestamp',
            'created_at::timestamptz',
            'CAST(CAST(created_at AS TEXT) AS TIMESTAMP)',
        )
        for expression in expressions:
            query=f"SELECT DATE_TRUNC('month',{expression}) AS mes,COUNT(*) AS total FROM assistant.paquetes_ems GROUP BY DATE_TRUNC('month',{expression})"
            with self.subTest(expression=expression),DemoSource().stream(query) as result:
                self.assertEqual(list(result.rows),[{'mes':'2026-10-01 00:00:00','total':80}])

    def test_timestamp_cast_surrounding_truncation_preserves_date_and_nulls(self):
        query="SELECT CAST(DATE_TRUNC('month',created_at::timestamp) AS TIMESTAMP) AS mes FROM assistant.paquetes_ems WHERE id=1"
        with DemoSource().stream(query) as result:
            self.assertEqual(list(result.rows),[{'mes':'2026-10-01 00:00:00'}])
        with DemoSource().stream('SELECT CAST(fecha_recojo AS TIMESTAMP) AS fecha FROM assistant.paquetes_contrato WHERE id=1') as result:
            self.assertEqual(list(result.rows),[{'fecha':None}])

    def test_labor_and_status_reference_tables(self):
        with DemoSource().stream('SELECT u.id, r.nombre FROM assistant.users u JOIN assistant.roles r ON u.role_id=r.id') as result:
            self.assertEqual(list(result.rows)[0]['nombre'],'Operador de demostración')

# Opt-in integration uses an isolated, schema-restored database only, never port 5432.
import os
import time
import threading
import secrets
from unittest.mock import patch
from postal.data import PostgresSource

class PostgresProjectionTests(unittest.TestCase):
    def test_postgres_stream_projects_public_tables_and_resolves_user_roles(self):
        from unittest.mock import MagicMock
        query = """
            WITH selected AS (SELECT * FROM assistant.users WHERE id = %s)
            SELECT u.id, a.role_id FROM selected u
            JOIN assistant.user_roles a ON a.user_id = u.id
        """
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.description = []
        with override_settings(BUSINESS_USE_ISOLATED_VIEWS=False), patch('psycopg.connect', return_value=connection):
            with PostgresSource('reader').stream(query, [7]) as result:
                self.assertCountEqual(result.sources, ['users', 'user_roles'])
        statement, params = cursor.execute.call_args.args
        self.assertEqual(params, [7])
        self.assertIn('FROM public.users', statement)
        self.assertIn('public.model_has_roles', statement)
        self.assertNotIn('assistant.', statement)
        self.assertNotIn('password', statement)
        self.assertEqual(connection.execute.call_args_list[0].args, ('SET TRANSACTION READ ONLY',))

@unittest.skipUnless(os.environ.get('POSTAL_INTEGRATION_URL'),'Requiere clúster PostgreSQL aislado explícito.')
@override_settings(BUSINESS_USE_ISOLATED_VIEWS=True)
class PostgresIntegrationTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import psycopg
        from psycopg.conninfo import conninfo_to_dict,make_conninfo
        from postal.management.commands.prepare_business import Command
        from postal.management.commands.restore_backup import require_isolated
        cls.admin_url=os.environ['POSTAL_INTEGRATION_URL']
        info=conninfo_to_dict(cls.admin_url)
        if info.get('port')=='5432': raise RuntimeError('Las pruebas no pueden usar el puerto del servicio existente.')
        cls.role='bolipost_test_'+secrets.token_hex(4)
        password=secrets.token_urlsafe(24)
        with psycopg.connect(cls.admin_url) as conn:
            require_isolated(conn)
            conn.execute('SET LOCAL session_replication_role=replica')
            conn.execute('DELETE FROM public.paquetes_ems')
            conn.execute("INSERT INTO public.paquetes_ems(id,codigo,peso,precio,created_at) SELECT n, 'BO-DEMO-'||lpad(n::text,3,'0'), 1.5, 20, TIMESTAMP '2026-10-01' FROM generate_series(1,180) n")
        with patch.dict(os.environ,{'BUSINESS_ADMIN_DATABASE_URL':cls.admin_url,'BUSINESS_READONLY_PASSWORD':password}):
            Command().handle(database=info['dbname'],role=cls.role)
        info['user']=cls.role;info['password']=password
        cls.reader_url=make_conninfo(**info)

    def test_real_server_cursor_full_rows_parameters_and_aggregate(self):
        source=PostgresSource(self.reader_url)
        with source.stream('SELECT codigo FROM assistant.paquetes_ems ORDER BY id') as result:
            self.assertEqual(len(list(result.rows)),180)
        with source.stream('SELECT codigo FROM assistant.paquetes_ems WHERE codigo = %s',['BO-DEMO-001']) as result:
            self.assertEqual(list(result.rows),[{'codigo':'BO-DEMO-001'}])
        with source.stream("SELECT date_trunc('month',created_at) AS month,count(*) AS total,sum(precio) AS importe FROM assistant.paquetes_ems GROUP BY date_trunc('month',created_at)") as result:
            row=list(result.rows)[0]
            self.assertEqual(row['total'],180);self.assertEqual(row['importe'],3600)

    def test_builtin_functions_cannot_be_shadowed_by_user_schema(self):
        import psycopg
        with psycopg.connect(self.admin_url) as conn:
            conn.execute("CREATE OR REPLACE FUNCTION public.lower(character varying) RETURNS text LANGUAGE sql AS $$ SELECT 'valor inventado'::text $$")
            conn.execute("CREATE OR REPLACE FUNCTION assistant.lower(character varying) RETURNS text LANGUAGE sql AS $$ SELECT 'valor inventado'::text $$")
            conn.execute("SET LOCAL session_replication_role=replica")
            conn.execute("UPDATE public.paquetes_ems SET ciudad='LA PAZ' WHERE id=1")
        with PostgresSource(self.reader_url).stream('SELECT LOWER(ciudad) AS ciudad FROM assistant.paquetes_ems WHERE id=1') as result:
            self.assertEqual(list(result.rows),[{'ciudad':'la paz'}])
        for query in ('SELECT public.lower(ciudad) FROM assistant.paquetes_ems','SELECT assistant.lower(ciudad) FROM assistant.paquetes_ems'):
            with self.subTest(query=query),self.assertRaises(QueryRejected): validate_sql(query)

    def test_effective_permissions_even_without_parser(self):
        import psycopg
        with psycopg.connect(self.reader_url,autocommit=True) as conn:
            self.assertEqual(conn.execute('SHOW default_transaction_read_only').fetchone()[0],'on')
            self.assertEqual(conn.execute('SHOW statement_timeout').fetchone()[0],'0')
            self.assertEqual(conn.execute('SHOW search_path').fetchone()[0],'pg_catalog')
            for statement in [
                'SELECT password FROM assistant.users',
                'SELECT password FROM public.users',
                'CREATE TEMP TABLE forbidden(id int)',
                'CREATE TABLE public.forbidden(id int)',
                'INSERT INTO assistant.paquetes_ems(id) VALUES (1000)',
                'UPDATE assistant.paquetes_ems SET precio=0',
                'DELETE FROM assistant.paquetes_ems',
            ]:
                with self.subTest(statement=statement), self.assertRaises(psycopg.Error):conn.execute(statement)
            # Turning off the default read-only flag must not grant write access.
            conn.execute('BEGIN READ WRITE')
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute('UPDATE assistant.paquetes_ems SET precio=0')
            conn.execute('ROLLBACK')

    def test_cancel_interrupts_execute_waiting_for_database_lock(self):
        import psycopg
        token=Cancellation();outcome=[]
        def query():
            try:
                with PostgresSource(self.reader_url).stream('SELECT codigo FROM assistant.paquetes_ems',cancellation=token) as result:
                    list(result.rows)
            except DataError as exc: outcome.append(exc.code)
        with psycopg.connect(self.admin_url) as admin:
            admin.execute('LOCK TABLE public.paquetes_ems IN ACCESS EXCLUSIVE MODE')
            worker=threading.Thread(target=query,daemon=True);worker.start()
            waiting=False;deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                waiting=admin.execute("SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE usename=%s AND wait_event_type='Lock')",(self.role,)).fetchone()[0]
                if waiting: break
                admin.execute('SELECT pg_stat_clear_snapshot()');time.sleep(.03)
            self.assertTrue(waiting,'La consulta debe estar bloqueada dentro de execute antes de cancelar.')
            token.cancel();worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(outcome,['cancelled'])

    def test_restore_refuses_existing_database_before_subprocess(self):
        from psycopg.conninfo import conninfo_to_dict
        from django.core.management.base import CommandError
        from postal.management.commands.restore_backup import Command
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory(dir='.runtime') as folder:
            backup=Path(folder)/'empty.pgdump';backup.write_bytes(b'PGDMP')
            with patch.dict(os.environ,{'BUSINESS_ADMIN_DATABASE_URL':self.admin_url}), patch('postal.management.commands.restore_backup.subprocess.run') as process:
                with self.assertRaisesRegex(CommandError,'ya existe'):
                    Command().handle(backup=str(backup),database=conninfo_to_dict(self.admin_url)['dbname'],pg_restore='pg_restore')
                process.assert_not_called()

class AIProvenanceTests(unittest.TestCase):
    def test_reject_manufactured_projected_values(self):
        from postal.policy import validate_ai_sql
        queries=[
            'SELECT 999999 AS envios_verificados FROM assistant.paquetes_ems LIMIT 1',
            'SELECT SUM(999999) AS total FROM assistant.paquetes_ems',
            'SELECT COUNT(999999) AS total FROM assistant.paquetes_ems',
            'SELECT COUNT(*)+999999 AS total FROM assistant.paquetes_ems',
            "SELECT CASE WHEN id>0 THEN 'Entregado' ELSE 'Admitido' END AS estado FROM assistant.paquetes_ems",
            'WITH x AS (SELECT 999999 AS total FROM assistant.paquetes_ems) SELECT total FROM x',
            'SELECT TRUE AS verificado FROM assistant.paquetes_ems',
            'SELECT NULL AS importe FROM assistant.paquetes_ems',
            'SELECT %s AS total FROM assistant.paquetes_ems',
            'SELECT CURRENT_TIMESTAMP AS fecha FROM assistant.paquetes_ems',
            'SELECT COUNT(*) AS total',
            'WITH datos AS (SELECT id FROM assistant.eventos_ems) SELECT COUNT(*) AS total',
            'WITH x AS (SELECT COUNT(*) AS total) SELECT x.total FROM x CROSS JOIN assistant.paquetes_ems',
            'SELECT codigo FROM assistant.paquetes_ems UNION ALL SELECT 999999 FROM assistant.paquetes_certi',
        ]
        for query in queries:
            with self.subTest(query=query),self.assertRaises(QueryRejected): validate_ai_sql(query)

    def test_accept_fields_true_aggregates_and_structural_literals(self):
        from postal.policy import validate_ai_sql
        for query in [
            'SELECT codigo,LOWER(ciudad) AS ciudad FROM assistant.paquetes_ems WHERE codigo=\'BO-DEMO-001\'',
            'SELECT COUNT(*) AS total,SUM(precio) AS importe FROM assistant.paquetes_ems',
            "SELECT DATE_TRUNC('month',created_at) AS mes,COUNT(*) AS total FROM assistant.paquetes_ems GROUP BY DATE_TRUNC('month',created_at)",
            'SELECT ROUND(AVG(peso),2) AS peso FROM assistant.paquetes_ems',
            'SELECT CAST(peso AS numeric(10,2)) AS peso FROM assistant.paquetes_ems',
            'WITH x AS (SELECT estado_id,COUNT(*) AS total FROM assistant.paquetes_ems GROUP BY estado_id) SELECT * FROM x',
        ]:
            with self.subTest(query=query): validate_ai_sql(query)
        # Fixed server-owned tracking service labels remain permitted by the base validator.
        validate_sql("SELECT 'ems' AS servicio,codigo FROM assistant.paquetes_ems")

    def test_chart_requires_real_grouped_aggregate(self):
        from postal.policy import ai_chart_supported
        self.assertTrue(ai_chart_supported('SELECT ciudad,COUNT(*) AS total FROM assistant.paquetes_ems GROUP BY ciudad','ciudad','total'))
        self.assertFalse(ai_chart_supported('SELECT ciudad,precio FROM assistant.paquetes_ems','ciudad','precio'))
        self.assertFalse(ai_chart_supported('SELECT ciudad,9999 AS total FROM assistant.paquetes_ems GROUP BY ciudad','ciudad','total'))
        self.assertFalse(ai_chart_supported('SELECT ciudad,COUNT(*) AS total FROM assistant.paquetes_ems GROUP BY ciudad','ciudad','missing'))
