"""Private runtime overrides; the environment remains the initial configuration."""
import json
import os
import tempfile
import threading
from contextvars import ContextVar
from pathlib import Path

from django.conf import settings

NARRATIVE_STYLE = (
    'Explica los resultados en párrafos breves y relacionados. Empieza con la respuesta a la pregunta '
    'y destaca qué muestran los datos. Para un desglose, prefiere una comparación o un resumen '
    'de la distribución a repetir los valores fila por fila. Reserva las listas para cuando el usuario '
    'las pida o cuando faciliten seguir pasos, distinguir opciones o consultar un ranking. '
    'En informes con tablas o gráficos, explica los hallazgos principales y deja el detalle en sus paneles.'
)

DEFAULTS = {
    'TABLE_PERMISSIONS': {},
    'COLUMN_PERMISSIONS': {},
    'AI_MAX_TOKENS': 3000, 'AI_TIMEOUT': 120, 'AI_CONNECT_TIMEOUT': 15,
    'DB_CONNECT_TIMEOUT': 10, 'DB_STATEMENT_TIMEOUT': 15000,
    'PLANNER_ENABLED': True, 'ANALYST_ENABLED': True,
    'PLANNER_INSTRUCTIONS': '', 'ANALYST_INSTRUCTIONS': NARRATIVE_STYLE,
    'SKILL_CHAT': True, 'SKILL_TRACKING': True, 'SKILL_DASHBOARD': True,
    'SKILL_CATALOG': True, 'SKILL_PDF': True,
    'SKILL_CSV': True, 'SKILL_XLSX': True, 'SKILL_BULK_TRACKING': True,
}
SECRET_FIELDS = {'GROQ_API_KEY', 'GROQ_BACKUP_API_KEY', 'OPENROUTER_API_KEY',
                 'NVIDIA_API_KEY', 'CLOUDFLARE_API_TOKEN', 'BUSINESS_DATABASE_URL'}
SETTING_FIELDS = {'AI_PROVIDER', 'GROQ_MODEL', 'OPENROUTER_MODEL', 'NVIDIA_MODEL',
                  'CLOUDFLARE_MODEL', 'CLOUDFLARE_ACCOUNT_ID', 'DATA_MODE'} | SECRET_FIELDS
ALLOWED_FIELDS = SETTING_FIELDS | DEFAULTS.keys()
_lock = threading.Lock()
_snapshot = ContextVar('postal_system_config', default=None)
usage_context = ContextVar('postal_usage_context', default=None)


def config_path():
    return Path(getattr(settings, 'SYSTEM_CONFIG_PATH', settings.RUNTIME_DIR / 'system-settings.json'))


def overrides():
    try:
        value = json.loads(config_path().read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    if not isinstance(value, dict) or set(value) - ALLOWED_FIELDS:
        raise ValueError('Configuración del sistema inválida.')
    return value


def configuration():
    snapshot = _snapshot.get()
    if snapshot is not None:
        return snapshot
    return {**{name: getattr(settings, name, DEFAULTS.get(name, '')) for name in ALLOWED_FIELDS},
            **overrides()}


def value(name):
    return configuration()[name]


def save_config(changes):
    if set(changes) - ALLOWED_FIELDS:
        raise ValueError('Campo no permitido.')
    with _lock:
        current = overrides()
        updated = {**current, **changes}
        for field in ('TABLE_PERMISSIONS', 'COLUMN_PERMISSIONS'):
            if field in changes:
                updated[field] = {**current.get(field, {}), **changes[field]}
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='system-', suffix='.tmp', dir=path.parent)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                json.dump(updated, output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)


def record_usage(provider, model, stage, counts):
    context = usage_context.get()
    if not context:
        return
    from .models import AIUsage
    AIUsage.objects.create(user_id=context[0], job_id=context[1], provider=provider,
                           model=model, stage=stage, **counts)
