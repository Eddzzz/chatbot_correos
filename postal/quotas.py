"""Atomic quota reservations shared by workers through the accounts database."""
import time

from django.core.cache import cache
from django.db import connection
from django.utils.crypto import salted_hmac

from .models import RequestQuota


def _key(scope, subject):
    return salted_hmac('postal.request-quota', f'{scope}:{subject}', algorithm='sha256').hexdigest()


def reset(scope, subject):
    RequestQuota.objects.filter(pk=_key(scope, subject)).delete()


def reserve(scope, subject, limit, window):
    now = int(time.time())
    key = _key(scope, subject)
    table = connection.ops.quote_name(RequestQuota._meta.db_table)
    # The write and limit check are one statement, including when a window expires.
    with connection.cursor() as cursor:
        cursor.execute(
            f'''INSERT INTO {table} (key, expires_at, count) VALUES (%s, %s, 1)
                ON CONFLICT(key) DO UPDATE SET
                    count = CASE WHEN expires_at <= %s THEN 1 ELSE count + 1 END,
                    expires_at = CASE WHEN expires_at <= %s THEN excluded.expires_at ELSE expires_at END
                WHERE expires_at <= %s OR count < %s
                RETURNING expires_at''',
            [key, now + window, now, now, now, limit],
        )
        if cursor.fetchone():
            return 0
    expires_at = RequestQuota.objects.filter(pk=key).values_list('expires_at', flat=True).first()
    return max(1, (expires_at or now) - now)


def purge_expired():
    if cache.add('postal.request-quota.cleanup', True, 60):
        RequestQuota.objects.filter(expires_at__lte=int(time.time())).delete()
