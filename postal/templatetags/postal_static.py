"""Invalidate cached frontend assets when their content changes."""
import hashlib
from pathlib import Path

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def versioned_static(name):
    url = static(name)
    path = finders.find(name)
    if path:
        version = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]
        url += ('&' if '?' in url else '?') + 'v=' + version
    return url
