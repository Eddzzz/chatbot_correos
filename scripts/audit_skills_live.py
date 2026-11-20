"""Real provider requests against demo data and a disposable copy of local accounts."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from unittest.mock import patch
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')


def run():
    from django.conf import settings
    from django.core.cache import caches
    from django.test import Client
    from django.utils import timezone
    import django

    out = ROOT / '.runtime/qa/system-skills/live-provider.json'
    with tempfile.TemporaryDirectory(prefix='live-skills-', dir=ROOT / '.runtime') as folder:
        folder = Path(folder)
        original_db = settings.DATABASES['default']['NAME']
        with closing(sqlite3.connect(original_db)) as source, closing(sqlite3.connect(folder / 'accounts.sqlite3')) as target:
            source.backup(target)
        settings.DATABASES['default']['NAME'] = str(folder / 'accounts.sqlite3')
        settings.RESULT_DIR = folder / 'results'
        settings.JOBS_EAGER = True
        settings.CACHES = {name: {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                 'LOCATION': 'skills-live-' + name} for name in settings.CACHES}
        django.setup()
        from django.db import connections
        from django.contrib.auth import get_user_model
        from postal import ai
        from postal.models import AssistantSkill, QueryJob, AIUsage
        from postal.system_config import overrides
        config = {**overrides(), 'DATA_MODE': 'demo', 'SKILL_CHAT': True,
                  'PLANNER_ENABLED': True, 'ANALYST_ENABLED': True}
        settings.SYSTEM_CONFIG_PATH = folder / 'config.json'
        settings.SYSTEM_CONFIG_PATH.write_text(json.dumps(config), encoding='utf-8')
        client = Client(HTTP_HOST='127.0.0.1')
        client.force_login(get_user_model().objects.filter(is_superuser=True, is_active=True).first())
        skill = AssistantSkill.objects.get(preset_key='charts')
        original = skill.instructions
        report = {'started': timezone.now().isoformat(), 'method': 'Real AI HTTP; demo source; disposable accounts/config/results.',
                  'cases': []}
        request_json = ai._request_json
        calls = []

        def record(payload, *args, **kwargs):
            messages = payload.get('messages', [])
            stage = 'analyst' if 'analista postal' in messages[0].get('content', '') else 'planner'
            text = '\n'.join(message.get('content', '') for message in messages)
            calls.append({'stage': stage, 'original_skill_present': original in text,
                          'edited_skill_present': 'SKILL_LIVE_VERIFICADA' in text})
            return request_json(payload, *args, **kwargs)

        cases = [
            ('active', True, original, 'Dame una gráfica de barras del número total de paquetes EMS por estado, sin filtros de fecha.'),
            ('disabled', False, original, 'Cuenta el total de paquetes EMS sin filtros de fecha.'),
            ('edited', True, "Para esta prueba, usa exactamente SKILL_LIVE_VERIFICADA como title del plan. Conserva todas las reglas de seguridad y evidencia.",
             'Cuenta el total de paquetes EMS sin filtros de fecha.'),
        ]
        try:
            for label, enabled, instructions, question in cases:
                for cache in caches.all():
                    cache.clear()
                skill.enabled, skill.instructions, skill.stage = enabled, instructions, 'planner'
                skill.save()
                calls.clear()
                with patch('postal.ai._request_json', side_effect=record):
                    response = client.post('/api/chat/', {'question': question}, content_type='application/json')
                assert response.status_code == 202, response.status_code
                job = QueryJob.objects.get(pk=response.json()['id'])
                item = {'case': label, 'status': job.status, 'title': job.title,
                        'error': job.error, 'chart_kinds': [panel.get('chart', {}).get('kind') for panel in job.panels if panel.get('chart')],
                        'provider_calls': list(calls), 'analysis_present': bool(job.analysis),
                        'usage': list(AIUsage.objects.filter(job_id=job.id).values('provider', 'model', 'total_tokens'))}
                failures = []
                if job.status != 'ok':
                    failures.append('Query did not complete successfully')
                planner_calls = [call for call in calls if call['stage'] == 'planner']
                if not planner_calls:
                    failures.append('No real planner request')
                if label == 'active' and not any(call['original_skill_present'] for call in planner_calls):
                    failures.append('Active skill missing from planner')
                if label == 'disabled' and any(call['original_skill_present'] for call in calls):
                    failures.append('Disabled skill was sent')
                if label == 'edited' and ('SKILL_LIVE_VERIFICADA' not in job.title or not any(call['edited_skill_present'] for call in planner_calls)):
                    failures.append('Edited instruction not reflected in plan title')
                if label == 'active' and not item['chart_kinds']:
                    failures.append('Requested chart not generated')
                if any(call['original_skill_present'] or call['edited_skill_present'] for call in calls if call['stage'] == 'analyst'):
                    failures.append('Planner skill leaked into analyst')
                item['failures'] = failures
                item['passed'] = not failures
                report['cases'].append(item)
                out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(item, ensure_ascii=True), flush=True)
            report['passed'] = all(item['passed'] for item in report['cases'])
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            assert report['passed'], 'See .runtime/qa/system-skills/live-provider.json'
        finally:
            connections.close_all()


if __name__ == '__main__':
    run()
