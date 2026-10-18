"""System-expression tokens recognized by the researched client's own catalogue."""
from importlib.resources import files
import json


def system_emojis(keyword='', limit=20, offset=0):
    if not isinstance(keyword, str) or '\0' in keyword:
        raise ValueError('Expected a keyword without NUL')
    if (limit is not None and (type(limit) is not int or limit < 0)
            or type(offset) is not int or offset < 0):
        raise ValueError('Expected a nonnegative count and offset')
    keyword.encode('utf-8')
    entries = json.loads(files('weskill').joinpath('assets/system_emojis.json').read_text())
    entries = [entry for entry in entries if keyword.casefold() in entry['name'].casefold()]
    selected = entries[offset:] if limit in (0, None) else entries[offset:offset + limit]
    return {'success': True, 'emojis': selected, 'total': len(entries), 'returned': len(selected),
            'offset': offset, 'has_more': offset + len(selected) < len(entries),
            'source': 'client_builtin_catalog'}
