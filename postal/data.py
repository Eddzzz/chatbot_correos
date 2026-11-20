"""Read-only streaming sources. Demo is explicit and never a connection fallback."""
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import threading
import uuid
from django.conf import settings
from sqlglot import exp, parse_one
from .policy import USER_ROLES_SOURCE, authorized_columns, catalog, validate_sql, QueryRejected


def projection_query(name, columns):
    from psycopg import sql

    if name == USER_ROLES_SOURCE:
        source = sql.SQL(r"""
            (SELECT u.id AS user_id, a.role_id
             FROM public.users u
             JOIN public.model_has_roles a ON a.model_id = u.id AND a.model_type = $$App\Models\User$$
             UNION ALL
             SELECT u.id, u.role_id FROM public.users u
             WHERE u.role_id IS NOT NULL AND NOT EXISTS (
                 SELECT 1 FROM public.model_has_roles a WHERE a.model_id = u.id AND a.model_type = $$App\Models\User$$
             )) AS assignments
        """)
    else:
        source = sql.SQL('public.{}').format(sql.Identifier(name))
    return sql.SQL('SELECT {} FROM {}').format(sql.SQL(', ').join(map(sql.Identifier, columns)), source)


def _project_postgres_sources(tree, allowed):
    # Translate validated logical sources while keeping the same field allowlist and aliases.
    for table in list(tree.find_all(exp.Table)):
        if table.db == 'assistant':
            projection = parse_one(projection_query(table.name, allowed[table.name]).as_string(), read='postgres')
            table.replace(exp.Subquery(this=projection, alias=table.args['alias'].copy()))

class DataError(Exception):
    def __init__(self,code,message):
        self.code=code; self.message=message
        super().__init__(message)

class Cancellation:
    def __init__(self):
        self._event=threading.Event(); self._lock=threading.Lock(); self._callbacks=[]
    @property
    def cancelled(self): return self._event.is_set()
    def check(self):
        if self.cancelled: raise DataError('cancelled','La consulta fue cancelada.')
    def register(self,callback):
        with self._lock:
            if not self.cancelled:
                self._callbacks.append(callback)
                return
        callback()
    def cancel(self):
        with self._lock:
            self._event.set(); callbacks=self._callbacks; self._callbacks=[]
        for callback in callbacks:
            try: callback()
            except Exception: pass

@dataclass
class Stream:
    columns: list
    rows: object
    sources: list

def _rows(cursor,token):
    while True:
        token.check()
        batch=cursor.fetchmany(100)
        if not batch: return
        for row in batch:
            token.check()
            yield dict(row)

def _columns(cursor):
    columns=[c[0] for c in cursor.description]
    if len(columns)!=len(set(columns)):
        raise DataError('duplicate_columns','Asigne un alias distinto a cada columna del resultado.')
    return columns

class DemoSource:
    demo=True
    def catalog(self): return catalog()
    @contextmanager
    def stream(self,sql,params=None,cancellation=None):
        tree,sources=validate_sql(sql)
        token=cancellation or Cancellation(); token.check()
        connection=sqlite3.connect(':memory:')
        connection.row_factory=sqlite3.Row
        try:
            connection.execute("ATTACH DATABASE ':memory:' AS assistant")
            fixtures=json.loads((Path(__file__).parent/'fixtures'/'demo.json').read_text(encoding='utf-8'))
            if 'user_roles' not in fixtures:
                fixtures['user_roles'] = [{'user_id': user['id'], 'role_id': user['role_id']}
                                          for user in fixtures.get('users', []) if user.get('role_id') is not None]
            for table,columns in authorized_columns().items():
                definitions=', '.join('"'+c+'" '+('REAL' if c in ('peso','precio') else 'INTEGER' if c=='id' or c.endswith('_id') or c.startswith('fk_') else 'TEXT') for c in columns)
                connection.execute(f'CREATE TABLE assistant."{table}" ({definitions})')
                values=fixtures.get(table,[])
                if values:
                    placeholders=','.join('?' for c in columns)
                    connection.executemany(f'INSERT INTO assistant."{table}" VALUES ({placeholders})',[[row.get(c) for c in columns] for row in values])
            connection.commit(); connection.execute('PRAGMA query_only=ON')
            connection.set_progress_handler(lambda:1 if token.cancelled else 0,1000)
            token.register(connection.interrupt)
            token.check()
            formats={'YEAR':'%Y-01-01 00:00:00','MONTH':'%Y-%m-01 00:00:00','DAY':'%Y-%m-%d 00:00:00','HOUR':'%Y-%m-%d %H:00:00','MINUTE':'%Y-%m-%d %H:%M:00','SECOND':'%Y-%m-%d %H:%M:%S'}
            def sqlite_temporal(node):
                # SQLite gives TIMESTAMP numeric affinity; use its date parser instead.
                if isinstance(node,exp.Cast) and node.to.this.value.upper() in ('TIMESTAMP','TIMESTAMPTZ'):
                    return exp.Anonymous(this='DATETIME',expressions=[node.this.copy()])
                if isinstance(node,exp.TimestampTrunc):
                    unit=node.args['unit'].name.upper()
                    if unit not in formats: raise DataError('unsupported_demo','Esta unidad temporal no está disponible en demostración.')
                    return exp.Anonymous(this='STRFTIME',expressions=[exp.Literal.string(formats[unit]),node.this.copy()])
                return node
            translated=tree.copy()
            # Translate children first so nested casts/truncations stay in SQLite's temporal domain.
            for node in reversed(list(translated.walk())):
                replacement=sqlite_temporal(node)
                if replacement is not node: node.replace(replacement)
            cursor=connection.execute(translated.sql(dialect='sqlite'),params or ())
            yield Stream(_columns(cursor),_rows(cursor,token),sources)
        except (DataError,QueryRejected): raise
        except sqlite3.Error as exc:
            token.check()
            raise DataError('query_failed','No se pudo ejecutar la consulta de demostración.') from exc
        finally: connection.close()

class PostgresSource:
    demo=False
    def __init__(self,url): self.url=url
    def catalog(self): return catalog()
    @contextmanager
    def stream(self,sql,params=None,cancellation=None):
        import psycopg
        from psycopg.rows import dict_row
        allowed=authorized_columns()
        tree,sources=validate_sql(sql,allowed=allowed)
        use_views=settings.BUSINESS_USE_ISOLATED_VIEWS
        if not use_views:
            _project_postgres_sources(tree, allowed)
        token=cancellation or Cancellation(); token.check()
        connection=None
        try:
            from .system_config import value
            connection=psycopg.connect(self.url,connect_timeout=value('DB_CONNECT_TIMEOUT'),row_factory=dict_row)
            # Register before execute: cancellation also interrupts a blocked server query.
            token.register(connection.cancel)
            token.check()
            connection.execute('SET TRANSACTION READ ONLY')
            connection.execute("SET LOCAL search_path TO pg_catalog")
            if not use_views:
                connection.execute("SET LOCAL standard_conforming_strings TO on")
            connection.execute("SELECT set_config('statement_timeout', %s, true)", (str(value('DB_STATEMENT_TIMEOUT')),))
            with connection.cursor(name='postal_'+uuid.uuid4().hex) as cursor:
                cursor.itersize=100
                cursor.execute(tree.sql(dialect='postgres'),params)
                columns=[c.name for c in cursor.description]
                if len(columns)!=len(set(columns)): raise DataError('duplicate_columns','Asigne un alias distinto a cada columna del resultado.')
                yield Stream(columns,_rows(cursor,token),sources)
        except (DataError,QueryRejected): raise
        except psycopg.Error as exc:
            token.check()
            raise DataError('database_unavailable','No se pudo consultar PostgreSQL. Revise la conexión y los permisos de lectura.') from exc
        finally:
            if connection is not None:
                try: connection.rollback()
                except Exception: pass
                finally: connection.close()

def get_source():
    from .system_config import value
    mode=value('DATA_MODE')
    if mode=='demo': return DemoSource()
    if mode!='postgres': raise DataError('configuration','DATA_MODE debe ser demo o postgres.')
    url=value('BUSINESS_DATABASE_URL')
    if not url: raise DataError('database_configuration','Configure BUSINESS_DATABASE_URL con el rol de consulta autorizado.')
    return PostgresSource(url)
