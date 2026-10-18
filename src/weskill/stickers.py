"""Keep native sticker credentials local; expose selectable IDs and stable pages."""
import hashlib
import json
from pathlib import Path
import time
import uuid

from .backend import _save_private


def _directory(state):
    directory = Path(state) / 'stickers'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory


def _record_path(state, source, sticker_id):
    token = hashlib.sha256((source + ':' + sticker_id).encode()).hexdigest()
    return _directory(state) / (token + '.json')


def remember_stickers(state, result, query):
    public = []
    for row in result.get('stickers', []):
        _save_private(_record_path(state, row['source'], row['sticker_id']),
                      {'record': row, 'query': query})
        public.append({'sticker_id': row['sticker_id'], 'source': row['source'],
                       'preview_url': row.get('thumb_url', ''),
                       'available_locally': bool(row.get('local_path'))})
    result['stickers'] = public


def search_stickers(query, state, keyword, limit, cursor):
    directory = _directory(state)
    page_id, position, native_cursor = None, 0, 0
    if cursor is not None:
        value = json.loads(cursor)
        page_id, position = value['page'], value['position']
        if not isinstance(page_id, str) or len(page_id) != 32 or any(c not in '0123456789abcdef' for c in page_id):
            raise ValueError('Invalid sticker page cursor')
        if type(position) is not int or position < 0:
            raise ValueError('Invalid sticker page position')
    rows, seen, count = [], set(), 0
    while True:
        if page_id:
            page = json.loads((directory / ('page-' + page_id + '.json')).read_text())
            if page['keyword'] != keyword:
                raise ValueError('Sticker cursor belongs to another keyword')
            response = page['response']
            seen.update(page.get('prior_ids', []))
        else:
            response = query({'operation': 'search_stickers', 'keyword': keyword,
                              'native_cursor': native_cursor})
            if response['status'] != 'client_success':
                return response
            page_id = uuid.uuid4().hex
            _save_private(directory / ('page-' + page_id + '.json'),
                          {'keyword': keyword, 'response': response, 'prior_ids': sorted(seen)})
        result = response['result']
        count += 1
        available = result['stickers']
        seen.update(row['sticker_id'] for row in available[:position])
        if position > len(available):
            raise ValueError('Sticker cursor position exceeds page length')
        while position < len(available):
            row = available[position]
            position += 1
            if row['sticker_id'] not in seen:
                seen.add(row['sticker_id'])
                rows.append(row)
            if limit and len(rows) >= limit:
                break
        remainder = position < len(available)
        more = remainder or bool(result.get('has_more'))
        following = json.dumps({'page': page_id, 'position': position}, separators=(',', ':')) if more else None
        stalled = bool(not remainder and result.get('has_more') and
                       (not available or result.get('next_native_cursor') == result.get('native_cursor')))
        if limit and len(rows) >= limit or not more or stalled:
            return {**response, 'result': {'success': True, 'stickers': rows, 'returned': len(rows),
                    'has_more': more, 'next_cursor': following, 'pagination_stalled': stalled,
                    'source': 'native_sticker_search', 'pages_read': count}}
        native_cursor = result['next_native_cursor']
        page_id, position = None, 0


def selected_parameters(state, recipient, sticker_id, source):
    path = _record_path(state, source, sticker_id)
    if not path.is_file():
        raise ValueError('Select a sticker from list_saved_stickers or search_stickers first')
    saved = json.loads(path.read_text())
    query = saved['query']
    return {'recipient_id': recipient, 'sticker_id': sticker_id, 'source': source,
            **({key: query[key] for key in ('keyword', 'native_cursor') if key in query}
               if source == 'search' else {})}


def wait_for_material(path, timeout):
    if not path:
        return False
    path = Path(path)
    deadline = time.monotonic() + timeout
    previous = None
    while time.monotonic() < deadline:
        try:
            current = (path.stat().st_size, path.stat().st_mtime_ns)
        except FileNotFoundError:
            current = None
        if current and current[0] and current == previous:
            return True
        previous = current
        time.sleep(.1)
    return False
