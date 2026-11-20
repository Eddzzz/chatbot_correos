"""Proofs for snapshots delivered by the server, scoped to one chat turn."""
import json
import re

from django.core import signing
from django.core.serializers.json import DjangoJSONEncoder


class ResultSerializer:
    def dumps(self, value):
        return DjangoJSONEncoder(ensure_ascii=True, separators=(',', ':')).encode(value).encode('ascii')

    def loads(self, value):
        return json.loads(value)


def _sign(user_id, chat_id, question, result):
    return signing.dumps([user_id, str(chat_id), question, result], salt='postal.history.v1',
                         serializer=ResultSerializer, compress=True)


def issue_proof(job, result):
    return _sign(job.user_id, job.conversation_id, job.question, result)


def public_result(result):
    def panel_data(panel):
        public = {key: value for key, value in panel.items()
                  if key not in {'sql', 'source_tables', 'analysis', 'comparison', 'chart_spec', 'filters'}}
        tracking_filters = {key: value for key, value in (panel.get('filters') or {}).items()
                            if key in {'codigo', 'choose_service'}}
        if tracking_filters:
            public['filters'] = tracking_filters
        answer = public.get('answer') or ''
        if answer.endswith(' Respaldo histórico, no tiempo real.'):
            provenance = re.search(r'\n\nFuente de «.{1,180}?»:\s+assistant\.', answer, re.S)
            if provenance:
                public['answer'] = (answer[:provenance.start()] +
                                    '\n\nLos resultados corresponden al respaldo histórico.')
        if ('sucursales' in panel.get('source_tables', ()) and
                {'sucursal_codigo', 'codigo_sucursal', 'codigoSucursal'}.intersection(panel.get('columns', ()))):
            public['refresh_branch_names'] = True
        return public

    public = panel_data(result)
    if 'panels' in result:
        public['panels'] = [panel_data(panel) for panel in result['panels']]
    analysis = result.get('analysis') or {}
    if analysis:
        public['is_explanation'] = bool(analysis.get('presentation') == 'explanation' or (
            re.match(r'^explicaci[oó]n\b', result.get('title', ''), re.I)
            and (analysis.get('generated') or analysis.get('citations'))))
        for key in ('note', 'warning'):
            if analysis.get(key):
                public[key] = analysis[key]
    return public


def verified_result(proof, user_id, chat_id, question):
    if not isinstance(proof, str) or question is None:
        return None
    try:
        owner, chat, prompt, result = signing.loads(proof, salt='postal.history.v1', serializer=ResultSerializer)
    except signing.BadSignature:
        return None
    if (owner, chat, prompt) == (user_id, str(chat_id), question):
        return result
    return None


def read_messages(chat):
    messages, omitted = [], 0
    question = None
    for message in chat.messages:
        if message['kind'] == 'question':
            question = message['text']
            messages.append({'kind': 'question', 'text': question})
        else:
            proof = message.get('proof')
            result = verified_result(proof, chat.user_id, chat.pk, question)
            if result is None:
                omitted += 1
            else:
                public = public_result(result)
                if public != result:
                    proof = _sign(chat.user_id, chat.pk, question, public)
                messages.append({'kind': 'result', 'result': public, 'proof': proof})
            question = None
    return messages, omitted
