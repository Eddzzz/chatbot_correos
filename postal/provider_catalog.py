"""Administrative provider catalog and private runtime connection snapshots."""
from urllib.parse import urlsplit

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.db.models import Max
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect

from .models import AIProvider, ProviderModel, ProviderKey, ProviderSelection
from .system_config import configuration


def is_openrouter_endpoint(url):
    host = urlsplit(url).hostname or ''
    return host == 'openrouter.ai' or host.endswith('.openrouter.ai')


class ApiSecretField(forms.CharField):
    def __init__(self, **kwargs):
        super().__init__(label='Clave API', max_length=4096, required=False,
            widget=forms.PasswordInput(attrs={'autocomplete': 'new-password', 'spellcheck': 'false',
                                               'autocapitalize': 'none'}), **kwargs)

    def to_python(self, value):
        if value and any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValidationError('La clave no puede contener saltos de línea ni caracteres de control.')
        return super().to_python(value)


class ProviderForm(forms.ModelForm):
    class Meta:
        model = AIProvider
        fields = ['name', 'endpoint', 'enabled']
        labels = {'name': 'Nombre del proveedor', 'endpoint': 'URL de chat completions',
                  'enabled': 'Proveedor habilitado'}
        widgets = {'endpoint': forms.URLInput(attrs={'placeholder': 'https://api.ejemplo.com/v1/chat/completions'})}
        help_texts = {'endpoint': 'Pegue la URL completa de Chat Completions compatible con OpenAI, sin credenciales.'}

    def clean_endpoint(self):
        value = self.cleaned_data['endpoint']
        parsed = urlsplit(value)
        try:
            parsed.port
        except ValueError:
            raise ValidationError('Indique un puerto válido en la URL.')
        if (parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', '::1'))
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValidationError('Use HTTPS, sin credenciales, parámetros ni fragmentos. HTTP solo se admite para localhost.')
        return value

    def save(self, commit=True):
        provider = super().save(commit=False)
        if is_openrouter_endpoint(provider.endpoint):
            provider.protocol = 'openrouter'
        elif urlsplit(provider.endpoint).hostname != urlsplit(self.initial.get('endpoint') or '').hostname:
            # Preserve the policy for previously configured proxies on the same host.
            provider.protocol = 'openai'
        if commit:
            provider.save()
        return provider


class NewProviderForm(ProviderForm):
    initial_secret = ApiSecretField(help_text='Se guardará como clave principal. También puede agregarla más tarde.')

    class Meta(ProviderForm.Meta):
        fields = ['name', 'endpoint', 'initial_secret', 'enabled']


class ModelForm(forms.ModelForm):
    class Meta:
        model = ProviderModel
        fields = ['name', 'identifier', 'enabled', 'fallback_enabled', 'priority']
        labels = {'name': 'Nombre visible', 'identifier': 'Identificador del modelo', 'enabled': 'Modelo habilitado',
                  'fallback_enabled': 'Incluir como respaldo automático', 'priority': 'Prioridad de respaldo'}
        help_texts = {'identifier': 'Use el identificador exacto que acepta la API del proveedor.',
                      'priority': 'El principal siempre va primero. Los respaldos se prueban de menor a mayor prioridad.'}


class BackupModelChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f'{obj.provider.name} · {obj.name} ({obj.identifier})'


class BackupForm(forms.Form):
    model = BackupModelChoice(label='Proveedor y modelo', queryset=ProviderModel.objects.none(),
        empty_label='Seleccione un modelo listo para usar')
    priority = forms.IntegerField(min_value=0, max_value=2147483647, widget=forms.HiddenInput)

    def __init__(self, *args, active_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['model'].queryset = ProviderModel.objects.filter(enabled=True, provider__enabled=True,
            provider__keys__enabled=True).exclude(pk=active_id).select_related('provider').distinct().order_by('provider__name', 'name')
        self.initial['priority'] = (ProviderModel.objects.filter(fallback_enabled=True).aggregate(last=Max('priority'))['last'] or 0) + 1


class KeyForm(forms.ModelForm):
    secret = ApiSecretField(help_text='Pegue la clave que le dio su proveedor.')

    class Meta:
        model = ProviderKey
        fields = ['name', 'secret', 'priority', 'enabled']
        labels = {'name': 'Nombre de la clave', 'priority': 'Orden de uso', 'enabled': 'Clave habilitada'}
        help_texts = {'priority': 'Primero se usa el número menor. Las demás claves sirven de respaldo ante límites o falta de saldo.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['secret'].required = not bool(self.instance.pk)
        if self.instance.pk:
            self.fields['secret'].help_text = 'Deje el campo vacío para conservar la clave guardada.'
        self.initial['secret'] = ''
        if not self.instance.pk and self.instance.provider_id:
            self.initial['priority'] = (self.instance.provider.keys.aggregate(last=Max('priority'))['last'] or 0) + 1

    def clean_secret(self):
        return self.cleaned_data['secret'] or self.instance.secret


def initialize_catalog():
    """Import the current connection once, including its existing backup credentials."""
    with transaction.atomic():
        state, created = ProviderSelection.objects.get_or_create(pk=1)
        if not created:
            return state
        cfg = configuration()
        endpoints = {
            'groq': ('Groq', 'https://api.groq.com/openai/v1/chat/completions', 'GROQ_MODEL', ['GROQ_API_KEY', 'GROQ_BACKUP_API_KEY']),
            'nvidia': ('NVIDIA', 'https://integrate.api.nvidia.com/v1/chat/completions', 'NVIDIA_MODEL', ['NVIDIA_API_KEY']),
            'cloudflare': ('Cloudflare', 'https://api.cloudflare.com/client/v4/accounts/' + cfg['CLOUDFLARE_ACCOUNT_ID'] + '/ai/v1/chat/completions', 'CLOUDFLARE_MODEL', ['CLOUDFLARE_API_TOKEN']),
            'openrouter': ('OpenRouter', 'https://openrouter.ai/api/v1/chat/completions', 'OPENROUTER_MODEL', ['OPENROUTER_API_KEY']),
        }
        for code, (name, endpoint, model_field, keys) in endpoints.items():
            provider = AIProvider.objects.create(name=name, endpoint=endpoint, legacy_code=code,
                protocol='openrouter' if code == 'openrouter' else 'openai')
            identifier = cfg[model_field].strip()
            if identifier:
                model = ProviderModel.objects.create(provider=provider, name=identifier[:80], identifier=identifier,
                    fallback_enabled=code == 'openrouter' and cfg['AI_PROVIDER'] == 'groq')
                if cfg['AI_PROVIDER'] == code:
                    state.active_model = model
                    state.save(update_fields=['active_model'])
            for priority, field in enumerate(keys, 1):
                if cfg[field].strip():
                    ProviderKey.objects.create(provider=provider, name='Principal' if priority == 1 else 'Respaldo',
                        secret=cfg[field].strip(), priority=priority)
        return state


def ordered_models(state):
    if not state or not state.active_model_id:
        return []
    primary = state.active_model
    backups = ProviderModel.objects.filter(fallback_enabled=True, enabled=True, provider__enabled=True).exclude(
        pk=primary.pk).select_related('provider').prefetch_related('provider__keys').order_by('priority', 'pk')
    return [model for model in [primary, *backups] if model.enabled and model.provider.enabled
            and any(key.enabled for key in model.provider.keys.all())]


def active_connection():
    state = ProviderSelection.objects.select_related('active_model__provider').filter(pk=1).first()
    if not state or not state.active_model_id:
        return None
    model, provider = state.active_model, state.active_model.provider
    configs = []
    primary_key = ''
    for candidate in ordered_models(state):
        for key in candidate.provider.keys.all():
            if not key.enabled:
                continue
            if candidate.pk == model.pk and not primary_key:
                primary_key = key.secret
            configs.append({'config': (candidate.provider.name, key.secret, candidate.provider.endpoint, candidate.identifier),
                            'protocol': candidate.provider.protocol})
    return {'primary': (provider.name, primary_key, provider.endpoint, model.identifier), 'configs': configs}


def managed_connection():
    cfg = configuration()
    return cfg['MANAGED_CONNECTION'] if 'MANAGED_CONNECTION' in cfg else active_connection()


def object_by_id(model, value):
    value = str(value or '')
    if not value.isdecimal() or len(value) > 18:
        raise Http404('Elemento no válido.')
    return get_object_or_404(model, pk=value)


def required_by_active(state, kind, obj):
    if not state.active_model_id or obj is None:
        return False
    active = state.active_model
    if kind == 'provider':
        return active.provider_id == obj.pk
    if kind == 'model':
        return active.pk == obj.pk
    return (active.provider_id == obj.provider_id
            and ProviderKey.objects.filter(pk=obj.pk, enabled=True).exists()
            and not obj.provider.keys.filter(enabled=True).exclude(pk=obj.pk).exists())


def catalog_context(request):
    from .system_views import audit
    state = initialize_catalog()
    types = {'provider': (AIProvider, ProviderForm, 'proveedor'), 'model': (ProviderModel, ModelForm, 'modelo'),
             'key': (ProviderKey, KeyForm, 'clave')}
    action = request.POST.get('action', '') if request.method == 'POST' else ''
    if action == 'catalog_reorder':
        values = request.POST.getlist('model_ids')
        if not values or len(values) > 1000 or any(not value.isdecimal() or len(value) > 18 for value in values):
            return {}, JsonResponse({'error': 'Orden no válido.'}, status=400)
        ids = [int(value) for value in values]
        with transaction.atomic():
            state = ProviderSelection.objects.select_for_update().get(pk=1)
            current_ids = [model.pk for model in ordered_models(state)]
            if len(set(ids)) != len(ids) or set(ids) != set(current_ids):
                return {}, JsonResponse({'error': 'La lista cambió. Recargue antes de ordenar.'}, status=409)
            for priority, model_id in enumerate(ids, 1):
                ProviderModel.objects.filter(pk=model_id).update(priority=priority, fallback_enabled=True)
            state.active_model_id = ids[0]
            state.save(update_fields=['active_model'])
            audit(request, 'catalog_model_save', 'Orden de modelos actualizado',
                  resource='Orden de modelos', fields=['active_model', 'priority'])
        return {}, JsonResponse({'ok': True})
    editor = request.GET.get('editor', '') if not action else action.removeprefix('catalog_').removesuffix('_save')
    form, editing, provider, kind = None, None, None, None
    if editor == 'backup':
        kind = 'backup'
        form = BackupForm(request.POST if action else None, active_id=state.active_model_id)
        if action and form.is_valid():
            with transaction.atomic():
                state = ProviderSelection.objects.select_for_update().get(pk=1)
                model = form.cleaned_data['model']
                if model.pk == state.active_model_id:
                    form.add_error('model', 'Este modelo ya es el principal.')
                else:
                    model.fallback_enabled = True
                    model.priority = form.cleaned_data['priority']
                    model.save(update_fields=['fallback_enabled', 'priority'])
                    audit(request, 'catalog_model_save', model.name, resource=f'Modelo #{model.pk}',
                          fields=['fallback_enabled', 'priority'])
                    messages.success(request, 'Respaldo agregado. Se usará automáticamente según su prioridad.')
                    return {}, redirect('/system/?view=models&selected_provider=' + str(model.provider_id))
    elif editor in types:
        kind = editor
        cls, form_type, title = types[kind]
        object_id = request.POST.get('object_id') if action else request.GET.get('object_id')
        editing = object_by_id(cls, object_id) if object_id else None
        if kind != 'provider':
            provider = object_by_id(AIProvider, request.POST.get('provider_id') if action else request.GET.get('provider_id'))
            if editing and editing.provider_id != provider.pk:
                raise Http404('El elemento no pertenece al proveedor.')
        instance = editing or cls()
        if provider:
            instance.provider = provider
        if kind == 'provider' and not editing:
            form_type = NewProviderForm
        form = form_type(request.POST if action else None, instance=instance)
        if action and form.is_valid():
            with transaction.atomic():
                state = ProviderSelection.objects.select_for_update().get(pk=1)
                active = state.active_model
                disabling = not form.cleaned_data['enabled']
                protected = required_by_active(state, kind, editing)
                if disabling and protected:
                    form.add_error('enabled', 'Seleccione otra conexión o habilite otra clave antes de desactivar este elemento.')
                else:
                    try:
                        with transaction.atomic():
                            saved = form.save()
                            if initial_secret := form.cleaned_data.get('initial_secret'):
                                saved.keys.create(name='Principal', secret=initial_secret)
                            audit(request, 'catalog_' + kind + '_save', saved.name,
                                  resource=f'{types[kind][2]} #{saved.pk}', fields=list(form.changed_data))
                    except IntegrityError:
                        form.add_error(None, 'Ya existe un elemento con ese nombre o identificador en este proveedor.')
                    else:
                        if kind == 'provider' and not editing:
                            messages.success(request, 'Proveedor agregado con su clave principal.' if initial_secret
                                             else 'Proveedor agregado. Puede agregar su clave en «Claves API».')
                        else:
                            messages.success(request, 'Cambios guardados. Aplican a las consultas nuevas.')
                        return {}, redirect('/system/?view=models&selected_provider=' + str(saved.pk if kind == 'provider' else provider.pk))
    elif action in ('catalog_activate', 'catalog_delete'):
        with transaction.atomic():
            state = ProviderSelection.objects.select_for_update().get(pk=1)
            if action == 'catalog_activate':
                model = object_by_id(ProviderModel, request.POST.get('object_id'))
                return_provider_id = model.provider_id
                if not model.enabled or not model.provider.enabled or not model.provider.keys.filter(enabled=True).exists():
                    messages.error(request, 'Habilite el proveedor, el modelo y al menos una clave antes de usar esta conexión.')
                else:
                    state.active_model = model
                    state.save(update_fields=['active_model'])
                    audit(request, action, model.name, resource=f'Modelo #{model.pk}')
                    messages.success(request, 'Modelo principal actualizado. Aplica a las consultas nuevas.')
            else:
                kind = request.POST.get('kind')
                if kind not in types:
                    raise Http404('Tipo de elemento no válido.')
                obj = object_by_id(types[kind][0], request.POST.get('object_id'))
                return_provider_id = obj.pk if kind == 'provider' else obj.provider_id
                active = state.active_model
                protected = required_by_active(state, kind, obj)
                if protected:
                    messages.error(request, 'Este elemento está en uso. Seleccione otro modelo o agregue otra clave antes de eliminarlo.')
                else:
                    try:
                        obj.delete()
                    except ProtectedError:
                        messages.error(request, 'El elemento está en uso.')
                    else:
                        if kind == 'provider':
                            return_provider_id = None
                        audit(request, action, obj.name, resource=f'{types[kind][2]} #{request.POST.get("object_id")}')
                        messages.success(request, 'Elemento eliminado.')
        return {}, redirect('/system/?view=models' + ('&selected_provider=' + str(return_provider_id) if return_provider_id else ''))
    elif action:
        raise Http404('Acción no válida.')
    providers = list(AIProvider.objects.prefetch_related('models', 'keys').all())
    active_provider_id = state.active_model.provider_id if state.active_model_id else None
    providers.sort(key=lambda item: (item.pk != active_provider_id, item.name.casefold()))
    for item in providers:
        item.enabled_key_count = sum(key.enabled for key in item.keys.all())
    selected = provider if provider else editing if kind == 'provider' and editing else None
    if selected is None and request.GET.get('selected_provider'):
        selected = object_by_id(AIProvider, request.GET['selected_provider'])
    return_url = '/system/?view=models' + ('&selected_provider=' + str(selected.pk) if selected else '')
    return {'catalog_providers': providers, 'catalog_selected_provider': selected,
            'catalog_model_chain': ordered_models(state),
            'catalog_visible_providers': [item for item in providers if selected and item.pk == selected.pk],
            'catalog_return_url': return_url, 'catalog_active_provider_id': active_provider_id,
            'catalog_active_id': state.active_model_id,
            'catalog_form': form, 'catalog_kind': kind, 'catalog_editing': editing,
            'catalog_parent': provider, 'catalog_title': 'Agregar respaldo' if kind == 'backup' else
                ('Editar ' if editing else 'Agregar ') + types[kind][2] if form else ''}, None
