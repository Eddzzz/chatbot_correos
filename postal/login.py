import unicodedata

from django.conf import settings
from django.contrib.auth.views import LoginView

from .quotas import purge_expired, reserve, reset


class LimitedLoginView(LoginView):
    def post(self, request, *args, **kwargs):
        purge_expired()
        username = unicodedata.normalize('NFKC', request.POST.get('username', '').strip()[:150])
        origin = request.META.get('REMOTE_ADDR') or 'unknown'
        self.quota_subject = (origin, username)
        wait = reserve('login-origin-account', self.quota_subject,
                       settings.LOGIN_ACCOUNT_LIMIT, settings.LOGIN_RATE_WINDOW)
        if wait:
            response = self.render_to_response(self.get_context_data(
                form=self.get_form_class()(request=request), retry_after=wait), status=429)
            response.headers['Retry-After'] = str(wait)
            return response
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        reset('login-origin-account', self.quota_subject)
        return response
