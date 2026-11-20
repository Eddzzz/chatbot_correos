"""Replace demo rows without mocking JSON parsing for configuration or policy."""
from contextlib import contextmanager
import json
from pathlib import Path
from unittest.mock import patch


@contextmanager
def demo_fixtures(rows):
    read_text = Path.read_text
    def read(path, *args, **kwargs):
        return json.dumps(rows) if path.name == 'demo.json' else read_text(path, *args, **kwargs)
    with patch('postal.data.Path.read_text', autospec=True, side_effect=read):
        yield
