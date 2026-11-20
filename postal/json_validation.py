"""Strict JSON at HTTP trust boundaries; duplicate keys are ambiguous."""
import json


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _constant(value):
    raise ValueError('Non-finite JSON number')


def load_object(raw):
    value = json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object')
    # Reject infinite exponents and unpaired surrogates before DB/HTTP encoding.
    json.dumps(value, allow_nan=False, ensure_ascii=False).encode('utf-8')
    return value
