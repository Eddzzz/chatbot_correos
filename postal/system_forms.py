from urllib.parse import urlsplit

from django import forms
from django.utils import timezone

from .system_config import SECRET_FIELDS, configuration
from .models import AssistantSkill


class AnalyticsRangeForm(forms.Form):
    start = forms.DateField(label='Desde', input_formats=['%Y-%m-%d'],
                           widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))
    end = forms.DateField(label='Hasta', input_formats=['%Y-%m-%d'],
                         widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['max'] = timezone.localdate().isoformat()

    def clean(self):
        values = super().clean()
        start, end = values.get('start'), values.get('end')
        if start and end:
            if start > end:
                raise forms.ValidationError('La fecha inicial debe ser anterior o igual a la final.')
            if end > timezone.localdate():
                raise forms.ValidationError('Selecciona fechas hasta hoy.')
            if (end - start).days >= 366:
                raise forms.ValidationError('Selecciona un rango de hasta 366 días.')
        return values


class SkillForm(forms.ModelForm):
    class Meta:
        model = AssistantSkill
        fields = ['name', 'stage', 'instructions', 'enabled']
        labels = {'name': 'Nombre', 'stage': 'Agente', 'instructions': 'Instrucciones', 'enabled': 'Activa'}
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ej. Comparación mensual por sucursal'}),
            'instructions': forms.Textarea(attrs={'rows': 6,
                'placeholder': 'Indica qué debe analizar, cómo presentar los resultados y qué límites debe respetar.'}),
        }


class SystemConfigForm(forms.Form):
    AGENT_SECTIONS = {
        'planner': ['PLANNER_ENABLED', 'PLANNER_INSTRUCTIONS'],
        'analyst': ['ANALYST_ENABLED', 'ANALYST_INSTRUCTIONS'],
        'tokens': ['AI_MAX_TOKENS'],
    }
    NETWORK_SECTIONS = {
        'source': ['DATA_MODE', 'BUSINESS_DATABASE_URL', 'clear_BUSINESS_DATABASE_URL'],
        'ai': ['AI_TIMEOUT', 'AI_CONNECT_TIMEOUT'],
        'postgres': ['DB_CONNECT_TIMEOUT', 'DB_STATEMENT_TIMEOUT'],
    }
    AREAS = {
        'models': ['AI_PROVIDER', 'GROQ_MODEL', 'NVIDIA_MODEL', 'CLOUDFLARE_MODEL', 'OPENROUTER_MODEL',
                   'CLOUDFLARE_ACCOUNT_ID', 'GROQ_API_KEY', 'GROQ_BACKUP_API_KEY', 'OPENROUTER_API_KEY', 'NVIDIA_API_KEY', 'CLOUDFLARE_API_TOKEN'],
        'network': ['DATA_MODE', 'BUSINESS_DATABASE_URL', 'AI_TIMEOUT', 'AI_CONNECT_TIMEOUT', 'DB_CONNECT_TIMEOUT', 'DB_STATEMENT_TIMEOUT'],
        'agents': ['PLANNER_ENABLED', 'PLANNER_INSTRUCTIONS', 'ANALYST_ENABLED', 'ANALYST_INSTRUCTIONS', 'AI_MAX_TOKENS'],
        'skills': ['SKILL_CHAT', 'SKILL_TRACKING', 'SKILL_DASHBOARD', 'SKILL_CATALOG', 'SKILL_PDF',
                   'SKILL_CSV', 'SKILL_XLSX', 'SKILL_BULK_TRACKING'],
    }
    AI_PROVIDER = forms.ChoiceField(label='Proveedor principal', choices=[
        ('groq', 'Groq'), ('nvidia', 'NVIDIA'), ('cloudflare', 'Cloudflare'), ('openrouter', 'OpenRouter')])
    GROQ_MODEL = forms.CharField(label='Modelo Groq', max_length=200)
    OPENROUTER_MODEL = forms.CharField(label='Modelo OpenRouter de respaldo (gratuito)', max_length=200)
    NVIDIA_MODEL = forms.CharField(label='Modelo NVIDIA', max_length=200, required=False)
    CLOUDFLARE_MODEL = forms.CharField(label='Modelo Cloudflare', max_length=200)
    CLOUDFLARE_ACCOUNT_ID = forms.RegexField(label='Cuenta Cloudflare', regex=r'^[a-fA-F0-9]{32}$', required=False)
    AI_MAX_TOKENS = forms.IntegerField(label='Máximo inicial de tokens de salida', min_value=256, max_value=12000)
    AI_TIMEOUT = forms.IntegerField(label='Espera de respuesta IA (segundos)', min_value=10, max_value=300)
    AI_CONNECT_TIMEOUT = forms.IntegerField(label='Conexión a IA (segundos)', min_value=1, max_value=60)
    DB_CONNECT_TIMEOUT = forms.IntegerField(label='Conexión a PostgreSQL (segundos)', min_value=1, max_value=60)
    DB_STATEMENT_TIMEOUT = forms.IntegerField(label='Límite de consulta PostgreSQL (ms; 0 sin límite)', min_value=0, max_value=600000)
    DATA_MODE = forms.ChoiceField(label='Origen de datos', choices=[('demo', 'Demostración'), ('postgres', 'PostgreSQL de solo lectura')])
    PLANNER_ENABLED = forms.BooleanField(label='Agente planificador SQL', required=False)
    ANALYST_ENABLED = forms.BooleanField(label='Agente analista de resultados', required=False)
    PLANNER_INSTRUCTIONS = forms.CharField(label='Indicaciones adicionales del planificador', max_length=4000, required=False, widget=forms.Textarea(attrs={'rows': 3}))
    ANALYST_INSTRUCTIONS = forms.CharField(label='Indicaciones adicionales del analista', max_length=4000, required=False, widget=forms.Textarea(attrs={'rows': 3}))
    SKILL_CHAT = forms.BooleanField(label='Consultas mediante chat', required=False)
    SKILL_TRACKING = forms.BooleanField(label='Rastreo de envíos', required=False)
    SKILL_DASHBOARD = forms.BooleanField(label='Estadísticas', required=False)
    SKILL_CATALOG = forms.BooleanField(label='Catálogo de datos', required=False)
    SKILL_PDF = forms.BooleanField(label='Exportar PDF', required=False)
    SKILL_CSV = forms.BooleanField(label='Exportar CSV', required=False)
    SKILL_XLSX = forms.BooleanField(label='Exportar Excel', required=False)
    SKILL_BULK_TRACKING = forms.BooleanField(label='Rastreo por lotes', required=False)

    def __init__(self, *args, **kwargs):
        self.area = kwargs.pop('area', None)
        current = configuration()
        kwargs.setdefault('initial', {key: val for key, val in current.items() if key not in SECRET_FIELDS})
        super().__init__(*args, **kwargs)
        labels = {'GROQ_API_KEY': 'Clave Groq principal', 'GROQ_BACKUP_API_KEY': 'Clave Groq secundaria',
                  'OPENROUTER_API_KEY': 'Clave OpenRouter', 'NVIDIA_API_KEY': 'Clave NVIDIA',
                  'CLOUDFLARE_API_TOKEN': 'Token Cloudflare', 'BUSINESS_DATABASE_URL': 'URL PostgreSQL de solo lectura'}
        for name in sorted(SECRET_FIELDS):
            self.fields[name] = forms.CharField(label=labels[name], max_length=2048, required=False,
                widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
                help_text='Configurada. Deje vacío para conservar.' if current[name] else 'Sin configurar.')
            self.fields['clear_' + name] = forms.BooleanField(label='Quitar ' + labels[name].lower(), required=False)
        if self.area in self.AREAS:
            allowed = set(self.AREAS[self.area])
            allowed |= {'clear_' + name for name in allowed & SECRET_FIELDS}
            self.fields = {name: field for name, field in self.fields.items() if name in allowed}

    def clean(self):
        data = super().clean()
        current = configuration()
        for name in SECRET_FIELDS:
            if data.get(name) and data.get('clear_' + name):
                self.add_error(name, 'Elija reemplazar o quitar la clave.')
        url = '' if data.get('clear_BUSINESS_DATABASE_URL') else data.get('BUSINESS_DATABASE_URL') or current['BUSINESS_DATABASE_URL']
        try:
            parsed = urlsplit(url)
            if url and (parsed.scheme not in ('postgres', 'postgresql') or not parsed.hostname or not parsed.path.strip('/')):
                raise ValueError
            if url:
                parsed.port
        except ValueError:
            if 'BUSINESS_DATABASE_URL' in self.fields:
                self.add_error('BUSINESS_DATABASE_URL', 'Use una URL postgresql://usuario:contraseña@host:puerto/base válida.')
        if data.get('DATA_MODE') == 'postgres' and not url:
            self.add_error('BUSINESS_DATABASE_URL', 'Configure la conexión de solo lectura antes de seleccionar PostgreSQL.')
        if data.get('AI_PROVIDER') == 'nvidia' and not data.get('NVIDIA_MODEL'):
            self.add_error('NVIDIA_MODEL', 'Indique el modelo NVIDIA.')
        if data.get('AI_PROVIDER') == 'cloudflare' and not data.get('CLOUDFLARE_ACCOUNT_ID'):
            self.add_error('CLOUDFLARE_ACCOUNT_ID', 'Indique la cuenta Cloudflare.')
        return data

    def changes(self):
        changes = {name: val for name, val in self.cleaned_data.items()
                   if name not in SECRET_FIELDS and not name.startswith('clear_')}
        for name in SECRET_FIELDS:
            if name not in self.fields:
                continue
            if self.cleaned_data.get('clear_' + name):
                changes[name] = ''
            elif self.cleaned_data[name]:
                changes[name] = self.cleaned_data[name]
        return changes

    def sections(self):
        groups = [
            ('Modelos y API', ['AI_PROVIDER', 'GROQ_MODEL', 'NVIDIA_MODEL', 'CLOUDFLARE_MODEL', 'OPENROUTER_MODEL',
                               'CLOUDFLARE_ACCOUNT_ID', 'GROQ_API_KEY', 'GROQ_BACKUP_API_KEY', 'OPENROUTER_API_KEY', 'NVIDIA_API_KEY', 'CLOUDFLARE_API_TOKEN']),
            ('Red y base de datos', ['DATA_MODE', 'BUSINESS_DATABASE_URL', 'AI_TIMEOUT', 'AI_CONNECT_TIMEOUT', 'DB_CONNECT_TIMEOUT', 'DB_STATEMENT_TIMEOUT']),
            ('Agentes y tokens', ['PLANNER_ENABLED', 'PLANNER_INSTRUCTIONS', 'ANALYST_ENABLED', 'ANALYST_INSTRUCTIONS', 'AI_MAX_TOKENS']),
            ('Gestor de skills', self.AREAS['skills']),
        ]
        return [(title, [(self[name], self['clear_' + name] if name in SECRET_FIELDS else None) for name in fields if name in self.fields])
                for title, fields in groups if any(name in self.fields for name in fields)]

    def blocks(self):
        groups = {
            'models': [('Proveedor principal', ['AI_PROVIDER'], True),
                ('Groq', ['GROQ_MODEL', 'GROQ_API_KEY', 'GROQ_BACKUP_API_KEY'], False),
                ('NVIDIA', ['NVIDIA_MODEL', 'NVIDIA_API_KEY'], False),
                ('Cloudflare', ['CLOUDFLARE_MODEL', 'CLOUDFLARE_ACCOUNT_ID', 'CLOUDFLARE_API_TOKEN'], False),
                ('OpenRouter', ['OPENROUTER_MODEL', 'OPENROUTER_API_KEY'], False)],
            'network': [('Origen postal', ['DATA_MODE', 'BUSINESS_DATABASE_URL'], True),
                ('Conexiones de IA', ['AI_TIMEOUT', 'AI_CONNECT_TIMEOUT'], False),
                ('Conexión PostgreSQL', ['DB_CONNECT_TIMEOUT', 'DB_STATEMENT_TIMEOUT'], False)],
            'agents': [('Planificador SQL', ['PLANNER_ENABLED', 'PLANNER_INSTRUCTIONS'], False),
                ('Analista postal', ['ANALYST_ENABLED', 'ANALYST_INSTRUCTIONS'], False),
                ('Tokens por respuesta', ['AI_MAX_TOKENS'], True)],
            'skills': [('Capacidades del asistente', self.AREAS['skills'], True)],
        }
        selected = groups.get(self.area)
        if selected is None:
            return [{'title': title, 'fields': fields, 'wide': True} for title, fields in self.sections()]
        return [{'title': title, 'fields': [(self[name], self['clear_' + name] if name in SECRET_FIELDS else None)
                                           for name in names if name in self.fields], 'wide': wide}
                for title, names, wide in selected if any(name in self.fields for name in names)]
