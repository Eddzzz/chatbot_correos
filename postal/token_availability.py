"""Last reported provider quotas, separate from historical token usage."""
import hashlib
import json

from django.core.cache import caches
from django.utils import timezone


def _cache_key(config):
    # Scope snapshots to the exact credential, endpoint and model, including backups.
    digest = hashlib.sha256(json.dumps(config).encode()).hexdigest()
    return 'provider-token-availability:' + digest


def record_token_availability(config, headers):
    if config[0] != 'Groq':
        return
    remaining = headers.get('x-ratelimit-remaining-tokens', '')
    limit = headers.get('x-ratelimit-limit-tokens', '')
    if not remaining.isascii() or not remaining.isdigit() or len(remaining) > 18:
        return
    limit = int(limit) if limit.isascii() and limit.isdigit() and len(limit) <= 18 else None
    caches['provider_quotas'].set(_cache_key(config), {
        'remaining': int(remaining), 'limit': limit, 'observed_at': timezone.now(),
    }, timeout=None)


def token_availability(config):
    snapshot = caches['provider_quotas'].get(_cache_key(config)) if config[0] == 'Groq' else None
    if snapshot is not None:
        snapshot['stale'] = (timezone.now() - snapshot['observed_at']).total_seconds() >= 60
    return snapshot
