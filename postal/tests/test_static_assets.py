import tempfile
from pathlib import Path
from unittest.mock import patch

from django.template import Context, Template
from django.test import SimpleTestCase, override_settings


@override_settings(STATIC_URL='/static/')
class StaticAssetTests(SimpleTestCase):
    def test_asset_url_changes_when_file_content_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            asset = Path(folder) / 'app.css'
            asset.write_text('body { color: red; }', encoding='utf-8')
            with patch('django.contrib.staticfiles.finders.find', return_value=str(asset)):
                template = Template("{% load postal_static %}{% versioned_static 'postal/app.css' %}")
                original = template.render(Context())
                self.assertEqual(original, template.render(Context()))
                self.assertTrue(original.startswith('/static/postal/app.css?v='))
                asset.write_text('body { color: blue; }', encoding='utf-8')
                self.assertNotEqual(original, template.render(Context()))

    def test_login_and_workspace_request_versioned_styles_and_scripts(self):
        from django.contrib.auth.models import AnonymousUser
        from django.template.loader import render_to_string
        for name in ('registration/login.html', 'postal/app.html'):
            with self.subTest(template=name):
                rendered = render_to_string(name, {'user': AnonymousUser()})
                self.assertRegex(rendered, r'/static/postal/app\.css\?v=[a-f0-9]+')
                self.assertRegex(rendered, r'/static/postal/theme\.js\?v=[a-f0-9]+')
                self.assertNotIn('width="2170"', rendered)
                if name == 'postal/app.html':
                    self.assertRegex(rendered, r'/static/postal/app\.js\?v=[a-f0-9]+')
