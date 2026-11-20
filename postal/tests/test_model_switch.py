"""Additional regression coverage for fallback lifetime and total retry bounds."""
import json
from unittest.mock import patch

import httpx
from django.test import TestCase, override_settings

from postal.ai import PlanningError, _call_json


@override_settings(AI_PROVIDER='groq', GROQ_API_KEY='test-groq', GROQ_BACKUP_API_KEY='',
                   OPENROUTER_API_KEY='test-router')
class ModelSwitchTests(TestCase):
    def test_new_generation_returns_to_primary_with_same_context(self):
        requests = []
        real_client = httpx.Client
        payload = {'messages': [{'role': 'user', 'content': 'JSON: cuenta EMS; contexto ficticio'}],
                   'response_format': {'type': 'json_object'}, 'max_tokens': 3000}

        def respond(request):
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(429, headers={'Retry-After': '60'})
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {
                'content': '{"sql":"SELECT COUNT(*) FROM assistant.paquetes_ems"}'}}]})

        with patch('postal.ai.httpx.Client', side_effect=lambda **kw: real_client(
                transport=httpx.MockTransport(respond), **kw)):
            first = _call_json(payload)
            second = _call_json(payload)
        self.assertEqual(first, second)
        self.assertEqual([request.url.host for request in requests],
                         ['api.groq.com', 'openrouter.ai', 'api.groq.com'])
        for request in requests:
            sent = json.loads(request.content)
            self.assertEqual(sent['messages'], payload['messages'])
            self.assertEqual(sent['response_format'], payload['response_format'])
        self.assertNotIn('provider', json.loads(requests[-1].content))
        self.assertNotIn('model', payload)

    def test_exhausted_chain_stops_after_four_http_requests(self):
        requests = []
        real_client = httpx.Client

        def respond(request):
            requests.append(request)
            return httpx.Response(429, headers={'Retry-After': '1'})

        with patch('postal.ai.httpx.Client', side_effect=lambda **kw: real_client(
                transport=httpx.MockTransport(respond), **kw)), patch('postal.ai.time.sleep'):
            with self.assertRaises(PlanningError) as caught:
                _call_json({'messages': []})
        self.assertEqual([request.url.host for request in requests],
                         ['api.groq.com'] * 2 + ['openrouter.ai'] * 2)
        self.assertEqual(caught.exception.code, 'provider_busy')
        self.assertIn('OpenRouter', caught.exception.message)
