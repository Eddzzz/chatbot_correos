import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from postal.models import AIUsage, Conversation, QueryJob
from postal.views import session_fingerprint


@override_settings(JOBS_EAGER=True)
class SystemDashboardTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.override = override_settings(SYSTEM_CONFIG_PATH=Path(self.temp.name) / 'config.json',
                                          RESULT_DIR=Path(self.temp.name) / 'results')
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.user = get_user_model().objects.create_superuser('admin-dashboard', password='qa-password')
        self.client.force_login(self.user)
        self.identity = session_fingerprint(self.client.session.session_key)
        self.client.defaults['HTTP_X_BOLIPOST_USER'] = self.identity
        self.now = datetime(2026, 11, 16, 12, tzinfo=ZoneInfo('America/La_Paz'))

    def usage(self, at, total, stage='planner'):
        row = AIUsage.objects.create(user=self.user, provider='Groq', model='qa/model', stage=stage,
            prompt_tokens=max(0, total - 2) if total is not None else None,
            completion_tokens=min(2, total) if total is not None else None, total_tokens=total)
        AIUsage.objects.filter(pk=row.pk).update(created_at=at)

    def test_period_and_local_days_reconcile(self):
        from postal.system_analytics import dashboard_data
        self.usage(self.now, 12)
        self.usage(self.now.replace(hour=0, minute=1), 22, 'analyst')
        self.usage(self.now - timedelta(days=8), 100)
        data = dashboard_data(7, now=self.now)
        self.assertEqual(data['totals']['tokens'], 34)
        self.assertEqual(data['totals']['calls'], 2)
        self.assertEqual(data['totals']['users'], 1)
        self.assertEqual(sum(item['tokens'] or 0 for item in data['daily']), 34)
        self.assertEqual(data['daily'][-1]['date'], '2026-11-16')
        self.assertEqual(data['previous_tokens'], 100)

    def test_missing_tokens_and_zero_are_distinct(self):
        from postal.system_analytics import dashboard_data
        self.usage(self.now, None)
        data = dashboard_data(7, now=self.now)
        self.assertIsNone(data['totals']['tokens'])
        self.assertEqual(data['unknown_calls'], 1)
        self.assertIsNone(data['daily'][-1]['tokens'])
        self.usage(self.now, 0)
        self.assertEqual(dashboard_data(7, now=self.now)['totals']['tokens'], 0)

    def test_one_day_period_filters_today_and_survives_refresh(self):
        from unittest.mock import patch
        self.usage(self.now.replace(hour=0, minute=0), 12)
        self.usage(self.now - timedelta(days=1), 100)
        with patch('postal.system_analytics.timezone.now', return_value=self.now):
            response = self.client.get('/system/', {'days': '1'})
            self.assertContains(response, 'value="1" selected>Último día</option>')
            for params in ({'days': '1'}, {'days': '1', 'live': '1'}):
                with self.subTest(params=params):
                    response = self.client.get('/system/', params)
                    data = response.context['analytics']
                    self.assertEqual(data['days'], 1)
                    self.assertEqual(data['totals']['tokens'], 12)
                    self.assertEqual(data['previous_tokens'], 100)
                    self.assertEqual([row['date'] for row in data['daily']], ['2026-11-16'])

    def test_custom_period_includes_local_end_day_and_previous_period(self):
        from datetime import date
        from postal.system_analytics import dashboard_data
        self.usage(self.now.replace(day=10, hour=0), 10)
        self.usage(self.now.replace(day=11, hour=23, minute=59), 20)
        self.usage(self.now.replace(day=12, hour=0), 100)
        self.usage(self.now.replace(day=9), 5)
        data = dashboard_data(now=self.now, start_date=date(2026, 11, 10), end_date=date(2026, 11, 11))
        self.assertEqual(data['days'], 2)
        self.assertEqual(data['totals']['tokens'], 30)
        self.assertEqual(data['previous_tokens'], 5)
        self.assertEqual([row['date'] for row in data['daily']], ['2026-11-10', '2026-11-11'])

    def test_one_day_charts_group_by_local_hour_in_page_and_refresh(self):
        from unittest.mock import patch
        self.usage(self.now.replace(hour=0, minute=0), 12)
        self.usage(self.now.replace(hour=0, minute=59), 8)
        self.usage(self.now.replace(hour=1), None)
        self.usage(self.now.replace(hour=2), 0)
        self.usage(self.now - timedelta(days=1), 100)
        self.usage(self.now + timedelta(hours=1), 500)
        with patch('postal.system_analytics.timezone.now', return_value=self.now):
            for params in ({'days': '1'}, {'days': '1', 'live': '1'},
                           {'days': 'custom', 'start': '2026-11-16', 'end': '2026-11-16'}):
                with self.subTest(params=params):
                    response = self.client.get('/system/', params)
                    series = response.context['chart_data']['daily']
                    self.assertEqual(len(series), 13)
                    self.assertEqual(series[0]['label'], '00:00')
                    self.assertEqual(series[-1]['label'], '12:00')
                    self.assertEqual(series[0]['tokens'], 20)
                    self.assertEqual(series[0]['calls'], 2)
                    self.assertIsNone(series[1]['tokens'])
                    self.assertEqual(series[1]['calls'], 1)
                    self.assertEqual(series[2]['tokens'], 0)
                    self.assertEqual(series[3]['tokens'], 0)
                    self.assertIsNone(response.context['analytics']['hourly'][13]['tokens'])
                    self.assertIsNone(response.context['analytics']['hourly'][13]['calls'])
                    self.assertEqual(sum(row['tokens'] or 0 for row in series), 20)
                    self.assertContains(response, 'Tokens informados por hora')
                    self.assertContains(response, 'Generaciones con uso informado por hora')
                    self.assertContains(response, '<th>Hora</th>')
                    self.assertContains(response, '<td>00:00</td>')

    def test_custom_period_is_preserved_in_page_and_refresh(self):
        response = self.client.get('/system/', {'days': 'custom', 'start': '2026-01-10', 'end': '2026-01-12'})
        self.assertEqual(response.context['analytics']['start'], '2026-01-10')
        self.assertEqual(response.context['analytics']['end'], '2026-01-12')
        self.assertContains(response, 'value="custom" selected')
        self.assertContains(response, 'value="2026-01-10"')
        self.assertContains(response, 'value="2026-01-12"')

    def test_dashboard_removes_manual_refresh_bar(self):
        response = self.client.get('/system/')
        self.assertNotContains(response, 'dashboard-period')
        self.assertNotContains(response, 'Actualizar analíticas')
        self.assertContains(response, 'id="dashboard-live"')

    def test_live_dashboard_refreshes_usage_and_preserves_period(self):
        params = {'live': '1', 'days': 'custom', 'start': '2026-11-16', 'end': '2026-11-16'}
        self.usage(self.now, 12)
        response = self.client.get('/system/', params)
        self.assertContains(response, 'data-number="12"')
        self.assertNotContains(response, '<html')
        self.assertNotContains(response, 'analytics-days')
        self.assertEqual(response.headers['X-Bolipost-User'], self.identity)
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.usage(self.now, 30)
        self.usage(self.now - timedelta(days=2), 100)
        response = self.client.get('/system/', params)
        self.assertContains(response, 'data-number="42"')
        self.assertEqual(response.context['analytics']['totals']['tokens'], 42)

    def test_live_dashboard_requires_admin(self):
        self.user.is_superuser = False
        self.user.save()
        self.assertEqual(self.client.get('/system/?live=1').status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get('/system/?live=1').status_code, 302)

    def test_invalid_custom_ranges_show_errors_without_crashing(self):
        for start, end in [('', ''), ('bad', '2026-01-01'), ('2026-01-02', '2026-01-01'),
                           ('2020-01-01', '2026-01-01'), ('9999-01-01', '9999-01-02')]:
            with self.subTest(start=start, end=end):
                response = self.client.get('/system/', {'days': 'custom', 'start': start, 'end': end})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['analytics_range'].errors)
                self.assertEqual(response.context['analytics']['days'], 30)

    def test_recent_clarifications_are_not_failures(self):
        from postal.system_analytics import dashboard_data
        for status, error in [('ok', {}), ('error', {'code': 'provider_timeout'}), ('error', {'code': 'clarification'}), ('cancelled', {})]:
            job = QueryJob.objects.create(user=self.user, session_hash='qa', kind='chat', status=status, error=error)
            QueryJob.objects.filter(pk=job.pk).update(created_at=self.now - timedelta(minutes=2), updated_at=self.now)
        recent = dashboard_data(7, now=self.now)['recent_jobs']
        self.assertEqual(recent['success'], 1)
        self.assertEqual(recent['failed'], 1)
        self.assertEqual(recent['clarifications'], 1)
        self.assertEqual(recent['success_rate'], 50)

    def test_operations_follow_applied_period_after_results_expire(self):
        from unittest.mock import patch

        from django.core.management import call_command

        for days_ago, status, error in [
            (31, 'ok', {}),
            (15, 'ok', {}),
            (15, 'error', {'code': 'clarification'}),
            (15, 'cancelled', {}),
            (2, 'error', {}),
            (0, 'ok', {}),
            (0, 'running', {}),
        ]:
            job = QueryJob.objects.create(user=self.user, session_hash='qa', kind='chat', status=status, error=error)
            at = self.now - timedelta(days=days_ago)
            QueryJob.objects.filter(pk=job.pk).update(created_at=at, updated_at=at)

        custom = {'days': 'custom', 'start': '2026-11-01', 'end': '2026-11-01'}
        counts = ('success', 'failed', 'clarifications', 'cancelled', 'running', 'success_rate')
        with patch('postal.system_analytics.timezone.now', return_value=self.now):
            for cleanup in (False, True):
                if cleanup:
                    call_command('cleanup_results', verbosity=0)
                    self.assertEqual(QueryJob.objects.count(), 2)
                for params, days_label, expected in [
                    ({'days': '1'}, '1 día', (1, 0, 0, 0, 1, 100)),
                    ({'days': '7'}, '7 días', (1, 1, 0, 0, 1, 50)),
                    ({'days': '30'}, '30 días', (2, 1, 1, 1, 1, 66.7)),
                    ({'days': '90'}, '90 días', (3, 1, 1, 1, 1, 75)),
                    ({**custom, 'live': '1'}, '1 día', (1, 0, 1, 1, 0, 100)),
                ]:
                    with self.subTest(cleanup=cleanup, params=params):
                        response = self.client.get('/system/', params)
                        jobs = response.context['analytics']['recent_jobs']
                        self.assertEqual(tuple(jobs[key] for key in counts), expected)
                        self.assertContains(response, f'período seleccionado.</p></div><span class="badge-soft">{days_label}</span>')
                        self.assertContains(response, f'En curso: <strong>{expected[4]}</strong>')

    def test_partial_settings_do_not_disable_other_capabilities(self):
        from postal.system_config import save_config, configuration
        save_config({'SKILL_CHAT': True, 'SKILL_PDF': True, 'AI_MAX_TOKENS': 1000})
        response = self.client.post('/system/?view=agents', {'action': 'settings', 'settings_area': 'agents',
            'AI_MAX_TOKENS': 512, 'PLANNER_ENABLED': 'on', 'ANALYST_ENABLED': 'on',
            'PLANNER_INSTRUCTIONS': 'Resume', 'ANALYST_INSTRUCTIONS': ''})
        self.assertEqual(response.status_code, 302)
        current = configuration()
        self.assertEqual(current['AI_MAX_TOKENS'], 512)
        self.assertTrue(current['SKILL_CHAT'])
        self.assertTrue(current['SKILL_PDF'])

    def test_default_is_dashboard_and_date_range_is_validated(self):
        response = self.client.get('/system/')
        self.assertContains(response, 'Resumen y analíticas')
        self.assertContains(response, 'dashboard-data')
        response = self.client.get('/system/?view=analytics&days=invalid')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['analytics']['days'], 30)

    def test_available_tokens_card_preserves_zero_and_unknown(self):
        from unittest.mock import patch
        with patch('postal.system_views.token_availability', return_value=None):
            response = self.client.get('/system/')
        self.assertContains(response, 'Tokens disponibles')
        self.assertContains(response, 'Sin reporte de cuota')
        self.assertContains(response, 'id="available-tokens">—</dd>')
        self.assertNotContains(response, '<meter class="kpi-quota-meter"')
        with patch('postal.system_views.token_availability', return_value={
                'remaining': 0, 'limit': 6000, 'observed_at': timezone.now()}):
            response = self.client.get('/system/?days=90')
        self.assertContains(response, 'id="available-tokens">0<span class="kpi-quota-limit">/6000</span></dd>')
        self.assertContains(response, '<meter class="kpi-quota-meter" min="0" max="6000" value="0" aria-hidden="true">')
        self.assertContains(response, 'Última cuota informada')
        self.assertContains(response, 'Por minuto')
        with patch('postal.system_views.token_availability', return_value={
                'remaining': 741, 'limit': None, 'observed_at': timezone.now()}):
            response = self.client.get('/system/')
        self.assertContains(response, 'id="available-tokens">741</dd>')
        self.assertNotContains(response, '<meter class="kpi-quota-meter"')

    def test_old_quota_is_visible_with_its_report_time(self):
        from unittest.mock import patch
        with patch('postal.system_views.token_availability', return_value={
                'remaining': 741, 'limit': 8000, 'observed_at': timezone.now() - timedelta(minutes=5),
                'stale': True}):
            response = self.client.get('/system/?live=1')
        self.assertContains(response, 'id="available-tokens">741<span class="kpi-quota-limit">/8000</span></dd>')
        self.assertContains(response, '<meter class="kpi-quota-meter" min="0" max="8000" value="741" aria-hidden="true">')
        self.assertContains(response, 'Última cuota informada')
        self.assertContains(response, 'Informado el <time datetime=')
        self.assertNotContains(response, 'Reporte anterior; la cuota actual puede variar.')

    def test_overview_combines_usage_and_operations(self):
        response = self.client.get('/system/?days=7')
        for text in ('Resumen y analíticas', 'tokens-chart', 'calls-chart',
                     'Operación reciente', 'Consumo por modelo', 'Consumo por usuario',
                     'Conversaciones', 'Planificación y análisis'):
            self.assertContains(response, text)
        self.assertEqual(response.context['analytics']['days'], 7)
        self.assertNotContains(response, 'href="/system/?view=analytics"')

    def test_user_consumption_only_shows_table_when_there_are_rows(self):
        response = self.client.get('/system/')
        self.assertNotContains(response, 'aria-label="Consumo por usuario"')
        self.assertContains(response, 'Sin consumo por usuario en este período.')
        self.usage(timezone.now(), 42)
        response = self.client.get('/system/')
        self.assertContains(response, 'aria-label="Consumo por usuario"')
        self.assertContains(response, self.user.username)
        self.assertNotContains(response, 'Sin consumo por usuario en este período.')

    def test_previous_analytics_link_opens_combined_view_with_period(self):
        response = self.client.get('/system/?view=analytics&days=90')
        self.assertEqual(response.context['active_view'], 'overview')
        self.assertEqual(response.context['analytics']['days'], 90)
        self.assertContains(response, 'Operación reciente')
        self.assertContains(response, 'calls-chart')
