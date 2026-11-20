from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Count, Sum, Q, OuterRef, Subquery
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from .conversations import move_to_trash, purge_trash, restore
from .history import read_messages
from .models import AIUsage, AssistantSkill, Conversation, QueryJob, SystemAudit
from .system_config import DEFAULTS, configuration, save_config
from .system_forms import AnalyticsRangeForm, SkillForm, SystemConfigForm
from .skill_presets import SKILL_PRESETS
from .system_analytics import dashboard_data
from .ai import provider_config
from .token_availability import token_availability
from .system_users import account_context, account_counts
from .labels import COLUMN_LABELS, LABEL_WORDS

SYSTEM_VIEWS = {
    'overview': 'Resumen y analíticas',
    'manage': 'Centro de administración', 'users': 'Usuarios',
    'models': 'Modelos y API', 'network': 'Red y base de datos', 'agents': 'Agentes y tokens',
    'tables': 'Permisos de tablas',
    'skills': 'Gestor de skills', 'chats': 'Conversaciones', 'health': 'Estado y caché', 'audit': 'Actividad administrativa',
}


def audit(request, action, detail='', **metadata):
    SystemAudit.objects.create(user=request.user, action=action, detail=detail[:500], metadata={
        **metadata, 'actor': request.user.username, 'ip': request.META.get('REMOTE_ADDR', '')[:64],
        'method': request.method, 'path': request.path[:200],
    })


def database_check():
    from .data import get_source
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        source = get_source()
        table = next((item['name'] for item in source.catalog() if item['queryable']), None)
        if table is None:
            return 'Conexión a cuentas correcta. Todas las tablas postales están bloqueadas; no se consultaron sus datos.'
        with source.stream(f'SELECT COUNT(*) AS cantidad FROM assistant."{table}"') as stream:
            next(iter(stream.rows), None)
        return 'Conexión correcta a cuentas y al origen postal. Consulta ejecutada en modo de solo lectura.'
    except Exception:
        return 'No se pudo verificar el origen postal. Revise el servidor, las credenciales y los permisos de lectura.'


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def system_view(request):
    if not request.user.is_active or not request.user.is_superuser:
        return HttpResponseForbidden('Solo el administrador del sistema puede acceder.')
    purge_trash()
    active_view = request.GET.get('view', 'overview')
    if active_view == 'analytics':
        active_view = 'overview'
    if active_view not in SYSTEM_VIEWS:
        active_view = 'overview'
    if active_view == 'tables':
        from .table_permissions import tables_page
        return tables_page(request)
    if active_view == 'audit' and request.method == 'GET':
        from .system_audit import audit_context
        audit_data, response = audit_context(request)
        if response is not None:
            return response
        return render(request, 'postal/system.html', {
            'active_view': active_view, 'view_title': SYSTEM_VIEWS[active_view], **audit_data,
        })
    account_usage = AIUsage.objects.filter(user_id=OuterRef('pk')).order_by().values('user_id').annotate(tokens=Sum('total_tokens'))
    chat_accounts = get_user_model().objects.annotate(
        history_count=Count('conversation', filter=Q(conversation__deleted_at__isnull=True)),
        trash_count=Count('conversation', filter=Q(conversation__deleted_at__isnull=False)),
        token_total=Subquery(account_usage.values('tokens')[:1]),
    ).order_by('username', 'pk')
    chat_account = None
    chat_usage = None
    if active_view == 'chats' and request.GET.get('user'):
        account_id = request.GET['user']
        if not account_id.isdecimal() or len(account_id) > 18:
            raise Http404('Cuenta no válida.')
        chat_account = get_object_or_404(chat_accounts, pk=account_id)
        chat_usage = AIUsage.objects.filter(user=chat_account).aggregate(tokens=Sum('total_tokens'),
            prompt=Sum('prompt_tokens'), completion=Sum('completion_tokens'), calls=Count('pk'),
            reported=Count('total_tokens'))
        chat_usage['unreported'] = chat_usage['calls'] - chat_usage['reported']
    settings_area = request.POST.get('settings_area', active_view) if request.method == 'POST' else active_view
    if settings_area not in SystemConfigForm.AREAS:
        settings_area = None
    form = SystemConfigForm(request.POST if request.method == 'POST' and request.POST.get('action') == 'settings' else None,
                            area=settings_area)
    network_section = request.POST.get('network_section', request.GET.get('edit_network', ''))
    if network_section not in SystemConfigForm.NETWORK_SECTIONS:
        network_section = ''
    network_blocks = []
    if settings_area == 'network':
        saved_form = SystemConfigForm(area='network')
        for key, block in zip(('source', 'ai', 'postgres'), saved_form.blocks()):
            network_blocks.append({**block, 'key': key})
        if network_section:
            allowed = SystemConfigForm.NETWORK_SECTIONS[network_section]
            form.fields = {key: value for key, value in form.fields.items() if key in allowed}
    agent_section = request.POST.get('agent_section', request.GET.get('edit_agent', ''))
    if agent_section not in SystemConfigForm.AGENT_SECTIONS:
        agent_section = ''
    agent_blocks = []
    if settings_area == 'agents':
        for key, block in zip(('planner', 'analyst', 'tokens'), SystemConfigForm(area='agents').blocks()):
            agent_blocks.append({**block, 'key': key})
        if agent_section:
            allowed = SystemConfigForm.AGENT_SECTIONS[agent_section]
            form.fields = {key: value for key, value in form.fields.items() if key in allowed}
            for block in agent_blocks:
                if block['key'] == agent_section:
                    block['fields'] = [(form[name], None) for name in allowed]
    diagnostic = None
    skill_form = SkillForm(prefix='skill')
    editing_skill = None
    if active_view == 'skills' and request.GET.get('preset') and not request.GET.get('edit_skill'):
        skill = get_object_or_404(AssistantSkill, preset_key=request.GET['preset'])
        return redirect(f'/system/?view=skills&edit_skill={skill.pk}#skill-editor')
    users_context = {}
    catalog_data = {}
    if active_view == 'models' or request.POST.get('action', '').startswith('catalog_'):
        from .provider_catalog import catalog_context
        active_view = 'models'
        catalog_data, response = catalog_context(request) if request.POST.get('action') != 'settings' else ({}, None)
        if response is not None:
            return response
    if active_view == 'users' or request.POST.get('action') in ('user_save', 'user_toggle', 'user_password_reset'):
        active_view = 'users'
        users_context, response = account_context(request)
        if response is not None:
            return response
    if request.GET.get('edit_skill', '').isdigit():
        active_view = 'skills'
        editing_skill = get_object_or_404(AssistantSkill, pk=request.GET['edit_skill'])
        skill_form = SkillForm(instance=editing_skill, prefix='skill')
    if request.method == 'POST':
        action = request.POST.get('action')
        if action in ('user_save', 'user_toggle', 'user_password_reset') or action.startswith('catalog_'):
            pass  # Account validation errors are rendered in the users view.
        elif action == 'settings':
            if form.is_valid():
                try:
                    changes = form.changes()
                    save_config(changes)
                    if settings_area == 'models':
                        from .models import ProviderSelection
                        ProviderSelection.objects.filter(pk=1).update(active_model=None)
                except OSError:
                    form.add_error(None, 'No se pudo guardar la configuración. Revise permisos y espacio del servidor.')
                else:
                    audit(request, 'settings', ', '.join(sorted(changes)), fields=sorted(changes),
                          resource=SYSTEM_VIEWS.get(settings_area, 'Configuración'))
                    messages.success(request, 'Configuración guardada. Se aplicará a las consultas nuevas.')
                    return redirect('/system/?view=' + (settings_area or 'models'))
            active_view = settings_area or 'models'
        elif action in ('trash', 'restore'):
            try:
                import uuid
                chat_id = uuid.UUID(request.POST.get('chat_id', ''))
            except ValueError:
                return HttpResponseForbidden('Conversación no válida.')
            chat = get_object_or_404(Conversation, pk=chat_id,
                **({'user_id': chat_account.pk} if chat_account else {}))
            chat_return = '/system/?' + urlencode({'view': 'chats', 'user': chat.user_id,
                'trash': '1' if action == 'restore' else '0',
                **({'q': request.GET['q'][:150]} if request.GET.get('q') else {})})
            if action == 'trash':
                move_to_trash(chat)
            elif not restore(chat):
                messages.error(request, 'La conversación ya no se puede restaurar.')
                return redirect(chat_return)
            audit(request, action, str(chat.pk), resource=f'Conversación #{chat.pk}')
            messages.success(request, 'Conversación enviada a la papelera.' if action == 'trash' else 'Conversación restaurada.')
            return redirect(chat_return)
        elif action == 'cleanup':
            from .jobs import maintain_results
            maintain_results(force=True)
            cache.clear()
            audit(request, 'cleanup', 'Resultados vencidos, papelera vencida y caché Django.')
            messages.success(request, 'Caché limpiada y mantenimiento de resultados y papelera completado.')
            return redirect('/system/?view=health')
        elif action == 'check_database':
            diagnostic = database_check()
            active_view = 'network' if active_view == 'network' else 'health'
            audit(request, 'check_database')
        elif action in ('skill_save', 'skill_delete', 'skill_toggle'):
            active_view = 'skills'
            skill_id = request.POST.get('skill_id', '')
            if skill_id and not skill_id.isdigit():
                return HttpResponseForbidden('Skill no válida.')
            editing_skill = get_object_or_404(AssistantSkill, pk=skill_id) if skill_id else None
            if action == 'skill_toggle':
                if editing_skill is None or request.POST.get('enabled') not in ('0', '1'):
                    return HttpResponseForbidden('Seleccione una skill y un estado válido.')
                editing_skill.enabled = request.POST['enabled'] == '1'
                editing_skill.save(update_fields=['enabled', 'updated_at'])
                audit(request, 'skill_toggle', f'{editing_skill.name} · ' + ('Activada' if editing_skill.enabled else 'Desactivada'),
                      resource=f'Skill #{editing_skill.pk}', fields=['enabled'])
                messages.success(request, 'Skill activada.' if editing_skill.enabled else 'Skill desactivada.')
                return redirect('/system/?view=skills#' + ('skill-presets' if editing_skill.preset_key else 'custom-skills'))
            if action == 'skill_delete':
                if editing_skill is None:
                    return HttpResponseForbidden('Seleccione una skill.')
                if editing_skill.preset_key:
                    return HttpResponseForbidden('Las skills predefinidas se pueden desactivar o editar.')
                audit(request, 'skill_delete', editing_skill.name, resource=f'Skill #{editing_skill.pk}')
                editing_skill.delete()
                messages.success(request, 'Skill eliminada.')
                return redirect('/system/?view=skills')
            skill_form = SkillForm(request.POST, instance=editing_skill, prefix='skill')
            if skill_form.is_valid():
                skill = skill_form.save()
                audit(request, 'skill_save', skill.name, resource=f'Skill #{skill.pk}',
                      fields=list(skill_form.changed_data), operation='updated' if editing_skill else 'created')
                messages.success(request, 'Skill guardada. Aplica a consultas nuevas.')
                return redirect('/system/?view=skills')
        else:
            return HttpResponseForbidden('Acción no válida.')
    current = configuration()
    effective_provider = provider_config()
    try:
        days = int(request.GET.get('days', '30'))
    except ValueError:
        days = 30
    analytics = dashboard_data(days)
    custom_period = request.GET.get('days') == 'custom'
    analytics_range = AnalyticsRangeForm(request.GET if custom_period else None,
        initial={'start': analytics['start'], 'end': analytics['end']})
    if custom_period and analytics_range.is_valid():
        analytics = dashboard_data(start_date=analytics_range.cleaned_data['start'], end_date=analytics_range.cleaned_data['end'])
    analytics_period = 'custom' if custom_period else str(analytics['days'])
    chart_data = {name: analytics[name] for name in ('daily', 'models', 'stages', 'users', 'totals')}
    chart_data['daily'] = [row for row in analytics['hourly'] if row['calls'] is not None] if analytics['hourly'] else analytics['daily']
    dashboard_context = {
        'analytics': analytics, 'chart_data': chart_data,
        'available_tokens': token_availability(provider_config()),
        'active_jobs': QueryJob.objects.filter(status__in=['queued', 'running']).count(),
        'current_provider': effective_provider[0], 'current_model': effective_provider[3],
        'provider_configured': bool(effective_provider[1]),
        'planner_enabled': current['PLANNER_ENABLED'], 'analyst_enabled': current['ANALYST_ENABLED'],
    }
    if request.method == 'GET' and active_view == 'overview' and request.GET.get('live') == '1':
        if not constant_time_compare(request.headers.get('X-Bolipost-User', ''), request.api_identity):
            return HttpResponseForbidden('Recargue la página para continuar con su sesión.')
        response = render(request, 'postal/_system_dashboard_values.html', dashboard_context)
        response['X-Bolipost-User'] = request.api_identity
        return response
    parsed = urlsplit(current['BUSINESS_DATABASE_URL'])
    # Never expose the password, username or query parameters of the connection URL.
    database = {'engine': 'PostgreSQL' if current['DATA_MODE'] == 'postgres' else 'Demostración',
                'host': parsed.hostname or 'Sin configurar', 'name': parsed.path.lstrip('/') or 'Sin configurar',
                'accounts': str(settings.DATABASES['default']['NAME'])}
    chats = Conversation.objects.select_related('user')
    trash = request.GET.get('trash') == '1'
    chats = chats.filter(deleted_at__isnull=not trash)
    if chat_account:
        chats = chats.filter(user=chat_account)
    chats = chats.order_by('-deleted_at', '-id') if trash else chats.order_by('-updated_at', '-id')
    search = request.GET.get('q', '').strip()[:150]
    if search:
        chats = chats.filter(Q(title__icontains=search) if chat_account else
            Q(title__icontains=search) | Q(user__username__icontains=search))
        chat_accounts = chat_accounts.filter(Q(username__icontains=search) |
            Q(first_name__icontains=search) | Q(last_name__icontains=search) | Q(email__icontains=search))
    chat_query = urlencode({'view': 'chats', 'trash': '1' if trash else '0', 'q': search,
        **({'user': chat_account.pk} if chat_account else {})})
    usage = AIUsage.objects.filter(created_at__gte=timezone.make_aware(datetime.fromisoformat(analytics['start'])),
                                   created_at__lte=datetime.fromisoformat(analytics['until']))
    totals = usage.aggregate(prompt=Sum('prompt_tokens'), completion=Sum('completion_tokens'), total=Sum('total_tokens'), calls=Count('id'))
    grouped = usage.values('user__username', 'provider', 'model', 'stage').annotate(
        tokens=Sum('total_tokens'), calls=Count('id')).order_by('-tokens')[:100]
    files = list(Path(settings.RESULT_DIR).glob('*.sqlite3'))
    size = 0
    for path in files:
        try:
            size += path.stat().st_size
        except OSError:
            pass
    health = {}
    if active_view == 'health':
        from .system_health import health_data
        health = health_data(files)
        health['users'] = Paginator(health['users'], 25).get_page(request.GET.get('page'))
    return render(request, 'postal/system.html', {
        'health': health,
        'form': form, 'sections': form.sections(), 'database': database, 'diagnostic': diagnostic,
        'network_defaults': {name: DEFAULTS[name] for name in ('AI_TIMEOUT', 'AI_CONNECT_TIMEOUT', 'DB_CONNECT_TIMEOUT', 'DB_STATEMENT_TIMEOUT')},
        'network_section': network_section, 'network_blocks': network_blocks,
        'network_url_configured': bool(current['BUSINESS_DATABASE_URL']),
        'agent_section': agent_section, 'agent_blocks': agent_blocks,
        'agent_values': {key: current[key] for key in SystemConfigForm.AREAS['agents']},
        'chats': Paginator(chats.defer('messages'), 25).get_page(request.GET.get('page')),
        'trash': trash, 'search': search, 'totals': totals, 'usage': grouped,
        'chat_account': chat_account, 'chat_usage': chat_usage,
        'chat_accounts': Paginator(chat_accounts, 25).get_page(request.GET.get('page')),
        'chat_query': chat_query,
        'cache_files': len(files), 'cache_bytes': size, 'audits': SystemAudit.objects.select_related('user')[:20],
        'skills': AssistantSkill.objects.filter(preset_key__isnull=True), 'skill_form': skill_form, 'editing_skill': editing_skill,
        'skill_presets': [{'skill': skill, 'category': next((preset['category'] for preset in SKILL_PRESETS if preset['id'] == skill.preset_key), 'Analítica')}
                         for skill in AssistantSkill.objects.filter(preset_key__isnull=False)],
        'show_skill_editor': bool(editing_skill or skill_form.is_bound or request.GET.get('new_skill') == '1'),
        'active_view': active_view, 'view_title': SYSTEM_VIEWS[active_view],
        'system_navigation': [{'id': key, 'label': label} for key, label in SYSTEM_VIEWS.items()],
        'analytics_range': analytics_range,
        'custom_period': custom_period, 'analytics_period': analytics_period,
        **dashboard_context,
        'account_counts': account_counts(), 'settings_blocks': form.blocks(),
        'skill_count': AssistantSkill.objects.filter(enabled=True).count(),
        **users_context, **catalog_data,
    })


@login_required
@never_cache
@require_http_methods(['GET'])
def trash_page(request):
    return render(request, 'postal/trash.html')


@login_required
@never_cache
@require_http_methods(['GET'])
def chat_inspect(request, chat_id):
    if not request.user.is_active or not request.user.is_superuser:
        return HttpResponseForbidden('Solo el administrador del sistema puede acceder.')
    purge_trash()
    chat = get_object_or_404(Conversation.objects.select_related('user'), pk=chat_id)
    transcript, unverified_results = read_messages(chat)
    audit(request, 'chat_inspect', str(chat.pk))
    return render(request, 'postal/chat_inspect.html', {
        'chat': chat, 'transcript': transcript, 'unverified_results': unverified_results, 'active_view': 'chats',
        'column_labels': COLUMN_LABELS, 'label_words': LABEL_WORDS,
    })
