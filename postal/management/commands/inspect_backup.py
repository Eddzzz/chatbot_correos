"""Extract only structural metadata; never restore or read business rows."""
import json
import re
import subprocess
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError


def extract_catalog(schema):
    tables=[]
    for name,body in re.findall(r'CREATE TABLE public\.([\w]+) \((.*?)\n\);',schema,re.S):
        columns=[]
        for line in body.splitlines():
            match=re.match(r'\s*("[^"]+"|\w+)\s+(.+)',line.rstrip(','))
            if match:
                col,definition=match.groups()
                datatype=re.split(r'\s+(?:DEFAULT|NOT NULL|NULL|GENERATED|CONSTRAINT|COLLATE)\b',definition)[0]
                columns.append({'name':col.strip('"'),'type':datatype})
        tables.append({'name':name,'columns':columns,'relations':[]})
    by_name={t['name']:t for t in tables}
    pattern=r'ALTER TABLE ONLY public\.(\w+)\s+ADD CONSTRAINT [^;]*?FOREIGN KEY \(([^)]+)\) REFERENCES public\.(\w+)\(([^)]+)\)'
    for table,cols,target,targets in re.findall(pattern,schema,re.S):
        for col,targetcol in zip(cols.split(','),targets.split(',')):
            by_name[table]['relations'].append({'column':col.strip().strip('"'),'table':target,'target':targetcol.strip().strip('"')})
    return tables

class Command(BaseCommand):
    help='Extrae únicamente nombres, tipos y claves del respaldo custom PostgreSQL.'
    def add_arguments(self,parser):
        parser.add_argument('backup'); parser.add_argument('--output',default='data/catalog.json')
        parser.add_argument('--pg-restore',default='pg_restore')
    def handle(self,*args,**opts):
        result=subprocess.run([opts['pg_restore'],'--schema-only','--no-owner','--no-privileges','--file=-',opts['backup']],capture_output=True,text=True,encoding='utf-8')
        if result.returncode: raise CommandError('No se pudo extraer el esquema del respaldo.')
        catalog=extract_catalog(result.stdout)
        if not catalog: raise CommandError('El respaldo no contiene tablas public verificables.')
        target=Path(opts['output']);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf-8')
        self.stdout.write(f'{len(catalog)} tablas; {sum(len(t["relations"]) for t in catalog)} relaciones. Sin filas de negocio.')
