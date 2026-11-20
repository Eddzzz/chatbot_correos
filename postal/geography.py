"""Local geographic coverage for the department-wide capital search rule."""
import json
from pathlib import Path
import unicodedata


def normalized_name(value):
    return ''.join(c for c in unicodedata.normalize('NFD', value.strip().lower())
                   if not unicodedata.combining(c))


CATALOG = json.loads((Path(__file__).resolve().parent.parent / 'data' / 'municipalities.json').read_text(encoding='utf-8'))
DEPARTMENTS = {normalized_name(name): spec for name, spec in CATALOG['departments'].items()}
CAPITALS = {normalized_name(spec['capital']): name for name, spec in DEPARTMENTS.items()}
ALIASES = {'santa cruz de la sierra': 'santa cruz', 'santa ana de yacuma': 'santa ana',
           'santa ana del yacuma': 'santa ana', 'puerto rurrenabaque': 'rurrenabaque',
           'puerto menor de rurrenabaque': 'rurrenabaque', 'san ignacio de moxos': 'san ignacio'}
SPELLINGS = {}
for _department, _spec in CATALOG['departments'].items():
    for _name in [_department, _spec['capital'], *_spec['municipalities']]:
        SPELLINGS.setdefault(normalized_name(_name), set()).add(_name.lower())


def variants(value):
    value = normalized_name(value)
    canonical = ALIASES.get(value, value)
    names = [canonical] + [alias for alias, target in ALIASES.items() if target == canonical]
    # Keep both accented and plain spellings; PostgreSQL LOWER preserves accents.
    names.extend(sorted(SPELLINGS.get(canonical, ())))
    return list(dict.fromkeys(names))


def department_for(value):
    name = ALIASES.get(normalized_name(value), normalized_name(value))
    return CAPITALS.get(name, name if name in DEPARTMENTS else None)


def coverage(value):
    department = department_for(value)
    names = variants(value)
    if department:
        names += variants(department)
        for municipality in DEPARTMENTS[department]['municipalities']:
            names += variants(municipality)
    return list(dict.fromkeys(names))
