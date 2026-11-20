import csv
import importlib
import io
import json
import sqlite3
import tempfile
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import override_settings

from .api_client import ApiTestCase
from django.utils import timezone
from openpyxl import load_workbook

from postal import jobs
from postal.models import AssistantSkill, QueryJob
from postal.system_config import save_config
from postal.views import session_fingerprint


@override_settings(JOBS_EAGER=True, DATA_MODE='demo', GROQ_API_KEY='', AI_PROVIDER='groq')
class AgentCapabilitiesTests(ApiTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        override = override_settings(RESULT_DIR=Path(folder.name) / 'results',
                                    SYSTEM_CONFIG_PATH=Path(folder.name) / 'settings.json')
        override.enable()
        self.addCleanup(override.disable)
        self.user = get_user_model().objects.create_user('capabilities-user')
        self.client.force_login(self.user)

    def result(self):
        job = QueryJob.objects.create(user=self.user, status='ok', title='Datos verificados',
            session_hash=session_fingerprint(self.client.session.session_key), columns=['codigo', 'cantidad'],
            row_count=125, source_tables=['paquetes_ems'], demo=True)
        with closing(sqlite3.connect(jobs.spool_path(job.id))) as spool:
            spool.execute('CREATE TABLE rows (position INTEGER PRIMARY KEY, value TEXT NOT NULL)')
            spool.executemany('INSERT INTO rows VALUES (?, ?)', [(index, json.dumps({
                'codigo': '=1+1' if index == 0 else '000123', 'cantidad': index})) for index in range(125)])
            spool.commit()
        return job

    def content(self, response):
        return b''.join(response.streaming_content) if response.streaming else response.content

    def test_capabilities_questions_return_text_without_querying_data(self):
        self.client.defaults['HTTP_X_BOLIPOST_USER'] = session_fingerprint(self.client.session.session_key)
        with patch('postal.jobs.get_source') as source, patch('postal.jobs.plan_question') as planner:
            for question in ('Hola, ¿qué puedes hacer?', 'En que me puedes ayudar', '¿Qué puedo consultar?'):
                with self.subTest(question=question):
                    response = self.client.post('/api/chat/', {'question': question}, content_type='application/json')
                    self.assertEqual(response.status_code, 202)
                    result = self.client.get(f"/api/results/{response.json()['id']}/").json()
                    self.assertEqual(result['status'], 'ok')
                    self.assertEqual(result['response_type'], 'help')
                    self.assertEqual(result['rows'], [])
                    self.assertNotIn('source_tables', result)
                    self.assertIn('datos históricos', result['answer'])
                    self.assertIn('rastrear', result['answer'])
                    self.assertIn('¿Cuántos envíos EMS', result['answer'])
            source.assert_not_called()
            planner.assert_not_called()

    def test_capabilities_answer_reflects_disabled_features(self):
        self.client.defaults['HTTP_X_BOLIPOST_USER'] = session_fingerprint(self.client.session.session_key)
        save_config({'SKILL_TRACKING': False, 'SKILL_DASHBOARD': False, 'SKILL_CATALOG': False,
                     'SKILL_PDF': False, 'SKILL_CSV': False, 'SKILL_XLSX': False})
        response = self.client.post('/api/chat/', {'question': '¿Qué puedes hacer?'}, content_type='application/json')
        self.assertEqual(response.status_code, 202)
        result = self.client.get(f"/api/results/{response.json()['id']}/").json()
        self.assertEqual(result['status'], 'ok')
        for label in ('rastrear', 'Estadísticas', 'catálogo', 'PDF', 'CSV', 'Excel'):
            self.assertNotIn(label, result['answer'])

    def test_capabilities_answer_preserves_the_last_report_for_followups(self):
        self.client.defaults['HTTP_X_BOLIPOST_USER'] = session_fingerprint(self.client.session.session_key)

        def ask(question, **context):
            response = self.client.post('/api/chat/', {'question': question, **context}, content_type='application/json')
            self.assertEqual(response.status_code, 202)
            return QueryJob.objects.get(pk=response.json()['id'])

        report = ask('Resume los envíos por servicio postal')
        self.assertEqual(report.status, 'ok', report.error)
        help_reply = ask('¿Qué puedes hacer?', previous_id=str(report.id))
        with patch('postal.jobs.compose_response', return_value={'answer': 'Este es el resumen.', 'citations': []}):
            followup = ask('Explícame eso', history_ids=[str(report.id), str(help_reply.id)])
        self.assertEqual(followup.status, 'ok', followup.error)
        self.assertEqual(followup.title, 'Explicación de ' + report.title)

    def test_csv_exports_all_rows_and_neutralizes_formulas(self):
        job = self.result()
        response = self.client.get(f'/api/results/{job.id}/csv/')
        self.assertEqual(response.status_code, 200)
        rows = list(csv.reader(io.StringIO(self.content(response).decode('utf-8-sig'))))
        self.assertEqual(len(rows), 126)
        self.assertEqual(rows[1], ["'=1+1", '0'])
        self.assertEqual(rows[-1], ['000123', '124'])

    def test_excel_preserves_codes_and_exports_each_panel(self):
        job = self.result()
        job.panels = [{'index': 0, 'title': 'EMS', 'columns': job.columns, 'row_count': 125},
                      {'index': 1, 'title': 'Certificado', 'columns': ['codigo'], 'row_count': 1}]
        job.save()
        with closing(sqlite3.connect(jobs.spool_path(job.id))) as spool:
            spool.execute('CREATE TABLE rows_1 (position INTEGER PRIMARY KEY, value TEXT NOT NULL)')
            spool.execute('INSERT INTO rows_1 VALUES (0, ?)', (json.dumps({'codigo': '000456'}),))
            spool.commit()
        response = self.client.get(f'/api/results/{job.id}/xlsx/')
        self.assertEqual(response.status_code, 200)
        workbook = load_workbook(io.BytesIO(self.content(response)))
        self.addCleanup(workbook.close)
        self.assertEqual(len(workbook.worksheets), 2)
        self.assertEqual(workbook.worksheets[0].max_row, 126)
        self.assertEqual(workbook.worksheets[0]['A2'].data_type, 's')
        self.assertEqual(workbook.worksheets[0]['A2'].value, '=1+1')
        self.assertEqual(workbook.worksheets[0]['A3'].value, '000123')
        self.assertEqual(workbook.worksheets[1]['A2'].value, '000456')

    def test_csv_neutralizes_formula_headers_too(self):
        job = self.result()
        job.columns = ['=1+1', 'codigo']
        job.save()
        response = self.client.get(f'/api/results/{job.id}/csv/')
        rows = list(csv.reader(io.StringIO(self.content(response).decode('utf-8-sig'))))
        self.assertEqual(rows[0][0], "'=1+1")

    def test_excel_formula_headers_are_text(self):
        job = self.result()
        job.columns = ['=1+1', 'codigo']
        job.save()
        response = self.client.get(f'/api/results/{job.id}/xlsx/')
        workbook = load_workbook(io.BytesIO(self.content(response)))
        self.addCleanup(workbook.close)
        self.assertEqual(workbook.active['A1'].data_type, 's')

    def test_missing_spool_does_not_download_an_empty_success(self):
        job = self.result()
        jobs.spool_path(job.id).unlink()
        for extension in ('csv', 'xlsx'):
            response = self.client.get(f'/api/results/{job.id}/{extension}/')
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()['error']['code'], 'expired')

    def test_excel_rejects_oversized_results_before_writing(self):
        job = self.result()
        job.row_count = 1048576
        job.save()
        response = self.client.get(f'/api/results/{job.id}/xlsx/')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error']['code'], 'export_too_large')

    def test_exports_enforce_ownership_expiry_readiness_and_permissions(self):
        job = self.result()
        for extension in ('csv', 'xlsx'):
            url = f'/api/results/{job.id}/{extension}/'
            save_config({'SKILL_' + extension.upper(): False})
            self.assertEqual(self.client.get(url).status_code, 403)
            save_config({'SKILL_' + extension.upper(): True})
            self.assertEqual(self.client.get(url + '?panel=5').status_code, 400)
            QueryJob.objects.filter(pk=job.id).update(status='running')
            self.assertEqual(self.client.get(url).status_code, 400)
            QueryJob.objects.filter(pk=job.id).update(status='ok', updated_at=timezone.now() - timedelta(days=10))
            self.assertEqual(self.client.get(url).status_code, 410)
            QueryJob.objects.filter(pk=job.id).update(updated_at=timezone.now())
            other = get_user_model().objects.create_user('other-' + extension)
            self.client.force_login(other)
            self.assertEqual(self.client.get(url).status_code, 404)
            self.client.force_login(self.user)
            QueryJob.objects.filter(pk=job.id).update(session_hash=session_fingerprint(self.client.session.session_key))

    def test_bulk_tracking_preserves_ambiguity_and_missing_codes(self):
        response = self.client.post('/api/tracking/', {'codes': ['BO-DEMO-001', 'NO-EXISTE']}, content_type='application/json')
        self.assertEqual(response.status_code, 202)
        job = QueryJob.objects.get(pk=response.json()['id'])
        self.assertEqual(job.status, 'ok', job.error)
        self.assertEqual(len(job.panels), 2)
        self.assertTrue(job.panels[0]['filters']['choose_service'])
        self.assertEqual(job.panels[1]['status'], 'no_matches')

    def test_bulk_tracking_validation_and_permission(self):
        for payload in ({'codes': []}, {'codes': ['X'] * 7}, {'codes': 'X,Y'},
                        {'codes': ['bad\'code']}, {'code': 'X', 'codes': ['Y']}, {'codes': [12]}):
            self.assertEqual(self.client.post('/api/tracking/', payload, content_type='application/json').status_code, 400)
        save_config({'SKILL_BULK_TRACKING': False})
        self.assertEqual(self.client.post('/api/tracking/', {'codes': ['BO-DEMO-001', 'X']}, content_type='application/json').status_code, 403)

    def test_chat_routes_bulk_tracking_without_ai(self):
        with patch('postal.jobs.plan_question', side_effect=AssertionError('No AI required')):
            response = self.client.post('/api/chat/', {'question': 'Rastrea BO-DEMO-001, BO-DEMO-002'}, content_type='application/json')
        job = QueryJob.objects.get(pk=response.json()['id'])
        self.assertEqual(job.status, 'ok', job.error)
        self.assertEqual(len(job.panels), 2)
        save_config({'SKILL_TRACKING': False})
        response = self.client.post('/api/chat/', {'question': 'Rastrea BO-DEMO-001, BO-DEMO-002'}, content_type='application/json')
        job = QueryJob.objects.get(pk=response.json()['id'])
        self.assertEqual(job.error['code'], 'disabled')

    def test_analysis_presets_are_seeded_and_preserve_customization(self):
        keys = ['delays', 'delivery-sla', 'period-comparison']
        self.assertEqual(AssistantSkill.objects.filter(preset_key__in=keys, enabled=True).count(), 3)
        skill = AssistantSkill.objects.get(preset_key='delivery-sla')
        self.assertIn('plazo', skill.instructions)
        skill.instructions, skill.enabled = 'Mi criterio postal.', False
        skill.save()
        seed = importlib.import_module('postal.migrations.0011_agent_capabilities').seed_skills
        from types import SimpleNamespace
        seed(apps, SimpleNamespace(connection=SimpleNamespace(alias='default')))
        skill.refresh_from_db()
        self.assertEqual(skill.instructions, 'Mi criterio postal.')
        self.assertFalse(skill.enabled)
