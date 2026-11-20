from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Q

from .models import QueryJob


def health_data(files):
    users = list(get_user_model().objects.values('id', 'username', 'first_name', 'last_name', 'is_active')
        .annotate(active=Count('queryjob', filter=Q(queryjob__status__in=['queued', 'running'])),
                  queries=Count('queryjob'), latest=Max('queryjob__updated_at'))
        .order_by('username', 'id'))
    by_user = {user['id']: user for user in users}
    for user in users:
        user.update(files=0, bytes=0)
    owners = {str(job_id): user_id for job_id, user_id in QueryJob.objects.values_list('id', 'user_id')}
    total_files = total_bytes = unassigned_files = unassigned_bytes = 0
    for path in files:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        total_files += 1
        total_bytes += size
        user = by_user.get(owners.get(path.stem))
        if user is None:
            unassigned_files += 1
            unassigned_bytes += size
        else:
            user['files'] += 1
            user['bytes'] += size
    return {'users': users, 'active_users': sum(bool(u['queries'] or u['files']) for u in users),
            'files': total_files, 'bytes': total_bytes,
            'unassigned_files': unassigned_files, 'unassigned_bytes': unassigned_bytes,
            'ttl_hours': settings.RESULT_TTL_HOURS}
