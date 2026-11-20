"""Provision projected views and verify an isolated query role's effective grants."""
import os
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from django.core.management.base import BaseCommand, CommandError
from postal.policy import SAFE_COLUMNS
from postal.data import projection_query
from .restore_backup import admin_url, check_name, require_isolated

class Command(BaseCommand):
    help='Crea vistas autorizadas y un rol nuevo de solo consulta en una base aislada.'
    def add_arguments(self,parser):
        parser.add_argument('--database',required=True)
        parser.add_argument('--role',default='bolipost_reader')
    def handle(self,*args,**opts):
        check_name(opts['database']);check_name(opts['role'])
        password=os.environ.get('BUSINESS_READONLY_PASSWORD','')
        if len(password)<16: raise CommandError('Configure BUSINESS_READONLY_PASSWORD con al menos 16 caracteres.')
        try:
            info=conninfo_to_dict(admin_url());info['dbname']=opts['database']
            with psycopg.connect(make_conninfo(**info)) as conn:
                require_isolated(conn)
                role=opts['role']; rid=sql.Identifier(role)
                if conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(role,)).fetchone():
                    raise CommandError('El rol ya existe. Use un rol nuevo para evitar modificar privilegios de otra aplicación.')
                # All privilege changes are atomic and restricted to this marked database.
                conn.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD {}').format(rid,sql.Literal(password)))
                conn.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM PUBLIC').format(sql.Identifier(opts['database'])))
                conn.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(opts['database']),rid))
                schemas=conn.execute("SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema'").fetchall()
                for (schema,) in schemas:
                    sid=sql.Identifier(schema)
                    conn.execute(sql.SQL('REVOKE ALL ON SCHEMA {} FROM PUBLIC').format(sid))
                    conn.execute(sql.SQL('REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM PUBLIC').format(sid))
                    conn.execute(sql.SQL('REVOKE ALL ON ALL SEQUENCES IN SCHEMA {} FROM PUBLIC').format(sid))
                    conn.execute(sql.SQL('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA {} FROM PUBLIC').format(sid))
                conn.execute('CREATE SCHEMA IF NOT EXISTS assistant')
                conn.execute('REVOKE ALL ON SCHEMA assistant FROM PUBLIC')
                for table,columns in SAFE_COLUMNS.items():
                    known={row[0] for row in conn.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s',('public',table))}
                    if table!='user_roles' and not set(columns)<=known: raise CommandError(f'El esquema de {table} no coincide con el catálogo revisado. No se aplicaron cambios.')
                    conn.execute(sql.SQL('CREATE OR REPLACE VIEW assistant.{} WITH (security_barrier=true) AS {}').format(sql.Identifier(table),projection_query(table,columns)))
                    conn.execute(sql.SQL('REVOKE ALL ON assistant.{} FROM PUBLIC').format(sql.Identifier(table)))
                    conn.execute(sql.SQL('GRANT SELECT ON assistant.{} TO {}').format(sql.Identifier(table),rid))
                conn.execute(sql.SQL('GRANT USAGE ON SCHEMA assistant TO {}').format(rid))
                conn.execute(sql.SQL('ALTER ROLE {} SET default_transaction_read_only=on').format(rid))
                conn.execute(sql.SQL('ALTER ROLE {} SET search_path=pg_catalog').format(rid))
                conn.execute(sql.SQL('ALTER ROLE {} SET statement_timeout=0').format(rid))
                grants=conn.execute("SELECT c.oid, n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN ('r','v','m','p','f') AND n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%'").fetchall()
                for oid,schema,table in grants:
                    canread,canwrite=conn.execute("SELECT has_table_privilege(%s,%s,'SELECT'), has_table_privilege(%s,%s,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')",(role,oid,role,oid)).fetchone()
                    expected=schema=='assistant' and table in SAFE_COLUMNS
                    if bool(canread)!=expected or canwrite: raise CommandError('Los privilegios efectivos no son seguros. Se revirtieron los cambios.')
                if any(conn.execute('SELECT has_database_privilege(%s,current_database(),%s)',(role,priv)).fetchone()[0] for priv in ('CREATE','TEMP')):
                    raise CommandError('El rol posee permisos de creación. Se revirtieron los cambios.')
            self.stdout.write(f'{len(SAFE_COLUMNS)} vistas autorizadas; rol nuevo verificado sin acceso a tablas originales ni escritura.')
        except CommandError: raise
        except psycopg.Error: raise CommandError('No se pudo preparar la base aislada. Revise conexión, propiedad y permisos administrativos.') from None
