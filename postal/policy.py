"""Default-deny field projection and PostgreSQL AST validation."""
import json
import re
from pathlib import Path
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify
from sqlglot.schema import MappingSchema

class QueryRejected(Exception):
    code='query_rejected'
    def __init__(self,message='La consulta solicita una operación o un campo no autorizado.'):
        self.message=message
        super().__init__(message)

# Every field here was reviewed against the backup's schema. New fields stay denied.
SAFE_COLUMNS={
 'paquetes_ems': ('id','codigo','origen','ciudad','peso','precio','cantidad','tipo_correspondencia','estado_id','created_at','updated_at','user_id'),
 'paquetes_ems_formulario': ('id','paquete_ems_id','codigo','origen','ciudad','peso','precio','cantidad','tipo_correspondencia','servicio_id','destino_id','created_at','updated_at'),
 'paquetes_certi': ('id','codigo','cuidad','peso','precio','tipo','fk_estado','fk_ventanilla','servicio_id','created_at','updated_at'),
 'paquetes_contrato': ('id','codigo','origen','destino','peso','precio','estados_id','created_at','updated_at','fecha_recojo','user_id'),
 'paquetes_int': ('id','codigo','peso','destino','origen','precio','servicio_id','estado_id','created_at','updated_at'),
 'paquetes_ordi': ('id','codigo','ciudad','peso','precio','tipo','pais','fk_estado','fk_ventanilla','servicio_id','created_at','updated_at'),
 'eventos': ('id','nombre_evento','created_at','updated_at'),
 'sucursales': ('id','codigoSucursal','puntoVenta','municipio','departamento','telefono','created_at','updated_at'),
 'users': ('id','role_id','sucursal_id'),
 'estados': ('id','nombre_estado','activo'),
 'roles': ('id','name','nombre'),
 'user_roles': ('user_id','role_id'),
 'servicio': ('id','nombre_servicio'),
}
for _family in ('ems','certi','contrato','ordi'):
    SAFE_COLUMNS['eventos_'+_family]=('id','codigo','evento_id','created_at','updated_at')

CATALOG_PATH=Path(__file__).resolve().parent.parent/'data'/'catalog.json'
USER_ROLES_SOURCE = 'user_roles'
INTERNAL_TABLES = {
    'activity_logs', 'app_settings', 'cache', 'cache_locks', 'external_api_tokens',
    'failed_jobs', 'job_batches', 'jobs', 'migrations', 'model_has_permissions',
    'model_has_roles', 'password_reset_tokens', 'permissions', 'personal_access_tokens',
    'role_has_permissions', 'sessions', 'system_audit_logs', 'user_ips_links', 'user_login_logs',
}


def internal_table(name):
    return name in INTERNAL_TABLES or name.startswith(('pulse_', 'telescope_', 'oauth_'))


def _catalog_entries():
    tables = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
    roles = {
        'name': USER_ROLES_SOURCE,
        'derived': True,
        'columns': [{'name': name, 'type': 'bigint'} for name in ('user_id', 'role_id')],
        'relations': [{'column': column, 'table': table, 'target': 'id'}
                      for column, table in (('user_id', 'users'), ('role_id', 'roles'))],
    }
    return [roles, *(table for table in tables if table['name'] != USER_ROLES_SOURCE)]


def configurable_columns():
    """Internal tables and protected fields stay outside the query projection."""
    tables=_catalog_entries()
    def selectable(table, column):
        name=column['name'].casefold()
        parts=set(re.split(r'[^a-z0-9]+', name))
        if internal_table(table):
            return False
        if table == 'users' and (name in {'name', 'alias'} or parts & {'email', 'ci', 'carnet', 'documento'}):
            return False
        if parts & {'destinatario', 'remitente'} and (len(parts) == 1 or parts & {
                'nombre', 'telefono', 'direccion', 'email', 'ci'}):
            return False
        if parts & {'password','passwd','secret','token','apikey','authorization','credentials','credential',
                    'cookie','cookies','payload','exception','clave','contrasena','recovery','authentication','hash','otp'}:
            return False
        if parts & {'session','auth'} and not (name.endswith('_id') and column.get('type') in ('bigint','integer','smallint')):
            return False
        if 'api' in parts and 'key' in parts:
            return False
        if name == 'id' and 'token' in table:
            return column.get('type') in ('bigint','integer','smallint')
        return True
    return {table['name']: tuple(column['name'] for column in table['columns'] if selectable(table['name'], column)) for table in tables}


def available_columns():
    """Reviewed defaults, with administrator-selected fields inside fixed credential limits."""
    from .system_config import value
    tables=_catalog_entries()
    additional={'auditoria': ('id','nombre_evento','created_at','updated_at')}
    defaults={table['name']: SAFE_COLUMNS.get(table['name'], additional.get(table['name'], tuple(
        column['name'] for column in table['columns'] if
        (column['name'] == 'id' or column['name'].endswith('_id')) and column.get('type') in ('bigint','integer','smallint')
        or column['name'] in ('created_at','updated_at') and column.get('type','').startswith(('timestamp','date'))))) for table in tables}
    configurable=configurable_columns()
    defaults={name: tuple(column for column in columns if column in configurable[name]) for name, columns in defaults.items()}
    overrides=value('COLUMN_PERMISSIONS')
    if not overrides:
        return defaults
    for name, selected in overrides.items():
        if name not in defaults:
            continue
        order=list(dict.fromkeys([*defaults[name], *configurable[name]]))
        defaults[name]=tuple(column for column in order if column in selected and column in configurable[name])
    return defaults


def authorized_columns():
    from .system_config import value
    permissions=value('TABLE_PERMISSIONS')
    if not permissions and not value('COLUMN_PERMISSIONS'):
        return SAFE_COLUMNS.copy()
    available=available_columns()
    return {name: columns for name,columns in available.items() if columns
            and permissions.get(name, name in SAFE_COLUMNS) is True}


def catalog():
    tables=_catalog_entries()
    authorized=authorized_columns()
    for table in tables:
        allowed=authorized.get(table['name'],())
        table['allowed_columns']=[c['name'] for c in table['columns'] if c['name'] in allowed]
        table['queryable']=bool(table['allowed_columns'])
        for c in table['columns']: c['allowed']=c['name'] in allowed
    return tables


def public_catalog(tables=None):
    tables = catalog() if tables is None else tables
    allowed = {table['name']: set(table['allowed_columns']) for table in tables if table['queryable']}
    return [{
        'name': table['name'],
        'columns': [{'name': column['name'], 'type': column['type']}
                    for column in table['columns'] if column['name'] in allowed[table['name']]],
        'relations': [{key: relation[key] for key in ('column', 'table', 'target', 'inferred') if key in relation}
                      for relation in table.get('relations', [])
                      if relation['column'] in allowed[table['name']]
                      and relation['target'] in allowed.get(relation['table'], set())],
    } for table in tables if table['name'] in allowed]

# Deliberately finite expression grammar; unsupported SQL is rejected, never passed through.
NODES=set('Select Union Intersect Except With CTE From Table TableAlias Identifier Column Star Alias Join Where Group Having Order Ordered Limit Offset Distinct Subquery Paren Literal Null Boolean Placeholder EQ NEQ GT GTE LT LTE And Or Not Add Sub Mul Div Mod Neg Between In Is Like ILike Escape Case If When Tuple Exists Count Sum Avg Min Max Coalesce Nullif Round Abs Lower Upper Length Trim DateTrunc TimestampTrunc Extract Cast DataType DataTypeParam Interval Window Partition RowNumber Rank DenseRank Lag Lead Filter WithinGroup Var Date Timestamp CurrentDate CurrentTimestamp'.split())
FUNCTIONS={'COUNT','SUM','AVG','MIN','MAX','COALESCE','NULLIF','ROUND','ABS','LOWER','UPPER','LENGTH','TRIM','DATE_TRUNC','TIMESTAMP_TRUNC','EXTRACT','ROW_NUMBER','RANK','DENSE_RANK','LAG','LEAD','CURRENT_DATE','CURRENT_TIMESTAMP','CAST','CASE','IF','DATE','TIMESTAMP'}
CAST_TYPES={'TEXT','VARCHAR','CHAR','INT','BIGINT','SMALLINT','DECIMAL','NUMERIC','FLOAT','DOUBLE','BOOLEAN','DATE','TIMESTAMP','TIMESTAMPTZ'}

def validate_sql(sql, *, allowed=None):
    if not isinstance(sql,str) or not sql.strip() or len(sql)>30000: raise QueryRejected()
    try:
        if allowed is None:
            allowed=authorized_columns()
        statements=sqlglot.parse(sql,read='postgres')
        if len(statements)!=1 or not isinstance(statements[0],(exp.Select,exp.Union,exp.Intersect,exp.Except)): raise QueryRejected()
        tree=statements[0]
        for node in tree.walk():
            if type(node).__name__ not in NODES: raise QueryRejected()
            if isinstance(node,exp.Func) and not isinstance(node,(exp.And,exp.Or)) and node.sql_name().upper() not in FUNCTIONS: raise QueryRejected()
            if isinstance(node,exp.Cast) and node.to.this.value.upper() not in CAST_TYPES: raise QueryRejected()
            if isinstance(node,exp.Table) and (node.catalog or node.db and node.db!='assistant'): raise QueryRejected()
            if isinstance(node,exp.Table) and node.db=='assistant' and node.name not in allowed: raise QueryRejected('La tabla no está permitida por la configuración de Administración.')
        # qualify resolves CTE/subquery aliases and validates every reference, including predicates.
        schema=MappingSchema({'assistant':{table:{column:'UNKNOWN' for column in columns} for table,columns in allowed.items()}},dialect='postgres',normalize=False)
        qualified=qualify(tree,dialect='postgres',schema=schema,validate_qualify_columns=True,identify=False)
        from sqlglot.optimizer.scope import traverse_scope
        if any(type(node).__name__ not in NODES for node in qualified.walk()): raise QueryRejected()
        sources=[]
        for scope in traverse_scope(qualified):
            for _,source in scope.sources.items():
                if isinstance(source,exp.Table):
                    if source.db!='assistant' or source.name not in allowed: raise QueryRejected()
                    if source.name not in sources: sources.append(source.name)
        # No composite whole-row references: the qualifier treats these as unknown columns.
        return qualified,sources
    except QueryRejected: raise
    except Exception as exc: raise QueryRejected() from exc


def _ai_structural_literal(node):
    """Literal arguments configuring a transform cannot supply reported data values."""
    parent=node.parent
    if isinstance(parent,(exp.TimestampTrunc,exp.DateTrunc)) and node.arg_key=='unit':
        return node.is_string
    if isinstance(parent,exp.Round) and node.arg_key=='decimals':
        return not node.is_string and node.this.isdigit() and 0<=int(node.this)<=12
    return isinstance(parent,exp.DataTypeParam) and not node.is_string and node.this.isdigit()


def _ai_measure(node):
    return node is not None and (node.find(exp.Column) is not None or
        any(isinstance(count.this,exp.Star) for count in node.find_all(exp.Count)))


def _ai_unwrap(node):
    while isinstance(node,(exp.Paren,exp.Cast)):
        node=node.this
    return node


def _ai_analytical_constants(projection):
    """Allow fixed percentage scaling and null-count indicators, never arbitrary offsets."""
    allowed=set()
    for node in projection.walk():
        if isinstance(node,exp.Nullif) and _ai_measure(node.this):
            zero=node.expression
            if isinstance(zero,exp.Literal) and not zero.is_string and zero.this=='0':
                allowed.add(id(zero))
        if isinstance(node,exp.Mul):
            for factor,measure in ((node.this,node.expression),(node.expression,node.this)):
                if not (isinstance(factor,exp.Literal) and not factor.is_string and
                        factor.this in ('100','100.0')):
                    continue
                ratio=_ai_unwrap(measure)
                if isinstance(ratio,exp.Div) and _ai_measure(ratio.this) and _ai_measure(ratio.expression):
                    allowed.add(id(factor))
                parent=node.parent
                while isinstance(parent,(exp.Paren,exp.Cast)):
                    parent=parent.parent
                if (isinstance(parent,exp.Div) and _ai_unwrap(parent.this) is node and
                        _ai_measure(measure) and _ai_measure(parent.expression)):
                    allowed.add(id(factor))
        if isinstance(node,(exp.Sum,exp.Count)):
            case=node.this
            if not isinstance(case,exp.Case) or case.this is not None or len(case.args.get('ifs',[]))!=1:
                continue
            branch=case.args['ifs'][0]
            predicate=branch.this
            if isinstance(predicate,exp.Not):
                predicate=predicate.this
            if not (isinstance(predicate,exp.Is) and isinstance(predicate.this,exp.Column) and
                    isinstance(predicate.expression,exp.Null)):
                continue
            one=branch.args.get('true')
            default=case.args.get('default')
            if not (isinstance(one,exp.Literal) and not one.is_string and one.this=='1'):
                continue
            if isinstance(node,exp.Sum):
                valid_default=isinstance(default,exp.Literal) and not default.is_string and default.this=='0'
            else:
                valid_default=default is None or isinstance(default,exp.Null)
            if valid_default:
                allowed.update(id(value) for value in (predicate.expression,one,default) if value is not None)
        if isinstance(node,exp.Filter) and isinstance(node.this,exp.Count):
            where=node.expression
            predicate=where.this if isinstance(where,exp.Where) else None
            if isinstance(predicate,exp.Not):
                predicate=predicate.this
            if (isinstance(predicate,exp.Is) and isinstance(predicate.this,exp.Column) and
                    isinstance(predicate.expression,exp.Null)):
                allowed.add(id(predicate.expression))
    return allowed


def _catalog_history_dates(scope):
    tables = {alias: source.name for alias, source in scope.sources.items() if isinstance(source, exp.Table)}
    histories = [alias for alias, name in tables.items() if name in ('eventos_ems', 'eventos_certi', 'eventos_contrato', 'eventos_ordi')]
    columns = [column for column in scope.columns if tables.get(column.table) == 'eventos'
               and column.name in ('created_at', 'updated_at')]
    return histories, columns


def normalize_history_dates(sql):
    """A history query dates the package event, never the reusable event definition."""
    from sqlglot.optimizer.scope import traverse_scope
    tree, _ = validate_sql(sql)
    for scope in traverse_scope(tree):
        histories, columns = _catalog_history_dates(scope)
        if not histories or not columns:
            continue
        if len(histories) != 1:
            raise QueryRejected('La fecha del movimiento debe identificar su historial de servicio, no el catálogo eventos.')
        for column in columns:
            column.set('table', exp.to_identifier(histories[0]))
    return tree.sql(dialect='postgres')


def validate_ai_sql(sql):
    """Require source-derived projections for model plans, beyond read-only safety.

    This establishes data provenance, not that a query matches the user's intent.
    Server-owned SQL (for example tracking service labels) uses validate_sql instead.
    """
    tree,sources=validate_sql(sql)
    if not sources: raise QueryRejected('El plan debe consultar fuentes autorizadas.')
    from sqlglot.optimizer.scope import traverse_scope
    for scope in traverse_scope(tree):
        histories, dates = _catalog_history_dates(scope)
        if histories and dates:
            raise QueryRejected('Use created_at/updated_at del historial eventos del servicio para las fechas del movimiento; eventos solo define nombres.')
        select=scope.expression
        if not isinstance(select,exp.Select): continue
        # Reject source-free COUNT(*) even when another CTE supplies a real table.
        if not scope.selected_sources: raise QueryRejected('Cada SELECT debe leer una fuente en FROM; declarar un CTE sin usarlo no cuenta filas de esa fuente.')
        for projection in select.expressions:
            nodes=list(projection.walk())
            analytical_constants=_ai_analytical_constants(projection)
            for node in nodes:
                if id(node) in analytical_constants:
                    continue
                if isinstance(node,exp.Literal) and not _ai_structural_literal(node):
                    raise QueryRejected('El plan no puede inventar valores en las columnas del resultado.')
                if isinstance(node,(exp.Boolean,exp.Null,exp.Placeholder,exp.CurrentDate,exp.CurrentTimestamp)):
                    raise QueryRejected('Las columnas del resultado deben proceder de datos autorizados.')
            has_field=any(isinstance(node,exp.Column) for node in nodes)
            has_count=any(isinstance(node,exp.Count) and isinstance(node.this,exp.Star) for node in nodes)
            if not (has_field or has_count):
                raise QueryRejected('Cada columna debe derivarse de un campo o un conteo de la fuente.')
    return tree,sources


def ai_chart_supported(sql,label_column,value_column):
    """Conservative chart eligibility: direct grouped aggregate, verified SQL aliases.

    Aggregate values hidden behind CTE aliases are left as tables, rather than inferred.
    """
    try:
        tree,_=validate_ai_sql(sql)
    except QueryRejected:
        return False
    if not isinstance(tree,exp.Select) or not tree.args.get('group'):
        return False
    projections={item.alias_or_name:item.unalias() for item in tree.expressions}
    if len(projections)!=len(tree.expressions): return False
    label=projections.get(label_column);value=projections.get(value_column)
    if label is None or value is None: return False
    if any(isinstance(node,exp.Window) for node in value.walk()): return False
    if not any(isinstance(node,exp.AggFunc) for node in value.walk()): return False
    # The label must identify an actual grouping expression, not an arbitrary field.
    groups={item.sql(dialect='postgres') for item in tree.args['group'].expressions}
    return label.sql(dialect='postgres') in groups
