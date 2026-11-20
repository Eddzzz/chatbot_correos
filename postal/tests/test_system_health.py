import tempfile
import uuid
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from postal.models import QueryJob


class SystemHealthTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.override = override_settings(RESULT_DIR=Path(self.tmp.name), RESULT_TTL_HOURS=12)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.admin = get_user_model().objects.create_superuser('admin')
        self.user = get_user_model().objects.create_user('operador')
        self.client.force_login(self.admin)

    def test_health_attributes_files_and_jobs_without_multiplying_totals(self):
        done = QueryJob.objects.create(user=self.user, status='done', kind='query')
        QueryJob.objects.create(user=self.user, status='running', kind='query')
        QueryJob.objects.create(user=self.admin, status='queued', kind='query')
        (Path(self.tmp.name) / f'{done.pk}.sqlite3').write_bytes(b'x' * 120)
        (Path(self.tmp.name) / f'{uuid.uuid4()}.sqlite3').write_bytes(b'x' * 30)
        response = self.client.get('/system/?view=health')
        health = response.context['health']
        row = next(row for row in health['users'] if row['id'] == self.user.pk)
        self.assertEqual((row['active'], row['files'], row['bytes']), (1, 1, 120))
        self.assertEqual((health['files'], health['bytes'], health['unassigned_files']), (2, 150, 1))
        self.assertEqual(health['active_users'], 2)
        self.assertEqual(health['ttl_hours'], 12)
        self.assertContains(response, 'Estado por usuario')
        self.assertContains(response, 'Sin usuario asociado')

    def test_empty_health_and_admin_access(self):
        response = self.client.get('/system/?view=health')
        self.assertEqual(response.context['health']['files'], 0)
        self.assertEqual(response.context['health']['active_users'], 0)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/system/?view=health').status_code, 403)
