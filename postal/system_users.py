"""Superuser-only account forms and actions, called after the administrative permission check."""
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.forms import SetPasswordForm
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect


class AccountForm(forms.ModelForm):
    role = forms.ChoiceField(label='Rol', choices=[('user', 'Usuario'), ('admin', 'Administrador del sistema')])
    password1 = forms.CharField(label='Contraseña', required=False, strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))
    password2 = forms.CharField(label='Confirmar contraseña', required=False, strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))

    class Meta:
        model = get_user_model()
        fields = ['username', 'first_name', 'last_name', 'email', 'is_active']
        labels = {'username': 'Nombre de usuario', 'first_name': 'Nombres', 'last_name': 'Apellidos',
                  'email': 'Correo electrónico', 'is_active': 'Cuenta activa'}
        help_texts = {'username': 'Letras, números y @ . + - _; hasta 150 caracteres.',
                      'is_active': 'Desactivar bloquea el acceso y conserva las conversaciones.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(['username', 'role', 'first_name', 'last_name', 'email', 'password1', 'password2', 'is_active'])
        self.fields['role'].initial = 'admin' if self.instance.is_superuser else 'user'
        if not self.instance.pk:
            self.fields['password1'].required = True
            self.fields['password2'].required = True
            self.fields['is_active'].initial = True
        else:
            self.fields['password1'].help_text = 'Deje ambas contraseñas vacías para conservar la actual.'

    def clean(self):
        data = super().clean()
        if data.get('password1', '') != data.get('password2', ''):
            self.add_error('password2', 'Las contraseñas no coinciden.')
        return data

    def _post_clean(self):
        super()._post_clean()
        password = self.cleaned_data.get('password1')
        if password:
            try:
                validate_password(password, self.instance)
            except ValidationError as exc:
                self.add_error('password1', exc)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_superuser = self.cleaned_data['role'] == 'admin'
        user.is_staff = user.is_superuser
        if self.cleaned_data.get('password1'):
            user.set_password(self.cleaned_data['password1'])
        if commit:
            user.save()
        return user


def cancel_user_jobs(user):
    from .jobs import cancel
    from .models import QueryJob
    for job_id in QueryJob.objects.filter(user=user, status__in=['queued', 'running']).values_list('id', flat=True):
        cancel(job_id)


def account_context(request):
    """Return (context, optional redirect) for the protected administrative view."""
    from .system_views import audit
    User = get_user_model()
    editing = None
    requested = request.POST.get('user_id', '') if request.method == 'POST' else request.GET.get('reset_user') or request.GET.get('edit_user', '')
    if requested:
        if not requested.isdecimal() or len(requested) > 18:
            from django.http import Http404
            raise Http404('Cuenta no válida.')
        editing = get_object_or_404(User, pk=requested)
    action = request.POST.get('action') if request.method == 'POST' else None
    resetting = action == 'user_password_reset' or (request.method == 'GET' and 'reset_user' in request.GET)
    if resetting and editing is None:
        from django.http import HttpResponseBadRequest
        return {}, HttpResponseBadRequest('Seleccione una cuenta para restablecer su contraseña.')
    password_form = SetPasswordForm(editing, request.POST if action == 'user_password_reset' else None) if resetting else None
    if action == 'user_password_reset' and password_form.is_valid():
        with transaction.atomic():
            saved = password_form.save()
            audit(request, 'user_password_reset', f'Cuenta {saved.pk} · {saved.username}', resource=f'Usuario #{saved.pk}')
        if saved.pk == request.user.pk:
            update_session_auth_hash(request, saved)
        messages.success(request, 'Contraseña restablecida. La cuenta ya puede usar la nueva contraseña.')
        return {}, redirect('/system/?view=users')
    form = AccountForm(request.POST if action == 'user_save' else None, instance=editing)
    if action == 'user_toggle':
        desired = request.POST.get('enabled')
        if desired not in ('0', '1'):
            from django.http import HttpResponseBadRequest
            return {}, HttpResponseBadRequest('Indique si la cuenta debe quedar activa o inactiva.')
        if editing is None or editing.pk == request.user.pk:
            messages.error(request, 'No puede desactivar su propia cuenta desde este panel.')
        else:
            with transaction.atomic():
                editing = User.objects.select_for_update().get(pk=editing.pk)
                editing.is_active = desired == '1'
                editing.save(update_fields=['is_active'])
                audit(request, 'user_enable' if editing.is_active else 'user_disable', editing.username,
                      resource=f'Usuario #{editing.pk}', fields=['is_active'])
            if not editing.is_active:
                cancel_user_jobs(editing)
            messages.success(request, 'Cuenta activada.' if editing.is_active else 'Cuenta desactivada. Sus conversaciones se conservan.')
        return {}, redirect('/system/?view=users')
    if action == 'user_save' and form.is_valid():
        if editing and editing.pk == request.user.pk and (form.cleaned_data['role'] != 'admin' or not form.cleaned_data['is_active']):
            form.add_error(None, 'Conserve su rol de administrador y su cuenta activa para no perder el acceso.')
        else:
            try:
                with transaction.atomic():
                    saved = form.save()
                    audit(request, 'user_update' if editing else 'user_create',
                          f'{saved.username} · ' + ('Administrador' if saved.is_superuser else 'Usuario') +
                          (' · Activo' if saved.is_active else ' · Inactivo'),
                          resource=f'Usuario #{saved.pk}', fields=list(form.changed_data))
            except IntegrityError:
                form.add_error('username', 'Ese nombre de usuario ya está en uso.')
            else:
                if saved.pk == request.user.pk and form.cleaned_data.get('password1'):
                    update_session_auth_hash(request, saved)
                if not saved.is_active:
                    cancel_user_jobs(saved)
                messages.success(request, 'Cuenta actualizada.' if editing else 'Usuario creado. Ya puede iniciar sesión.')
                return {}, redirect('/system/?view=users')
    users = User.objects.all().annotate(chat_count=Count('conversation', distinct=True)).order_by('username')
    search = request.GET.get('q', '').strip()[:150]
    if search:
        users = users.filter(Q(username__icontains=search) | Q(first_name__icontains=search) |
                             Q(last_name__icontains=search) | Q(email__icontains=search))
    status = request.GET.get('status', 'all')
    if status == 'active':
        users = users.filter(is_active=True)
    elif status == 'inactive':
        users = users.filter(is_active=False)
    elif status == 'admins':
        users = users.filter(is_superuser=True)
    else:
        status = 'all'
    return {'account_form': form, 'editing_account': editing if not resetting else None, 'account_status': status,
            'password_form': password_form, 'password_account': editing if resetting else None,
            'account_dialog_open': not resetting and bool(editing or form.is_bound or request.GET.get('new') == '1'),
            'accounts': Paginator(users, 20).get_page(request.GET.get('page'))}, None


def account_counts():
    return get_user_model().objects.aggregate(total=Count('id'), active=Count('id', filter=Q(is_active=True)),
        inactive=Count('id', filter=Q(is_active=False)), admins=Count('id', filter=Q(is_active=True, is_superuser=True)))
