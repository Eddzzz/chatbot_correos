"""Check permission changes against a temporary PostgreSQL cluster, never the running service."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from django.conf import settings
from django.test import override_settings
import psycopg
from postal.data import PostgresSource
from postal.policy import QueryRejected, validate_sql
from postal.system_config import save_config
from postal.table_permissions import prepare_table


def run():
    out = ROOT / '.runtime/qa/table-permissions'
    out.mkdir(parents=True, exist_ok=True)
    binary = Path(settings.PG_BIN)
    flags = {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)}
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='table-pg-', dir=ROOT / '.runtime') as folder:
        folder = Path(folder)
        cluster = folder / 'cluster'
        def command(*args):
            with (out / 'postgres-tools.log').open('a', encoding='utf-8') as log:
                result = subprocess.run(list(map(str, args)), stdout=log, stderr=subprocess.STDOUT, text=True, **flags)
            if result.returncode:
                raise RuntimeError('PostgreSQL test helper failed; see postgres-tools.log')
        command(binary / 'initdb.exe', '-D', cluster, '--username=qa_admin', '--auth=trust', '--encoding=UTF8', '--no-locale', '--no-sync')
        command(binary / 'pg_ctl.exe', '-D', cluster, '-l', folder / 'postgres.log', '-o', f'-h 127.0.0.1 -p {port}', '-w', 'start')
        try:
            url = f'postgresql://qa_admin@127.0.0.1:{port}'
            with psycopg.connect(url + '/postgres', autocommit=True) as conn:
                conn.execute('CREATE DATABASE qa_permissions')
                conn.execute("COMMENT ON DATABASE qa_permissions IS 'bolipost-isolated-restore-v1'")
            with psycopg.connect(url + '/qa_permissions') as conn:
                conn.execute('CREATE SCHEMA assistant')
                conn.execute('CREATE TABLE public.auditoria (id bigint, nombre_evento varchar(255), created_at timestamp, updated_at timestamp, password text)')
                conn.execute("INSERT INTO public.auditoria VALUES (1, 'Prueba', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'synthetic-secret')")
                conn.execute('CREATE TABLE public.users (id bigint, ciudad varchar(255), role_id bigint, password text)')
                conn.execute("INSERT INTO public.users VALUES (1, 'La Paz', 2, 'synthetic-secret')")
                conn.execute('CREATE ROLE qa_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT')
                conn.execute('REVOKE ALL ON SCHEMA public FROM PUBLIC')
                conn.execute('GRANT USAGE ON SCHEMA assistant TO qa_reader')
                conn.execute('ALTER ROLE qa_reader SET default_transaction_read_only=on')
            reader = f'postgresql://qa_reader@127.0.0.1:{port}/qa_permissions'
            with override_settings(SYSTEM_CONFIG_PATH=folder / 'settings.json', DATA_MODE='postgres',
                                   BUSINESS_USE_ISOLATED_VIEWS=True,
                                   BUSINESS_DATABASE_URL=reader, BUSINESS_ADMIN_DATABASE_URL=url + '/postgres'):
                save_config({'TABLE_PERMISSIONS': {'auditoria': True}})
                prepare_table('auditoria', ('id', 'nombre_evento', 'created_at', 'updated_at'))
                with PostgresSource(reader).stream('SELECT COUNT(*) AS total FROM assistant.auditoria') as result:
                    assert next(result.rows)['total'] == 1
                prepare_table('users', ('id','ciudad'), persist=lambda: save_config({'COLUMN_PERMISSIONS': {'users': ['id','ciudad']}}))
                prepare_table('users', ('id','ciudad','role_id'), persist=lambda: save_config({'COLUMN_PERMISSIONS': {'users': ['id','ciudad','role_id']}}))
                with PostgresSource(reader).stream('SELECT ciudad, role_id FROM assistant.users') as result:
                    assert next(result.rows) == {'ciudad': 'La Paz', 'role_id': 2}
                prepare_table('users', ('id',), persist=lambda: save_config({'COLUMN_PERMISSIONS': {'users': ['id']}}))
                with psycopg.connect(reader, autocommit=True) as conn:
                    try:
                        conn.execute('SELECT role_id FROM assistant.users')
                    except psycopg.errors.UndefinedColumn:
                        pass
                    else:
                        raise AssertionError('Protected column remained in the PostgreSQL view')
                def failed_save():
                    raise OSError('Synthetic settings failure')
                try:
                    prepare_table('users', ('id','ciudad'), persist=failed_save)
                except OSError:
                    pass
                else:
                    raise AssertionError('Failed save was ignored')
                with psycopg.connect(reader, autocommit=True) as conn:
                    try:
                        conn.execute('SELECT ciudad FROM assistant.users')
                    except psycopg.errors.UndefinedColumn:
                        pass
                    else:
                        raise AssertionError('Failed save changed the PostgreSQL projection')
                with psycopg.connect(reader, autocommit=True) as conn:
                    for sql in ('SELECT * FROM public.auditoria', 'SELECT password FROM assistant.auditoria',
                                "UPDATE assistant.auditoria SET nombre_evento='modificado'"):
                        try:
                            conn.execute(sql)
                        except psycopg.Error:
                            pass
                        else:
                            raise AssertionError('Unexpected access: ' + sql)
                save_config({'TABLE_PERMISSIONS': {'auditoria': False}})
                try:
                    validate_sql('SELECT COUNT(*) FROM assistant.auditoria')
                except QueryRejected:
                    pass
                else:
                    raise AssertionError('Blocked table remained queryable')
            (out / 'postgres-check.json').write_text(json.dumps({'passed': True,
                'checks': ['new table readable', 'original table denied', 'secret field denied', 'write denied',
                           'added authorized field', 'removed protected field', 'failed save rollback', 'blocked table rejected']}), encoding='utf-8')
            print('PASS: new PostgreSQL projection, read-only role, protected fields, and blocking')
        finally:
            command(binary / 'pg_ctl.exe', '-D', cluster, '-m', 'fast', '-w', 'stop')


if __name__ == '__main__':
    run()
