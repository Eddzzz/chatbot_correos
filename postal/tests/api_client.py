from django.test import Client, TestCase, override_settings

from postal.views import session_fingerprint


class ApiClient(Client):
    """Send the same session header as the browser unless a test overrides it."""

    def request(self, **request):
        if request.get('PATH_INFO', '').startswith('/api/') and 'HTTP_X_BOLIPOST_USER' not in request:
            request['HTTP_X_BOLIPOST_USER'] = session_fingerprint(self.session.session_key)
        return super().request(**request)


@override_settings(QUERY_RATE_LIMITS={'chat': 12, 'tracking': 30, 'dashboard': 20})
class ApiTestCase(TestCase):
    client_class = ApiClient
