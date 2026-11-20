"""Account-owned persistent history and 30-day trash lifecycle."""
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import Conversation, PurgedConversation, QueryJob
from .history import read_messages, verified_result
from .views import api_view, body, error, text


def summary(chat):
    return {'id': str(chat.id), 'title': chat.title, 'revision': chat.revision,
            'updated': int(chat.updated_at.timestamp() * 1000),
            'deleted_at': chat.deleted_at.isoformat() if chat.deleted_at else None}


def purge_trash(now=None):
    from .jobs import spool_path
    cutoff = (now or timezone.now()) - timedelta(days=30)
    count = 0
    for chat in Conversation.objects.filter(deleted_at__lte=cutoff).iterator():
        # A failed file removal leaves the chat in trash for the next maintenance pass.
        try:
            for job_id in QueryJob.objects.filter(conversation=chat).values_list('id', flat=True):
                spool_path(job_id).unlink(missing_ok=True)
        except OSError:
            continue
        with transaction.atomic():
            eligible = Conversation.objects.filter(pk=chat.pk, deleted_at__lte=cutoff).first()
            if eligible:
                PurgedConversation.objects.get_or_create(pk=chat.pk, defaults={'user_id': chat.user_id})
                count += Conversation.objects.filter(pk=chat.pk, deleted_at__lte=cutoff).delete()[1].get('postal.Conversation', 0)
    return count


def move_to_trash(chat):
    from .jobs import cancel
    with transaction.atomic():
        changed = Conversation.objects.filter(pk=chat.pk, deleted_at__isnull=True).update(
            deleted_at=timezone.now(), revision=F('revision') + 1)
        if changed:
            for job_id in QueryJob.objects.filter(conversation=chat, status__in=['queued', 'running']).values_list('id', flat=True):
                cancel(job_id)


def restore(chat):
    return Conversation.objects.filter(pk=chat.pk, deleted_at__gt=timezone.now() - timedelta(days=30)).update(
        deleted_at=None, revision=F('revision') + 1, updated_at=timezone.now())


@api_view()
def list_view(request):
    purge_trash()
    try:
        page = int(request.GET.get('page', 1))
        if not 1 <= page <= 100000:
            raise ValueError
    except ValueError:
        return error('invalid_page', 'Página no válida.')
    chats = Conversation.objects.filter(user=request.user, deleted_at__isnull=request.GET.get('trash') != '1')
    batch = list(chats[(page - 1) * 50:page * 50 + 1])
    return JsonResponse({'conversations': [summary(chat) for chat in batch[:50]], 'has_more': len(batch) > 50})


@api_view()
def detail_view(request, chat_id):
    chat = get_object_or_404(Conversation, pk=chat_id, user=request.user, deleted_at__isnull=True)
    messages, omitted = read_messages(chat)
    return JsonResponse({**summary(chat), 'messages': messages, 'unverified_results': omitted})


@api_view('POST')
def save_view(request, chat_id):
    data = body(request, ['title', 'messages', 'revision'], ['import_only'], maximum=4 * 1024 * 1024)
    title = text(data['title'], 180, 'un título')
    messages = data['messages']
    import_only = data.get('import_only', False)
    if (not isinstance(messages, list) or len(messages) > 2000 or
            type(data['revision']) is not int or data['revision'] < 0 or
            type(import_only) is not bool):
        return error('invalid_input', 'El historial o su versión no son válidos.')
    stored = []
    result_ids = set()
    question = None
    for message in messages:
        if not isinstance(message, dict) or message.get('kind') not in ('question', 'result'):
            return error('invalid_input', 'El historial contiene un mensaje no válido.')
        if message['kind'] == 'question':
            if not isinstance(message.get('text'), str) or len(message['text']) > 4000:
                return error('invalid_input', 'La pregunta guardada no es válida.')
            question = message['text']
            stored.append({'kind': 'question', 'text': question})
        else:
            if import_only:
                return error('unverified_result', 'La importación local admite solo preguntas.')
            proof = message.get('proof')
            result = verified_result(proof, request.user.pk, chat_id, question)
            if set(message) != {'kind', 'proof'} or result is None or result['id'] in result_ids:
                return error('unverified_result', 'La respuesta guardada no corresponde a un resultado verificado de esta conversación.')
            result_ids.add(result['id'])
            stored.append({'kind': 'result', 'proof': proof})
            question = None
    with transaction.atomic():
        tombstone = PurgedConversation.objects.filter(pk=chat_id).first()
        if tombstone:
            if tombstone.user_id != request.user.pk:
                return error('not_found', 'La conversación no existe.', 404)
            return error('expired', 'La conversación se eliminó definitivamente. Inicie un chat nuevo.', 410)
        chat, created = Conversation.objects.get_or_create(pk=chat_id, defaults={
            'user': request.user, 'title': title, 'messages': stored})
        if chat.user_id != request.user.pk:
            return error('not_found', 'La conversación no existe.', 404)
        if import_only:
            if created:
                return JsonResponse({**summary(chat), 'import_status': 'imported'}, status=201)
            if chat.deleted_at is None and chat.title == title and chat.messages == stored:
                return JsonResponse({**summary(chat), 'import_status': 'already_imported'})
            return error('import_conflict', 'La conversación ya existe con otro contenido o está en la papelera. Se conservó la copia local.', 409)
        if not created:
            changed = Conversation.objects.filter(pk=chat_id, deleted_at__isnull=True, revision=data['revision']).update(
                title=title, messages=stored, revision=F('revision') + 1, updated_at=timezone.now())
            if not changed:
                return error('chat_conflict', 'La conversación cambió en otra pestaña o está en la papelera. Recargue para ver su estado actual.', 409)
            chat.refresh_from_db()
    return JsonResponse(summary(chat))


@api_view('POST')
def trash_view(request, chat_id):
    body(request, [])
    chat = get_object_or_404(Conversation, pk=chat_id, user=request.user)
    move_to_trash(chat)
    return JsonResponse({'ok': True})


@api_view('POST')
def restore_view(request, chat_id):
    body(request, [])
    chat = get_object_or_404(Conversation, pk=chat_id, user=request.user)
    if not restore(chat):
        return error('expired', 'La conversación ya no está disponible para restaurar.', 410)
    return JsonResponse({'ok': True})
