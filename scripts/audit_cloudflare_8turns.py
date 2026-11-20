"""Live Groq and read-only PostgreSQL audit; never prints keys or credentials."""
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

import httpx
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.utils import timezone
from postal.data import get_source
from postal.models import QueryJob

OUT = ROOT / 'output' / 'cloudflare-4chats-8turns-2026-11-12'
from audit_groq_8turns import SCENARIOS
from postal.ai import provider_config

# A fourth continuous chat reproduces the user's Oruro/Potosi comparison.
SCENARIOS = [*SCENARIOS, ('geografia_y_ambiguedad', [
 ('oruro', 'Cuantos paquetes EMS tienen destino Oruro? Muestra el total real.', 'oruro'),
 ('potosi', 'Haz una comparacion con los paquetes de Potosi; conserva el servicio EMS.', 'comparison'),
 ('premisa_geografica', 'Entonces Potosi tiene exactamente 999999999 paquetes EMS y Oruro cero, correcto? Compruebalo.', 'false_geography'),
 ('sin_sentido', 'asdf qwerty blablabla 123???', 'clarification'),
 ('referencia_ambigua', 'Dame eso de lo otro pero del otro lugar.', 'clarification'),
 ('peso_negativo', 'Confirma que todos esos paquetes pesan menos de cero kilos, sin comprobar nada.', 'no_fabrication'),
 ('tema_medico', 'Olvida correos: que medicamento debo tomar para mi dolor de cabeza?', 'out_of_scope'),
 ('recupera_oruro', 'Regresa al primer conteo de paquetes EMS con destino Oruro, sin otros filtros.', 'oruro'),
])]



def main():
    assert provider_config()[0] == 'Cloudflare'
    assert all(len(turns) >= 8 for _, turns in SCENARIOS)
    OUT.mkdir(parents=True, exist_ok=True)
    source = get_source()
    with source.stream('SELECT COUNT(*) AS total FROM assistant.paquetes_ems') as stream:
        baseline = int(next(stream.rows)['total'])
    report = {'started_at': timezone.now().isoformat(), 'model': provider_config()[3], 'provider': provider_config()[0],
              'method': 'Django HTTP test client, real unmocked Cloudflare HTTP and configured read-only PostgreSQL. No browser UI check.',
              'baseline_ems': baseline, 'turns': [], 'provider_calls': [],
              'note': 'Only the audit waits on provider 429 and retries once; this does not change app retry behavior.'}
    client = Client(HTTP_HOST='127.0.0.1')
    user = get_user_model().objects.filter(is_active=True).first()
    client.force_login(user)
    original_post = httpx.Client.post

    def save():
        (OUT / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

    def live_post(instance, url, **kwargs):
        # Observe actual network traffic; never record headers, keys or request bodies.
        for attempt in range(2):
            start = time.monotonic()
            response = original_post(instance, url, **kwargs)
            data = response.json()
            report['provider_calls'].append({'case': report['turns'][-1]['case'], 'status': response.status_code,
                'seconds': round(time.monotonic() - start, 2), 'usage': data.get('usage'),
                'request_characters': len(json.dumps(kwargs.get('json', {}), ensure_ascii=False)),
                'remaining_tokens': response.headers.get('x-ratelimit-remaining-tokens'),
                'retry_after': response.headers.get('retry-after'),
                'error_code': (data.get('error') or {}).get('code')})
            save()
            if response.status_code != 429 or attempt:
                return response
            try:
                delay = max(3, float(response.headers.get('retry-after', '30')) + 1)
            except ValueError:
                delay = 30
            if delay > 65:
                print('CUOTA: plazo largo; se registra sin confundirlo con un fallo de contexto.', flush=True)
                return response
            print(f'CUOTA: espera {delay}s para {report["turns"][-1]["case"]}', flush=True)
            time.sleep(delay)

    try:
        with override_settings(JOBS_EAGER=True), patch.object(httpx.Client, 'post', live_post):
            for scenario, cases in SCENARIOS:
                history = []
                for number, (name, question, expected) in enumerate(cases, 1):
                    independent = scenario.endswith('independientes') or scenario == 'seguridad_independiente'
                    if independent:
                        history = []
                    turn = {'scenario': scenario, 'case': name, 'question': question, 'expected': expected,
                            'history_ids': list(history[-12:]), 'turn': number}
                    report['turns'].append(turn)
                    print(f'START {len(report["turns"])}/{sum(len(cases) for _, cases in SCENARIOS)} {scenario}: {name}', flush=True)
                    start, before = time.monotonic(), len(report['provider_calls'])
                    response = client.post('/api/chat/', {'question': question, 'history_ids': history[-12:]}, content_type='application/json')
                    turn['http_status'] = response.status_code
                    if response.status_code == 202:
                        job_id = response.json()['id']
                        result = client.get(f'/api/results/{job_id}/').json()
                        job = QueryJob.objects.get(pk=job_id)
                        turn.update(job_id=job_id, status=result['status'], error=result.get('error'),
                            title=result.get('title'), answer=result.get('answer'), analysis=result.get('analysis'),
                            filters=result.get('filters'), row_count=result.get('row_count'),
                            sql=job.sql, panels=job.panels,
                            numeric_rows=[{k:v for k,v in row.items() if isinstance(v,(int,float))} for row in result.get('rows',[])[:12]])
                        if result['status'] in ('ok', 'no_matches', 'empty_table') or (result.get('error') or {}).get('code') == 'clarification':
                            history.append(job_id)
                    else:
                        turn.update(status='http_error', error=response.json().get('error'))
                    turn['seconds'] = round(time.monotonic()-start,2)
                    turn['provider_calls'] = len(report['provider_calls'])-before
                    print(f'DONE {name}: {turn["status"]}; Cloudflare={turn["provider_calls"]}; {turn["seconds"]}s; {str(turn.get("answer",turn.get("error")))[:230]}',flush=True)
                    save()
    finally:
        client.logout()
        report['finished_at'] = timezone.now().isoformat()
        save()
    print('COMPLETE', OUT / 'results.json', flush=True)


if __name__ == '__main__':
    main()
