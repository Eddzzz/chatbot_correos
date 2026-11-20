"""Provider 413 is either a known Groq quota or an oversized AI request."""
import json
from unittest.mock import patch

import httpx
from django.test import TestCase, override_settings

from postal.ai import PlanningError, _call_json


@override_settings(AI_PROVIDER='groq', GROQ_API_KEY='test-groq', GROQ_BACKUP_API_KEY='',
                   OPENROUTER_API_KEY='test-router')
class ProviderSizeErrorTests(TestCase):
    def call_provider(self, responses, payload=None):
        self.requests = []
        responses = iter(responses)
        real_client = httpx.Client

        def respond(request):
            self.requests.append(request)
            return next(responses)

        with patch('postal.ai.httpx.Client', side_effect=lambda **kw: real_client(
                transport=httpx.MockTransport(respond), **kw)), patch('postal.ai.time.sleep') as sleep:
            try:
                return _call_json(payload or {'messages': []})
            finally:
                sleep.assert_not_called()

    def test_groq_token_quota_413_switches_without_retrying_same_request(self):
        payload = {'messages': [{'role': 'user', 'content': 'JSON postal'}], 'max_tokens': 3000,
                   'response_format': {'type': 'json_object'}}
        result = self.call_provider([
            httpx.Response(413, headers={'Retry-After': '60'}, json={'error': {
                'code': 'rate_limit_exceeded', 'message': 'PRIVATE quota details'}}),
            httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {
                'content': '{"ok":true}'}}]}),
        ], payload)
        self.assertEqual(result, {'ok': True})
        self.assertEqual([request.url.host for request in self.requests], ['api.groq.com', 'openrouter.ai'])
        self.assertEqual(json.loads(self.requests[1].content)['messages'], payload['messages'])
        self.assertNotIn('model', payload)

    @override_settings(OPENROUTER_API_KEY='')
    def test_groq_token_quota_without_backup_reports_quota_and_hides_body(self):
        with self.assertRaises(PlanningError) as caught:
            self.call_provider([httpx.Response(413, json={'error': {
                'code': 'rate_limit_exceeded', 'message': 'PRIVATE quota details'}})])
        self.assertEqual(caught.exception.code, 'provider_busy')
        self.assertIn('Groq', caught.exception.message)
        self.assertNotIn('PRIVATE', caught.exception.message)
        self.assertEqual(len(self.requests), 1)

    def test_generic_413_is_actionable_size_error_without_retry_or_fallback(self):
        for response in [httpx.Response(413), httpx.Response(413, text='<html>PRIVATE</html>'),
                         httpx.Response(413, json={'error': {'code': 'request_too_large', 'message': 'PRIVATE'}}),
                         httpx.Response(413, json={'error': {'message': 'rate_limit_exceeded PRIVATE'}}),
                         httpx.Response(413, json={'error': 'rate_limit_exceeded'})]:
            with self.subTest(body=response.content), self.assertRaises(PlanningError) as caught:
                self.call_provider([response])
            self.assertEqual(caught.exception.code, 'provider_request_too_large')
            self.assertIn('Groq', caught.exception.message)
            self.assertIn('redu', caught.exception.message.lower())
            self.assertNotIn('PRIVATE', caught.exception.message)
            self.assertEqual(len(self.requests), 1)

    def test_oversized_error_body_does_not_enable_quota_fallback(self):
        with self.assertRaises(PlanningError) as caught:
            self.call_provider([httpx.Response(413, json={'error': {
                'code': 'rate_limit_exceeded', 'message': 'x' * 10001}})])
        self.assertEqual(caught.exception.code, 'provider_request_too_large')
        self.assertEqual(len(self.requests), 1)

    @override_settings(AI_PROVIDER='nvidia', NVIDIA_API_KEY='test-nvidia')
    def test_groq_quota_code_on_another_provider_is_still_size_error(self):
        with self.assertRaises(PlanningError) as caught:
            self.call_provider([httpx.Response(413, json={'error': {'code': 'rate_limit_exceeded'}})])
        self.assertEqual(caught.exception.code, 'provider_request_too_large')
        self.assertIn('NVIDIA', caught.exception.message)
        self.assertEqual(len(self.requests), 1)

    def test_openrouter_size_error_stops_chain(self):
        with self.assertRaises(PlanningError) as caught:
            self.call_provider([httpx.Response(429, headers={'Retry-After': '60'}),
                                httpx.Response(413, json={'error': {'code': 'rate_limit_exceeded'}})])
        self.assertEqual(caught.exception.code, 'provider_request_too_large')
        self.assertIn('OpenRouter', caught.exception.message)
        self.assertEqual([request.url.host for request in self.requests], ['api.groq.com', 'openrouter.ai'])
