"""Lossless request state and bounded, server-owned context for provider calls."""
from copy import deepcopy
from difflib import get_close_matches
import json
import re

from .policy import QueryRejected, validate_ai_sql


def compact_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=str, allow_nan=False)


def correction_slot(question):
    """Only replace standalone corrections; retain unfamiliar constraints verbatim."""
    text = question.strip().rstrip('.!?').casefold()
    prefix = r'(?:(?:ahora|mejor)\s+)?'
    if re.fullmatch(prefix + r'(?:(?:del?|en|año)\s+)?[12]\d{3}', text):
        return 'year'
    if re.fullmatch(prefix + r'(?:(?:solo|solamente|servicio|para|de)\s+)?(?:ems|certi|certificado|contrato|ordi|ordinario|internacional)', text):
        return 'service'
    if re.fullmatch(prefix + r'(?:(?:en|de|para)\s+)?(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)', text):
        return 'month'
    return None


def advance_state(state, question, clarification=None):
    state = deepcopy(state) if state else {'request': question, 'updates': {}, 'notes': [], 'recent': []}
    if question != state['request']:
        slot = correction_slot(question)
        if slot:
            state['updates'][slot] = question
        elif question not in state['notes']:
            state['notes'].append(question)
    turn = {'question': question}
    if clarification:
        turn['clarification'] = clarification
    state['recent'] = [*state['recent'], turn][-3:]
    state['pending_clarification'] = clarification
    return state


def settled_state(question, result_id, previous=None, panels=()):
    # Executed SQL/filters now carry resolved constraints; obsolete corrections are unnecessary.
    state = advance_state({}, question)
    if previous:
        state['recent'] = [*previous.get('recent', []), {'question': question}][-3:]
    state['results'] = [*(previous or {}).get('results', []),
                        {'question': question, 'result_id': str(result_id)}]
    state['result_id'] = str(result_id)
    state['scope'] = [{'source_tables': panel.get('source_tables', []),
                       'filters': deepcopy(panel.get('filters', {}))} for panel in panels]
    return state


def needs_result_rows(question):
    # Omit rows only for unambiguous standalone scope changes. Unknown references keep evidence.
    return correction_slot(question) is None


def explanation_followup(question):
    """Recognize interpretation of the last result, leaving new scopes to planning."""
    text = ' '.join(question.casefold().strip(' .!?').split())
    # Correct this intent word only; place names and requested filters stay untouched.
    text = re.sub(r'\bexpl\w{4,}\b', lambda match: 'explicacion' if
                  get_close_matches(match.group(), ('explicacion', 'explicación'), n=1, cutoff=0.84)
                  else match.group(), text)
    reference = r'(?:eso|esto|estos datos|esos datos|el resultado|los resultados|el gr[aá]fico|la gr[aá]fica|el dashboard|el consejo)'
    return bool(re.fullmatch(
        r'(?:(?:por favor|ahora)\s+)?(?:'
        r'(?:(?:dame|quiero|necesito)\s+(?:una?\s+)?)?(?:explicaci[oó]n|resumen|consejos?)(?:\s+(?:breve|detallad[oa]))?(?:\s+(?:de|sobre)\s+' + reference + r')?'
        r'|expl[ií]ca(?:me)?(?:\s+' + reference + r')?(?:\s+(?:m[aá]s|en detalle))?'
        r'|(?:ampl[ií]a|desarrolla)(?:\s+' + reference + r')?'
        r'|m[aá]s (?:detalle|informaci[oó]n))', text))


def _compact_location_sql(sql, tree, normalize_location_sql):
    """Invert only predicates reproduced exactly by the execution normalizer."""
    from sqlglot import exp
    from sqlglot.optimizer.scope import traverse_scope

    def unparen(node):
        while isinstance(node, exp.Paren):
            node = node.this
        return node

    changed = False
    for scope in reversed(list(traverse_scope(tree))):
        for predicate in list(scope.find_all(exp.In)):
            if predicate.args.get('query') or not predicate.expressions:
                continue
            field = predicate.this
            while isinstance(field, (exp.Lower, exp.Upper, exp.Trim, exp.Paren)):
                field = field.this
            if not isinstance(field, exp.Column):
                continue
            source = scope.sources.get(field.table)
            if not isinstance(source, exp.Table):
                continue
            if not ((source.name.startswith('paquetes_') and field.name in ('ciudad', 'cuidad', 'origen', 'destino'))
                    or (source.name == 'sucursales' and field.name in ('municipio', 'departamento'))):
                continue
            seed = predicate.expressions[0]
            if not isinstance(seed, exp.Literal) or not seed.is_string:
                continue
            compact = exp.EQ(this=field.copy(), expression=seed.copy())
            probe = exp.select(exp.Count(this=exp.Star())).from_(source.copy()).where(compact.copy())
            try:
                expanded, _ = validate_ai_sql(normalize_location_sql(probe.sql(dialect='postgres')))
            except QueryRejected:
                continue
            expected = unparen(expanded.args['where'].this)
            if not isinstance(expected, exp.Or):
                continue
            node = predicate
            while node is not None:
                if unparen(node) == expected:
                    node.replace(compact)
                    changed = True
                    break
                parent = node.parent
                if not isinstance(parent, (exp.Or, exp.Paren)):
                    break
                node = parent
    return tree.sql(dialect='postgres') if changed else sql


def compress_context(question, context, normalize_location_sql=None):
    if not context:
        return None
    result = {key: deepcopy(value) for key, value in context.items()
              if key not in ('state', 'conversation', 'preview_first_page', 'preview_is_partial', 'report_panels')}
    state = context.get('state')
    if not state:
        for turn in context.get('conversation', []):
            state = advance_state(state, turn['question'], turn.get('clarification'))
    if state:
        state = deepcopy(state)
        # Historical result references stay private; jobs resolves them only when requested.
        state.pop('results', None)
        state.pop('scope', None)  # Already supplied by verified SQL/filters below.
        result['conversation'] = state.pop('recent', [])
        # These turns are already carried exactly by the anchor/notes/recent window.
        state['notes'] = [note for note in state['notes']
                          if note not in {turn['question'] for turn in result['conversation']}]
        result['state'] = {key: value for key, value in state.items() if value not in ({}, [], None)}
        if result.get('question') == state.get('request'):
            result.pop('question')
    panels = [deepcopy(panel) for panel in context.get('report_panels', [])]
    for item in [result, *panels]:
        if item.get('comparison', {}).get('base_sql'):
            # The comparison descriptor retains the complete SQL template and geography.
            item.pop('sql', None)
            item.pop('filters', None)
        if item.get('sql'):
            try:
                tree, _ = validate_ai_sql(item['sql'])
                if normalize_location_sql:
                    item['sql'] = _compact_location_sql(item['sql'], tree, normalize_location_sql)
            except QueryRejected:
                item.pop('sql')
        filters = item.get('filters', {})
        # SQL already contains these exact predicates. Keep server report date/parameter filters.
        if item.get('sql') and set(filters) <= {'fuentes', 'condiciones'}:
            item.pop('filters', None)
    for panel in panels:
        for key in ('sql', 'filters'):
            if key in result and panel.get(key) == result[key]:
                panel.pop(key, None)
        if 'row_count' in panel and panel['row_count'] == result.get('total_rows') and len(panels) == 1:
            panel.pop('row_count')
    if panels:
        result['report_panels'] = panels
    if needs_result_rows(question) and 'preview_first_page' in context:
        result['preview_first_page'] = deepcopy(context['preview_first_page'])
        result['preview_is_partial'] = context.get('preview_is_partial', False)
    if 'historical_result' in context:
        result['historical_result'] = compress_context(question, context['historical_result'], normalize_location_sql)
    return result


def compact_evidence(panels, budget=24000):
    evidence = [{key: deepcopy(panel[key]) for key in
                 ('title', 'columns', 'row_count', 'source_tables', 'filters', 'rows') if key in panel}
                for panel in panels]
    for original, panel in zip(panels, evidence):
        filters = panel.get('filters', {})
        if original.get('sql') and set(filters) <= {'fuentes', 'condiciones'} and filters.get('condiciones'):
            from sqlglot import exp
            from .ai import _normalize_location_filters
            try:
                tree, _ = validate_ai_sql(original['sql'])
                conditions = [where.this.sql(dialect='postgres') for where in tree.find_all(exp.Where)]
                if filters['condiciones'] == conditions:
                    compact_sql = _compact_location_sql(original['sql'], tree, _normalize_location_filters)
                    compact_tree, _ = validate_ai_sql(compact_sql)
                    filters['condiciones'] = [where.this.sql(dialect='postgres') for where in compact_tree.find_all(exp.Where)]
            except QueryRejected:
                pass
        if len(panel['rows']) != panel['row_count']:
            panel['rows'] = panel['rows'][:20]
        panel['complete'] = len(panel['rows']) == panel['row_count']
    # Reduce partial lists first, preserving small complete aggregates and row indices.
    while len(compact_json(evidence)) > budget:
        candidates = [panel for panel in evidence if not panel['complete'] and len(panel['rows']) > 1]
        if not candidates:
            candidates = [panel for panel in evidence if len(panel['rows']) > 1]
        if not candidates:
            break
        largest = max(candidates, key=lambda panel: len(compact_json(panel['rows'])))
        largest['rows'] = largest['rows'][:max(1, len(largest['rows']) // 2)]
        largest['complete'] = len(largest['rows']) == largest['row_count']
    return evidence

