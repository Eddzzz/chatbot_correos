"""Administrator-managed table permissions over projected, read-only sources."""
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.core.management.base import CommandError
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render

from .policy import SAFE_COLUMNS, available_columns, configurable_columns, catalog
from .data import projection_query
from .system_config import save_config, value


def prepare_table(name, columns, persist=None):
    """Add just the selected projection to the existing isolated query role."""
    editable = configurable_columns()
    if name not in editable or not columns or not set(columns) <= set(editable[name]):
        raise ValueError('La proyección contiene campos desconocidos o con protección obligatoria.')
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from .management.commands.restore_backup import require_isolated
    if not settings.BUSINESS_ADMIN_DATABASE_URL:
        raise ValueError('Para habilitar tablas nuevas, configura la conexión administrativa de PostgreSQL en el servidor.')
    try:
        reader = conninfo_to_dict(value('BUSINESS_DATABASE_URL'))
        admin = conninfo_to_dict(settings.BUSINESS_ADMIN_DATABASE_URL)
        def host(info):
            return (info.get('host', 'localhost').replace('127.0.0.1', 'localhost'), info.get('port', '5432'))
        if host(reader) != host(admin) or not reader.get('dbname') or not reader.get('user'):
            raise ValueError('Las conexiones administrativa y de consulta deben apuntar al mismo servidor PostgreSQL.')
        admin['dbname'] = reader['dbname']
        with psycopg.connect(make_conninfo(**admin), connect_timeout=value('DB_CONNECT_TIMEOUT')) as conn:
            require_isolated(conn)
            known = {row[0] for row in conn.execute(
                'SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s', ('public', name))}
            if name != 'user_roles' and not set(columns) <= known:
                raise ValueError('La estructura de la tabla no coincide con el catálogo. Actualiza el catálogo antes de habilitarla.')
            # A projected view cannot remove/reorder columns with CREATE OR REPLACE.
            # RESTRICT keeps external dependants intact; the transaction restores the old view on failure.
            conn.execute(sql.SQL('DROP VIEW IF EXISTS assistant.{}').format(sql.Identifier(name)))
            conn.execute(sql.SQL('CREATE VIEW assistant.{} WITH (security_barrier=true) AS {}').format(
                sql.Identifier(name), projection_query(name, columns)))
            conn.execute(sql.SQL('REVOKE ALL ON assistant.{} FROM PUBLIC').format(sql.Identifier(name)))
            conn.execute(sql.SQL('GRANT SELECT ON assistant.{} TO {}').format(sql.Identifier(name), sql.Identifier(reader['user'])))
            if persist:
                persist()
    except (psycopg.Error, CommandError):
        raise ValueError('No se pudo preparar la vista de solo lectura. Revisa la conexión administrativa y que la base sea la restauración aislada.') from None


def tables_page(request):
    from .system_views import audit
    available = available_columns()
    configurable = configurable_columns()
    if request.method == 'POST':
        action, name = request.POST.get('action'), request.POST.get('table', '')
        if action not in ('table_toggle', 'table_columns') or name not in available:
            return HttpResponseBadRequest('Selecciona una tabla del catálogo y un estado válido.')
        current_enabled = next(table['queryable'] for table in catalog() if table['name'] == name)
        if action == 'table_toggle':
            if request.POST.get('enabled') not in ('0', '1'):
                return HttpResponseBadRequest('Selecciona un estado válido.')
            enabled = request.POST['enabled'] == '1'
            columns = available[name]
            if enabled and not columns:
                return HttpResponseBadRequest('Autoriza al menos un campo antes de permitir esta tabla.')
            changes = {'TABLE_PERMISSIONS': {name: enabled}}
            prepare = enabled and (name not in SAFE_COLUMNS or name in value('COLUMN_PERMISSIONS'))
        else:
            selected = request.POST.getlist('columns')
            if not set(selected) <= set(configurable[name]):
                return HttpResponseBadRequest('Hay campos desconocidos o con protección obligatoria. No se guardaron cambios.')
            order = list(dict.fromkeys([*available[name], *configurable[name]]))
            columns = [column for column in order if column in selected]
            changes = {'COLUMN_PERMISSIONS': {name: columns}}
            if not columns:
                changes['TABLE_PERMISSIONS'] = {name: False}
            prepare = current_enabled and bool(columns)
        try:
            if prepare and value('DATA_MODE') == 'postgres' and settings.BUSINESS_USE_ISOLATED_VIEWS:
                prepare_table(name, columns, persist=lambda: save_config(changes))
            else:
                save_config(changes)
        except (ValueError, OSError) as exc:
            messages.error(request, str(exc) if isinstance(exc, ValueError) else 'No se pudo guardar el permiso. Revisa el almacenamiento del servidor.')
        else:
            if action == 'table_toggle':
                audit(request, action, name + (' · Permitida' if enabled else ' · Bloqueada'),
                      resource=name, fields=['enabled'], enabled=enabled)
                messages.success(request, f'Tabla {name} ' + ('permitida' if enabled else 'bloqueada') + '. Aplica a consultas nuevas.')
            else:
                audit(request, action, name + ' · ' + ', '.join(columns), resource=name,
                      fields=columns, authorized=columns, protected=[column for column in configurable[name] if column not in columns])
                messages.success(request, f'Campos de {name} guardados. Aplica a consultas nuevas.'
                                 + (' La tabla quedó bloqueada porque no tiene campos autorizados.' if not columns else ''))
        return redirect('/system/?' + urlencode({'view': 'tables', 'q': request.POST.get('q', '')[:150],
                                               'permission': request.POST.get('permission', '')[:15]}))
    query = request.GET.get('q', '').strip()[:150]
    permission = request.GET.get('permission', 'allowed')
    if permission not in ('allowed', 'blocked'):
        permission = 'allowed'
    tables = catalog()
    editor = None
    editing = request.GET.get('edit_fields', '')
    if editing:
        table = next((table for table in tables if table['name'] == editing), None)
        if table is None:
            return HttpResponseBadRequest('Selecciona una tabla del catálogo.')
        editor = {'name': editing, 'fields': [{'name': column['name'], 'selected': column['name'] in available[editing],
                  'locked': column['name'] not in configurable[editing]} for column in table['columns']]}
    return_url = '/system/?' + urlencode({'view': 'tables', 'permission': permission, 'q': query})
    physical = [table for table in tables if not table.get('derived')]
    counts = {'total': len(physical), 'allowed': sum(t['queryable'] for t in physical)}
    counts['blocked'] = counts['total'] - counts['allowed']
    rows = []
    for table in tables:
        if query.casefold() not in table['name'].casefold():
            continue
        if permission == 'allowed' and not table['queryable'] or permission == 'blocked' and table['queryable']:
            continue
        columns = available[table['name']]
        rows.append({'name': table['name'], 'enabled': table['queryable'], 'columns': columns,
                     'derived': table.get('derived', False),
                     'protected': [c['name'] for c in table['columns'] if c['name'] not in columns],
                     'editable': bool(columns), 'fields_editable': bool(configurable[table['name']])})
    return render(request, 'postal/system.html', {'active_view': 'tables', 'view_title': 'Permisos de tablas',
        'table_rows': rows, 'table_row_count': sum(not row['derived'] for row in rows),
        'table_counts': counts, 'table_query': query, 'table_permission': permission,
        'field_editor': editor, 'table_return_url': return_url})
