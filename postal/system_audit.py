"""Content-free audit browsing and exports, restricted by the system view."""
import csv
from datetime import date, datetime, time
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone

from .models import SystemAudit


ACTION_LABELS = {
    'table_toggle': 'Permiso de tabla actualizado',
    'table_columns': 'Campos autorizados actualizados',
    'settings': 'Configuración actualizada', 'trash': 'Conversación a la papelera',
    'restore': 'Conversación restaurada', 'cleanup': 'Limpieza del sistema',
    'check_database': 'Conexión comprobada', 'chat_inspect': 'Conversación consultada',
    'skill_save': 'Skill guardada', 'skill_delete': 'Skill eliminada',
    'skill_toggle': 'Estado de skill cambiado', 'user_create': 'Usuario creado',
    'user_update': 'Usuario actualizado', 'user_enable': 'Usuario activado',
    'user_disable': 'Usuario desactivado', 'user_password_reset': 'Contraseña restablecida',
    'catalog_provider_save': 'Proveedor guardado', 'catalog_model_save': 'Modelo guardado',
    'catalog_key_save': 'Clave de API guardada', 'catalog_activate': 'Modelo principal seleccionado',
    'catalog_delete': 'Elemento del catálogo eliminado',
}


def action_label(action):
    return ACTION_LABELS.get(action, action.replace('_', ' ').capitalize())


def present(entry):
    entry.label = action_label(entry.action)
    entry.actor = entry.metadata.get('actor') or (entry.user.username if entry.user else 'Usuario eliminado')
    entry.category = ('Skills' if entry.action.startswith('skill_') else
                      'Usuarios' if entry.action.startswith('user_') else
                      'Modelos y API' if entry.action.startswith('catalog_') else
                      'Conversaciones' if entry.action in ('trash', 'restore', 'chat_inspect') else 'Sistema')
    entry.destructive = entry.action.endswith(('_delete', '_disable')) or entry.action == 'trash'
    entry.description = entry.detail or 'Sin detalles adicionales registrados.'
    if entry.action == 'skill_toggle' and ': ' in entry.detail:
        identity, state = entry.detail.rsplit(': ', 1)
        if identity.isdecimal() and state in ('True', 'False'):
            entry.description = f'Skill #{identity} · ' + ('Activada' if state == 'True' else 'Desactivada')
    return entry


def audit_context(request):
    records = SystemAudit.objects.select_related('user').order_by('-created_at', '-pk')
    filters = {key: request.GET.get(key, '').strip()[:150]
               for key in ('q', 'action_type', 'actor', 'start', 'end')}
    errors = []
    if filters['q']:
        records = records.filter(Q(detail__icontains=filters['q']) | Q(action__icontains=filters['q']) |
                                 Q(user__username__icontains=filters['q']) | Q(metadata__actor__icontains=filters['q']) |
                                 Q(metadata__resource__icontains=filters['q']))
    if filters['action_type']:
        records = records.filter(action=filters['action_type'])
    if filters['actor']:
        records = records.filter(metadata__actor=filters['actor']) | records.filter(user__username=filters['actor'])
    dates = {}
    for key in ('start', 'end'):
        if filters[key]:
            try:
                dates[key] = date.fromisoformat(filters[key])
            except ValueError:
                errors.append('Introduzca una fecha válida en el filtro de período.')
    if dates.get('start') and dates.get('end') and dates['start'] > dates['end']:
        errors.append('La fecha inicial debe ser anterior o igual a la fecha final.')
    for key, day in dates.items():
        boundary = timezone.make_aware(datetime.combine(day, time.min if key == 'start' else time.max))
        records = records.filter(**{'created_at__gte' if key == 'start' else 'created_at__lte': boundary})
    if errors:
        records = records.none()
    query = urlencode({'view': 'audit', **{key: value for key, value in filters.items() if value}})
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="auditoria.csv"'
        response.write('\ufeff')
        writer = csv.writer(response)
        writer.writerow(['ID', 'Fecha (America/La_Paz)', 'Administrador', 'Acción', 'Área', 'Recurso',
                         'Detalle', 'Campos modificados', 'IP directa', 'Método', 'Ruta'])
        for entry in records.iterator(chunk_size=500):
            entry = present(entry)
            values = [entry.pk, timezone.localtime(entry.created_at).isoformat(), entry.actor,
                      entry.label, entry.category, entry.metadata.get('resource', ''), entry.description,
                      ', '.join(entry.metadata.get('fields', [])), entry.metadata.get('ip', ''),
                      entry.metadata.get('method', ''), entry.metadata.get('path', '')]
            writer.writerow(["'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else value for value in values])
        return {}, response
    page = Paginator(records, 25).get_page(request.GET.get('page'))
    page.object_list = [present(entry) for entry in page.object_list]
    summary = records.aggregate(total=Count('pk'), actors=Count('user_id', distinct=True),
        today=Count('pk', filter=Q(created_at__gte=timezone.make_aware(datetime.combine(timezone.localdate(), time.min)))),
        sensitive=Count('pk', filter=Q(action__in=['skill_delete', 'catalog_delete', 'user_disable', 'user_password_reset', 'trash'])))
    all_actions = SystemAudit.objects.order_by().values_list('action', flat=True).distinct()
    actors = set(SystemAudit.objects.exclude(user=None).order_by().values_list('user__username', flat=True))
    actors.update(name for name in SystemAudit.objects.order_by().values_list('metadata__actor', flat=True).distinct() if name)
    return {'audits': page, 'audit_filters': filters, 'audit_errors': errors, 'audit_summary': summary,
            'audit_query': query, 'audit_actions': [(key, action_label(key)) for key in sorted(all_actions)],
            'audit_actors': sorted(actors)}, None
