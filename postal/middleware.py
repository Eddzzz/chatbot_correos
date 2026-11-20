class LocalSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        import sys
        from django.conf import settings
        from django.utils.crypto import constant_time_compare
        from .views import api_identity
        request.api_identity = api_identity(request) if request.user.is_authenticated else ''
        if not settings.JOBS_EAGER and 'test' not in sys.argv and request.user.is_authenticated:
            from .jobs import start_maintenance
            start_maintenance()
        response = self.get_response(request)
        response['Referrer-Policy'] = 'same-origin'
        response['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        response['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        if request.path.startswith(('/api/', '/c/', '/system/', '/trash/')) or request.path == '/':
            response['Cache-Control'] = 'no-store, private'
        if request.path.startswith('/api/'):
            if request.api_identity and constant_time_compare(request.headers.get('X-Bolipost-User', ''), request.api_identity):
                response['X-Bolipost-User'] = request.api_identity
        return response
