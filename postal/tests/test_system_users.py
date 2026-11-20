import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings


@override_settings(JOBS_EAGER=True)
class SystemUserTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.override = override_settings(SYSTEM_CONFIG_PATH=Path(self.tmp.name) / 'config.json', RESULT_DIR=Path(self.tmp.name) / 'results')
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.admin = get_user_model().objects.create_superuser('gestor', password='Postal-Admin-2026')
        self.user = get_user_model().objects.create_user('operador', password='Postal-Usuario-2026')
        self.client.force_login(self.admin)

    def data(self, **extra):
        return {'action': 'user_save', 'username': 'nuevo', 'first_name': 'Ana', 'last_name': 'Lima',
                'email': 'ana@example.com', 'role': 'user', 'is_active': 'on',
                'password1': 'Correo-Nuevo-2026!', 'password2': 'Correo-Nuevo-2026!', **extra}

    def test_admin_creates_user_with_hashed_password(self):
        response = self.client.post('/system/?view=users', self.data())
        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(username='nuevo')
        self.assertTrue(user.check_password('Correo-Nuevo-2026!'))
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        self.assertEqual(user.first_name, 'Ana')

    def test_admin_can_assign_admin_role(self):
        self.client.post('/system/?view=users', self.data(role='admin'))
        user = get_user_model().objects.get(username='nuevo')
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)

    def test_normal_user_and_staff_cannot_manage_accounts(self):
        for staff in (False, True):
            self.user.is_staff = staff
            self.user.save()
            self.client.force_login(self.user)
            self.assertEqual(self.client.post('/system/?view=users', self.data()).status_code, 403)
        self.assertFalse(get_user_model().objects.filter(username='nuevo').exists())

    def test_edit_preserves_password_when_empty(self):
        original = self.user.password
        response = self.client.post('/system/?view=users', self.data(user_id=self.user.pk,
            username=self.user.username, password1='', password2=''))
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.password, original)
        self.assertEqual(self.user.first_name, 'Ana')

    def test_cannot_deactivate_or_demote_current_admin(self):
        for changes in ({'role': 'user'}, {'is_active': ''}):
            data = self.data(user_id=self.admin.pk, username=self.admin.username, role='admin', password1='', password2='')
            data.update(changes)
            response = self.client.post('/system/?view=users', data)
            self.assertEqual(response.status_code, 200)
            self.admin.refresh_from_db()
            self.assertTrue(self.admin.is_superuser)
            self.assertTrue(self.admin.is_active)

    def test_password_validation_does_not_expose_submitted_password(self):
        response = self.client.post('/system/?view=users', self.data(password1='123', password2='123'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username='nuevo').exists())
        self.assertNotContains(response, 'value="123"')

    def test_duplicate_username_is_rejected(self):
        response = self.client.post('/system/?view=users', self.data(username='operador'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(get_user_model().objects.filter(username='operador').count(), 1)

    def test_deactivation_cancels_jobs_without_removing_chats(self):
        from postal.models import Conversation, QueryJob
        chat = Conversation.objects.create(user=self.user, title='Conservar')
        job = QueryJob.objects.create(user=self.user, session_hash='qa', kind='chat', status='running')
        response = self.client.post('/system/?view=users', {'action': 'user_toggle', 'user_id': self.user.pk, 'enabled': '0'})
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        job.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertEqual(job.status, 'cancelled')
        self.assertTrue(Conversation.objects.filter(pk=chat.pk).exists())

    def test_repeated_deactivation_never_reactivates_account(self):
        for _ in range(2):
            response = self.client.post('/system/?view=users', {'action': 'user_toggle', 'user_id': self.user.pk, 'enabled': '0'})
            self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_hub_flat_navigation_and_user_search(self):
        response = self.client.get('/system/?view=manage')
        self.assertContains(response, 'Centro de administración')
        self.assertContains(response, 'class="manage-directory"')
        self.assertContains(response, 'role="group" aria-labelledby="nav-activity"')
        for view in ('overview', 'chats', 'users', 'models', 'agents', 'skills', 'network', 'health', 'audit', 'manage'):
            self.assertContains(response, 'href="/system/?view=' + view + '"')
        self.assertNotContains(response, '<details class="system-nav-group"')
        response = self.client.get('/system/?view=users&q=operador')
        self.assertEqual(list(response.context['accounts']), [self.user])
        self.assertNotContains(response, 'class="system-subnav"')

    def test_own_password_change_keeps_current_session(self):
        response = self.client.post('/system/?view=users', self.data(user_id=self.admin.pk,
            username=self.admin.username, role='admin'))
        self.assertEqual(response.status_code, 302)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password('Correo-Nuevo-2026!'))
        self.assertEqual(self.client.get('/system/?view=users').status_code, 200)

    def test_admin_resets_password_without_changing_account_details(self):
        from postal.models import SystemAudit
        old_session = Client()
        old_session.force_login(self.user)
        response = self.client.post('/system/?view=users', {
            'action': 'user_password_reset', 'user_id': self.user.pk,
            'new_password1': 'Nueva-Clave-Postal-2026!', 'new_password2': 'Nueva-Clave-Postal-2026!',
        })
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Nueva-Clave-Postal-2026!'))
        self.assertEqual(self.user.username, 'operador')
        self.assertFalse(self.user.is_superuser)
        self.assertNotIn('_auth_user_id', old_session.get('/').wsgi_request.session)
        entry = SystemAudit.objects.get(action='user_password_reset')
        self.assertNotIn('Nueva-Clave', entry.detail)

    def test_reset_rejects_invalid_passwords_and_keeps_dialog_open(self):
        original = self.user.password
        for first, second in [('123', '123'), ('Nueva-Clave-Postal-2026!', 'otra')]:
            response = self.client.post('/system/?view=users', {
                'action': 'user_password_reset', 'user_id': self.user.pk,
                'new_password1': first, 'new_password2': second,
            })
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['password_form'].errors)
            self.assertContains(response, 'id="password-editor"')
            self.assertNotContains(response, f'value="{first}"')
            self.user.refresh_from_db()
            self.assertEqual(self.user.password, original)

    def test_reset_requires_admin_and_existing_target(self):
        data = {'action': 'user_password_reset', 'new_password1': 'Nueva-Clave-Postal-2026!',
                'new_password2': 'Nueva-Clave-Postal-2026!'}
        for target in ('', 'invalid', '999999'):
            self.assertIn(self.client.post('/system/', {**data, 'user_id': target}).status_code, (400, 404))
        self.client.force_login(self.user)
        self.assertEqual(self.client.post('/system/', {**data, 'user_id': self.admin.pk}).status_code, 403)

    def test_own_reset_keeps_admin_session(self):
        response = self.client.post('/system/', {'action': 'user_password_reset', 'user_id': self.admin.pk,
            'new_password1': 'Nueva-Clave-Postal-2026!', 'new_password2': 'Nueva-Clave-Postal-2026!'})
        self.assertEqual(response.status_code, 302)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password('Nueva-Clave-Postal-2026!'))
        self.assertEqual(self.client.get('/system/?view=users').status_code, 200)
