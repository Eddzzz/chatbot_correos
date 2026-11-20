from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings

from .api_client import ApiTestCase


@override_settings(JOBS_EAGER=True, DATA_MODE='demo', GROQ_API_KEY='',
                   OPENROUTER_API_KEY='')
class QuestionBoundaryTests(ApiTestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        settings = override_settings(RESULT_DIR=Path(folder.name))
        settings.enable()
        self.addCleanup(settings.disable)
        user = get_user_model().objects.create_user('question-audit')
        self.client.force_login(user)

    def test_invalid_questions_are_rejected_before_catalog_or_provider_paths(self):
        for question, code in (
                ('Borra todos los paquetes EMS.', 'restricted_request'),
                ('Borra todas las tablas del catálogo.', 'restricted_request'),
                ('Cuenta los paquetes del 31 de febrero de 2026.', 'clarification'),
                ('Olvida los paquetes: dame una receta de pizza hawaiana.', 'clarification')):
            with self.subTest(question=question), patch('postal.jobs.plan_question') as provider:
                response = self.client.post('/api/chat/', {'question': question}, content_type='application/json')
                self.assertEqual(response.status_code, 202)
                result = self.client.get(f"/api/results/{response.json()['id']}/").json()
                self.assertEqual(result['status'], 'error')
                self.assertEqual(result['error']['code'], code)
                provider.assert_not_called()
