import json
import tempfile
import subprocess
import sys
from datetime import timedelta
from unittest.mock import patch

import httpx
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from postal.ai import PlanningError, _request_json


class TokenAvailabilityTests(SimpleTestCase):
    config = ('Groq', 'qa-key', 'https://api.groq.com/openai/v1/chat/completions', 'qa-model')

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        override = override_settings(CACHES={
            'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
            'provider_quotas': {'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
                                'LOCATION': folder.name},
        })
        override.enable()
        self.addCleanup(override.disable)
        cache.clear()
        self.addCleanup(cache.clear)

    def request(self, response):
        client = httpx.Client
        with patch('postal.ai.httpx.Client', side_effect=lambda **kw: client(
                transport=httpx.MockTransport(lambda request: response), **kw)):
            return _request_json({'messages': []}, self.config)

    def test_success_records_provider_headers_without_exposing_credentials(self):
        from postal.token_availability import token_availability
        self.request(httpx.Response(200, headers={
            'x-ratelimit-remaining-tokens': '1234', 'x-ratelimit-limit-tokens': '6000'},
            json={'choices': [{'message': {'content': '{}'}, 'finish_reason': 'stop'}]}))
        snapshot = token_availability(self.config)
        self.assertEqual(snapshot['remaining'], 1234)
        self.assertEqual(snapshot['limit'], 6000)
        self.assertNotIn('qa-key', json.dumps(snapshot, default=str))
        self.assertIsNone(token_availability(('Groq', 'other-key', self.config[2], 'qa-model')))
        self.assertIsNone(token_availability((*self.config[:3], 'other-model')))
        self.assertFalse(snapshot['stale'])

    def test_last_report_survives_one_minute_and_cache_reconnection(self):
        from django.core.cache import caches
        from postal.token_availability import record_token_availability, token_availability
        observed = timezone.now() - timedelta(minutes=5)
        with patch('postal.token_availability.timezone.now', return_value=observed):
            record_token_availability(self.config, {'x-ratelimit-remaining-tokens': '1234'})
        cache.clear()
        caches.close_all()
        snapshot = token_availability(self.config)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot['remaining'], 1234)
        self.assertEqual(snapshot['observed_at'], observed)
        self.assertTrue(snapshot['stale'])

    def test_worker_report_is_readable_from_another_process(self):
        from django.conf import settings
        from postal.token_availability import record_token_availability
        record_token_availability(self.config, {'x-ratelimit-remaining-tokens': '4321'})
        script = '''
import json, sys
from django.conf import settings
settings.configure(USE_TZ=True, CACHES={'provider_quotas': {
    'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache', 'LOCATION': sys.argv[1]}})
from postal.token_availability import token_availability
print(json.dumps(token_availability(tuple(json.loads(sys.argv[2]))), default=str))
'''
        result = subprocess.run([sys.executable, '-c', script,
            settings.CACHES['provider_quotas']['LOCATION'], json.dumps(self.config)],
            capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)['remaining'], 4321)

    def test_exhausted_quota_is_recorded_even_on_error(self):
        from postal.token_availability import token_availability
        with self.assertRaises(PlanningError):
            self.request(httpx.Response(429, headers={
                'Retry-After': '60', 'x-ratelimit-remaining-tokens': '0'}))
        self.assertEqual(token_availability(self.config)['remaining'], 0)

    def test_missing_invalid_and_unsupported_headers_do_not_invent_a_balance(self):
        from postal.token_availability import record_token_availability, token_availability
        for value in (None, '-1', 'invalid', '1.5', '9' * 100):
            with self.subTest(value=value):
                headers = {} if value is None else {'x-ratelimit-remaining-tokens': value}
                record_token_availability(self.config, headers)
                self.assertIsNone(token_availability(self.config))
        other = ('NVIDIA', *self.config[1:])
        record_token_availability(other, {'x-ratelimit-remaining-tokens': '100'})
        self.assertIsNone(token_availability(other))
