"""Restore only into a newly created, marked database; never overwrite."""
import os
from pathlib import Path
import re
import subprocess
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from django.core.management.base import BaseCommand, CommandError

MARKER='bolipost-isolated-restore-v1'

def admin_url():
    value=os.environ.get('BUSINESS_ADMIN_DATABASE_URL','')
    if not value: raise CommandError('Configure BUSINESS_ADMIN_DATABASE_URL localmente; no incluya secretos en la línea de comandos.')
    return value

def check_name(name):
    if not re.fullmatch(r'[a-z][a-z0-9_]{2,62}',name): raise CommandError('Use un nombre de 3–63 caracteres: letras minúsculas, números y guion bajo.')
    if name in ('postgres','template0','template1'): raise CommandError('No se permite usar una base del sistema.')

def require_isolated(conn):
    row=conn.execute("SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname=current_database()").fetchone()
    if not row or row[0]!=MARKER: raise CommandError('La base debe ser una restauración aislada creada por restore_backup.')

class Command(BaseCommand):
    help='Restaura en una base NUEVA. Rechaza destinos existentes; no modifica el servicio PostgreSQL.'
    def add_arguments(self,parser):
        parser.add_argument('backup');parser.add_argument('--database',required=True)
        parser.add_argument('--pg-restore',default='pg_restore')
    def handle(self,*args,**opts):
        check_name(opts['database'])
        backup=Path(opts['backup']).resolve()
        if not backup.is_file(): raise CommandError('No existe el archivo de respaldo.')
        with backup.open('rb') as source:
            if source.read(5)!=b'PGDMP': raise CommandError('Se requiere un respaldo custom PGDMP.')
        try:
            url=admin_url()
            with psycopg.connect(url,autocommit=True) as conn:
                if conn.execute('SELECT 1 FROM pg_database WHERE datname=%s',(opts['database'],)).fetchone():
                    raise CommandError('El destino ya existe. No se sobrescribió ninguna base.')
                conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(opts['database'])))
            info=conninfo_to_dict(url); info['dbname']=opts['database']
            env=os.environ.copy()
            if info.get('password'): env['PGPASSWORD']=info['password']
            command=[opts['pg_restore'],'--no-owner','--no-privileges','--exit-on-error','--dbname',info['dbname']]
            for key,arg in [('host','--host'),('port','--port'),('user','--username')]:
                if info.get(key): command.extend([arg,info[key]])
            command.extend(['--no-password',str(backup)])
            result=subprocess.run(command,env=env,capture_output=True)
            if result.returncode: raise CommandError('La restauración falló. La base nueva se conservó para inspección; no vuelva a usar ese destino.')
            with psycopg.connect(url,autocommit=True) as conn:
                conn.execute(sql.SQL('COMMENT ON DATABASE {} IS {}').format(sql.Identifier(opts['database']),sql.Literal(MARKER)))
            self.stdout.write('Respaldo restaurado en la base nueva. Configure vistas y rol con prepare_business antes de consultar.')
        except CommandError: raise
        except (psycopg.Error,OSError) as exc: raise CommandError('No se pudo restaurar. Revise credenciales, conexión y herramientas PostgreSQL.') from None
