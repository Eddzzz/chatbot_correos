"""Administrative aggregates from local records; no provider or postal DB requests."""
from datetime import datetime, time, timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate, TruncHour
from django.utils import timezone

from .models import AIUsage, Conversation, QueryJob


def dashboard_data(days=30, now=None, start_date=None, end_date=None):
    days = days if days in (1, 7, 30, 90) else 30
    now = now or timezone.now()
    tz = timezone.get_current_timezone()
    today = timezone.localtime(now, tz).date()
    first = today - timedelta(days=days - 1)
    last = today
    if start_date is not None and end_date is not None:
        first, last = start_date, end_date
        days = (last - first).days + 1
        if not 1 <= days <= 366 or last > today:
            raise ValueError('Invalid analytics range')
    start = timezone.make_aware(datetime.combine(first, time.min), tz)
    until = min(now, timezone.make_aware(datetime.combine(last, time.max), tz))
    usage = AIUsage.objects.filter(created_at__gte=start, created_at__lte=until)
    totals = usage.aggregate(tokens=Sum('total_tokens'), prompt=Sum('prompt_tokens'),
                             completion=Sum('completion_tokens'), calls=Count('id'))
    totals['users'] = usage.exclude(user_id=None).values('user_id').distinct().count()
    daily_rows = {row['day']: row for row in usage.annotate(day=TruncDate('created_at', tzinfo=tz)).values('day').annotate(
        tokens=Sum('total_tokens'), calls=Count('id')).order_by('day')}
    daily = []
    for offset in range(days):
        day = first + timedelta(days=offset)
        values = daily_rows.get(day, {'tokens': 0, 'calls': 0})
        daily.append({'date': day.isoformat(), 'label': day.strftime('%d/%m'),
                      'tokens': values['tokens'], 'calls': values['calls']})
    hourly = []
    if days == 1:
        hourly_rows = {row['hour']: row for row in usage.annotate(hour=TruncHour('created_at', tzinfo=tz)).values('hour').annotate(
            tokens=Sum('total_tokens'), calls=Count('id'))}
        for offset in range(24):
            hour = start + timedelta(hours=offset)
            empty = None if hour > until else 0
            values = hourly_rows.get(hour, {'tokens': empty, 'calls': empty})
            hourly.append({'date': hour.isoformat(), 'label': hour.strftime('%H:%M'),
                           'tokens': values['tokens'], 'calls': values['calls']})
    previous = AIUsage.objects.filter(created_at__gte=start - timedelta(days=days), created_at__lt=start).aggregate(tokens=Sum('total_tokens'))['tokens']
    groups = list(usage.values('provider', 'model').annotate(tokens=Sum('total_tokens'),
                  calls=Count('id')).order_by('-tokens', 'provider', 'model')[:8])
    stages = list(usage.values('stage').annotate(tokens=Sum('total_tokens'), calls=Count('id')).order_by('stage'))
    users = list(usage.values('user_id', 'user__username').annotate(tokens=Sum('total_tokens'), calls=Count('id')).order_by('-tokens', 'user__username')[:8])
    chats = Conversation.objects.filter(created_at__gte=start, created_at__lte=until)
    totals['chats'] = chats.count()
    recent = QueryJob.objects.filter(created_at__gte=now - timedelta(hours=24), created_at__lte=now)
    jobs = recent.aggregate(total=Count('id'), success=Count('id', filter=Q(status__in=['ok', 'no_matches', 'empty_table'])),
        failed=Count('id', filter=Q(status='error') & ~Q(error__code='clarification')),
        clarifications=Count('id', filter=Q(status='error', error__code='clarification')),
        cancelled=Count('id', filter=Q(status='cancelled')),
        running=Count('id', filter=Q(status__in=['queued', 'running'])))
    # JSON missing keys use SQL NULL; count failures explicitly without excluding absent codes.
    jobs['failed'] = recent.filter(status='error').count() - jobs['clarifications']
    resolved = jobs['success'] + jobs['failed']
    jobs['success_rate'] = round(jobs['success'] * 100 / resolved, 1) if resolved else None
    return {'days': days, 'start': first.isoformat(), 'end': last.isoformat(), 'until': until.isoformat(), 'updated_at': timezone.localtime(now, tz).isoformat(),
            'totals': totals, 'daily': daily, 'hourly': hourly, 'previous_tokens': previous,
            'unknown_calls': usage.filter(total_tokens__isnull=True).count(),
            'models': groups, 'stages': stages, 'users': users, 'recent_jobs': jobs,
            'chat_counts': {'active': Conversation.objects.filter(deleted_at__isnull=True).count(),
                            'trash': Conversation.objects.filter(deleted_at__isnull=False).count()},
            'latest_chats': list(Conversation.objects.select_related('user').defer('messages')[:4]),
            'recent_errors': list(recent.filter(status='error').exclude(error__code='clarification').only('id', 'kind', 'created_at')[:4])}
