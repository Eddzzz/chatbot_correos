from django.contrib.auth import get_user_model
from django.test import TestCase

from postal.models import AssistantSkill, SystemAudit


class SystemAuditTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('audit-admin')
        self.client.force_login(self.admin)

    def test_filters_pagination_and_legacy_labels(self):
        SystemAudit.objects.bulk_create([
            SystemAudit(user=self.admin, action='skill_toggle', detail='9: False')
            for _ in range(28)
        ])
        SystemAudit.objects.create(user=self.admin, action='cleanup', detail='Mantenimiento')
        response = self.client.get('/system/', {'view': 'audit', 'action_type': 'skill_toggle'})
        self.assertContains(response, 'Estado de skill cambiado')
        self.assertContains(response, 'Skill #9 · Desactivada')
        self.assertEqual(response.context['audits'].paginator.count, 28)
        self.assertEqual(len(response.context['audits']), 25)
        self.assertEqual(self.client.get('/system/?view=audit&q=Mantenimiento').context['audits'].paginator.count, 1)
        self.assertEqual(self.client.get('/system/?view=audit&start=2099-01-01').context['audits'].paginator.count, 0)

    def test_toggle_records_resource_and_origin_without_payload(self):
        skill = AssistantSkill.objects.create(name='Auditoría de prueba', instructions='contenido privado', stage='both')
        self.client.post('/system/?view=skills', {'action': 'skill_toggle', 'skill_id': skill.pk, 'enabled': '0'}, REMOTE_ADDR='127.0.0.1')
        entry = SystemAudit.objects.get(action='skill_toggle')
        self.assertIn('Auditoría de prueba', entry.detail)
        self.assertEqual(entry.metadata['actor'], 'audit-admin')
        self.assertEqual(entry.metadata['ip'], '127.0.0.1')
        self.assertEqual(entry.metadata['method'], 'POST')
        self.assertNotIn('contenido privado', str(entry.metadata))

    def test_export_escapes_formulas_and_respects_filters(self):
        SystemAudit.objects.create(user=self.admin, action='skill_save', detail='=HYPERLINK("test")')
        SystemAudit.objects.create(user=self.admin, action='cleanup', detail='Other')
        response = self.client.get('/system/?view=audit&action_type=skill_save&export=csv')
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn("'=HYPERLINK", response.content.decode('utf-8-sig'))
        self.assertNotIn('Other', response.content.decode('utf-8-sig'))

    def test_non_admin_cannot_read_or_export(self):
        self.client.force_login(get_user_model().objects.create_user('regular-audit'))
        self.assertEqual(self.client.get('/system/?view=audit&export=csv').status_code, 403)

    def test_actor_snapshot_and_resource_search_survive_deleted_account(self):
        actor = get_user_model().objects.create_user('former-admin')
        SystemAudit.objects.create(user=actor, action='settings', metadata={
            'actor': 'former-admin', 'resource': 'Agentes y tokens'})
        actor.delete()
        response = self.client.get('/system/', {'view': 'audit', 'q': 'Agentes', 'actor': 'former-admin'})
        self.assertEqual(response.context['audits'].paginator.count, 1)
        self.assertContains(response, 'former-admin')

    def test_invalid_and_reversed_dates_show_errors(self):
        for params in ({'start': 'invalid'}, {'start': '2026-11-20', 'end': '2026-11-01'}):
            response = self.client.get('/system/', {'view': 'audit', **params})
            self.assertTrue(response.context['audit_errors'])
            self.assertEqual(response.context['audits'].paginator.count, 0)

    def test_summary_and_csv_use_same_actor_filter(self):
        SystemAudit.objects.create(user=self.admin, action='skill_delete', detail='Removed', metadata={'actor': self.admin.username})
        response = self.client.get('/system/', {'view': 'audit', 'actor': self.admin.username})
        self.assertEqual(response.context['audit_summary']['total'], 1)
        self.assertEqual(response.context['audit_summary']['sensitive'], 1)
