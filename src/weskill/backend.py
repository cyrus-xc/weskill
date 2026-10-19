"""Native operations for the local MCP; client success is the send-success criterion.

One session and executor bridge per backend. Completed business agents are
released after native ownership ends; uncertain callbacks remain retained.
No native operation runs during construction.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import uuid

HISTORY_PAGE_SIZE = 200
MAIN_SHA256 = '71e22a172018bf250b7b70493382bf55024727144eb7f13cf9b312cdf02e5bbc'
def valid_chat_id(value):
    return isinstance(value, str) and bool(value.strip()) and '\0' not in value


def valid_limit(value):
    return value is None or type(value) is int and value >= 0


class NativeConnectionTimeout(TimeoutError):
    """The pre-submission attachment watchdog was exhausted."""


def _start_time(pid: int) -> str:
    value = Path(f'/proc/{pid}/stat').read_text()
    return value[value.rfind(')') + 2:].split()[19]


def _save_private(path: Path, value: dict) -> None:
    """Replace and fsync both file and parent before any native submission."""
    fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, ensure_ascii=True, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class ExperimentalBackend:
    def __init__(self, pid: int, shim_path: Path | str, state_dir: Path | str):
        if type(pid) is not int or pid <= 0:
            raise ValueError('Expected an explicit positive WeChat PID')
        self.pid = pid
        self.shim_path = Path(shim_path).resolve()
        self.state_dir = Path(state_dir).resolve()
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.state_dir, 0o700)
        self._lock = threading.RLock()
        self._session = None
        self._binding = None
        self._scripts = []
        from .native_resources import NativeResources
        self._resources = NativeResources(self)
        self._frida = None
        self._unsafe = None
        self.timeout_seconds = 30.0
        self.attach_timeout_seconds = 15.0
        self.connection_attempts = 0
        self._phase = "not_started"

    @contextmanager
    def _ledger_lock(self):
        # Also serializes backend instances sharing this durable ledger.
        fd = os.open(self.state_dir / '.operation.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _verify_binding(self):
        started, device, inode = self._binding
        if _start_time(self.pid) != started:
            raise ValueError('Target PID was reused')
        with open(f'/proc/{self.pid}/exe', 'rb') as stream:
            st = os.fstat(stream.fileno())
            if (st.st_dev, st.st_ino) != (device, inode):
                raise ValueError('Target executable mapping changed')

    def _ensure_session(self):
        if self._unsafe:
            raise RuntimeError(self._unsafe)
        if self._session is not None:
            self._verify_binding()
            return self._session
        import frida
        if frida.__version__ != '16.7.19':
            raise ValueError('Experimental backend requires Frida 16.7.19')
        self._frida = frida
        if not self.shim_path.is_file():
            raise ValueError('Build the verified native executor shim first')
        started = _start_time(self.pid)
        if os.readlink(f'/proc/{self.pid}/exe') != '/opt/wechat/wechat':
            raise ValueError('Expected installed WeChat main executable')
        with open(f'/proc/{self.pid}/exe', 'rb') as stream:
            st = os.fstat(stream.fileno())
            if hashlib.file_digest(stream, 'sha256').hexdigest() != MAIN_SHA256:
                raise ValueError('Target differs from researched ARM64 build')
        self._binding = (started, st.st_dev, st.st_ino)
        session = self._attach_session(frida)
        try:
            self._verify_binding()
        except BaseException:
            session.detach()  # No business scripts exist yet.
            raise
        self._session = session
        return session

    def _attach_session(self, frida):
        # Restart policy belongs to the parent, which replaces an unready worker.
        self._verify_binding()
        self.connection_attempts = 1
        cancel = frida.Cancellable()
        timer = threading.Timer(self.attach_timeout_seconds, cancel.cancel)
        timer.daemon = True
        timer.start()
        try:
            with cancel:
                self._phase = 'connection.local_device'
                device = frida.get_local_device()
                self._phase = 'connection.attach'
                return device.attach(self.pid)
        except frida.OperationCancelledError as error:
            if not cancel.is_cancelled:
                raise
            raise NativeConnectionTimeout(
                'Native connection timed out before any business task was submitted'
            ) from error
        finally:
            timer.cancel()

    def _rpc(self, script, name, *args):
        self._phase = "native." + name
        cancel = self._frida.Cancellable()
        timer = threading.Timer(self.timeout_seconds, cancel.cancel)
        timer.daemon = True
        timer.start()
        try:
            with cancel:
                return getattr(script.exports_sync, name)(*args)
        finally:
            timer.cancel()

    def _wait_idle(self, script, invokes):
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            state = self._rpc(script, 'bridge_status')
            if state['idle'] and int(state['invokes']) >= invokes:
                if int(state['allocations']) != int(state['frees']):
                    raise RuntimeError('Native executor allocation accounting differs')
                return state
            time.sleep(0.05)
        raise TimeoutError('Executor task pending; native buffers remain retained')

    def _run(self, mode: str, parameters: dict) -> dict:
        started = time.monotonic()
        self._phase = "connection"
        events = []
        event_lock = threading.Lock()
        script = None
        bridge = None
        bridge_handler_attached = False
        submission_possible = False
        state = None
        response = {'status': 'not_submitted', 'result': None,
                    'delivery_confirmed': False, 'errors': []}
        journal = self.state_dir / f'request-{uuid.uuid4().hex}.json'

        def on_message(message, data):
            with event_lock:
                events.append(message)

        try:
            session = self._ensure_session()
            asset = {'search': 'contact_query_agent.js', 'messages': 'message_list_agent.js',
                     'send': 'send_text_agent.js', 'media': 'media_send_agent.js', 'group': 'group_agent.js', 'mention': 'mention_agent.js',
                     'friend_profile': 'friend_profile_agent.js', 'friend_remark': 'friend_remark_agent.js',
                     'friend_request': 'friend_request_agent.js', 'emoji_query': 'emoji_query_agent.js', 'emoji_send': 'emoji_send_agent.js',
                     'moments_read': 'moments_read_agent.js', 'moments_publish': 'moments_publish_agent.js'}[mode]
            assets = files('weskill').joinpath('assets')
            bridge = self._resources.ensure_bridge(session)
            self._resources.reap()
            bridge.on('message', on_message)
            bridge_handler_attached = True
            before = self._rpc(bridge, 'bridge_status')
            initial_invokes = int(before['invokes'])
            initial_noops = int(before['noopRuns'])
            source = assets.joinpath(asset).read_text()
            script = self._resources.create_agent(session, source)
            script.on('message', on_message)
            script.load()
            if self._rpc(bridge, 'submit_task', None) != 0:
                raise RuntimeError('Executor no-op submission rejected')
            noop = self._wait_idle(bridge, initial_invokes + 1)
            if int(noop.get('noopRuns', 0)) != initial_noops + 1 or int(noop['tid']) <= 0:
                raise RuntimeError('Executor no-op did not identify one native thread')
            with event_lock:
                noops = [m.get('payload', {}) for m in events if m.get('type') == 'send'
                         and m.get('payload', {}).get('kind') == 'executor_noop']
            if len(noops) != 1 or noops[0].get('tid') != int(noop['tid']):
                raise RuntimeError('Executor TID evidence differs')
            tid = int(noop['tid'])
            if mode in ('search', 'messages', 'media', 'group', 'friend_profile', 'friend_remark', 'friend_request', 'emoji_query', 'emoji_send', 'moments_read', 'moments_publish'):
                task = self._rpc(script, 'prepare', tid, parameters)
            elif mode == 'mention':
                task = self._rpc(script, 'prepare', tid, parameters['group_id'], parameters['text'],
                                 parameters['at_user_list'])
            else:
                task = self._rpc(script, 'prepare', tid, parameters['recipient'], parameters['text'])
            self._verify_binding()
            # RPC failure after this point cannot prove absence of submission.
            submission_possible = True
            if self._rpc(bridge, 'submit_task', task) != 0:
                submission_possible = False  # Native shim returned before post.
                raise RuntimeError('Native task submission rejected; no retry')
            executor = self._wait_idle(bridge, initial_invokes + 2)
            if executor['tid'] != noop['tid']:
                raise RuntimeError('Executor task ran on a different thread')
            deadline = time.monotonic() + self.timeout_seconds
            while time.monotonic() < deadline:
                state = self._rpc(script, 'status')
                if state.get('completed') and (mode in ('send', 'media', 'mention') or state.get('destroyed')):
                    break
                if state.get('errors'):
                    break
                time.sleep(0.05)
            response['agent_state'] = state
            with event_lock:
                kind = {'search': 'contact_query_result', 'messages': 'message_list_result',
                        'send': 'text_send_result', 'media': 'media_send_result', 'group': 'group_result', 'mention': 'text_send_result',
                        'friend_profile': 'friend_profile_result', 'friend_remark': 'friend_remark_result',
                        'friend_request': 'friend_request_result', 'emoji_query': 'emoji_query_result', 'emoji_send': 'emoji_send_result',
                        'moments_read': 'moments_read_result', 'moments_publish': 'moments_publish_result'}[mode]
                payloads = [m.get('payload', {}) for m in events if m.get('type') == 'send'
                            and m.get('payload', {}).get('kind') == kind]
            healthy = (state and state.get('invoked') and state.get('completed')
                       and state.get('destroyed') and state.get('invocationCount') == 1
                       and state.get('completionCount') == 1 and not state.get('errors'))
            if len(payloads) == 1 and (mode in ('send', 'media', 'mention') or healthy):
                payload = payloads[0]
                # Native message ids are 64-bit JSON numbers; Python parses the
                # untouched serialization rather than Frida's rounded JS Number.
                native_result = (json.loads(payload['raw_json'])
                                 if mode in ('messages', 'media', 'send', 'mention', 'moments_publish') and payload.get('raw_json')
                                 else payload.get('result'))
                if mode == 'moments_publish' and parameters.get('images') and state.get('mediaModelTransfers') != 1:
                    native_result = {'success': False, 'submission_unknown': True,
                                     'error_message': 'Native image model transfer was not established'}
                response['result'] = self._string_message_ids(native_result)
                response['errors'] = [payload['error']] if payload.get('error') else []
                if isinstance(native_result, dict) and native_result.get('not_submitted') is True:
                    response['status'] = 'not_submitted'
                    response['errors'] = [native_result.get('error_message', 'Native operation was not submitted')]
                elif isinstance(native_result, dict) and native_result.get('submission_unknown'):
                    response['status'] = 'unknown'
                    response['errors'] = [native_result.get('error_message', 'Native completion not established')]
                elif (not payload.get('error') and isinstance(native_result, dict)
                        and native_result.get('success') is True):
                    response['status'] = ('unknown' if mode == 'mention' and
                                          (state.get('mentionAppliedCount') != 1 or state.get('errors'))
                                          else 'client_success')
                    if response['status'] == 'unknown':
                        response['errors'] = state.get('errors') or ['Native mention metadata application not established']
                else:
                    response['status'] = 'client_error'
            else:
                response['status'] = 'unknown'
                response['errors'] = (state or {}).get('errors') or ['Native completion not established']
        except Exception as error:
            response['status'] = 'unknown' if submission_possible else 'not_submitted'
            response['errors'].append(f'{type(error).__name__}: {error}')
            response['failure_stage'] = self._phase
            response['error_code'] = ('connection_timeout' if isinstance(error, NativeConnectionTimeout)
                                      else 'operation_cancelled' if type(error).__name__ == 'OperationCancelledError'
                                      else 'native_operation_failed')
        finally:
            cleanup_ok = True
            if script is not None:
                if mode == 'mention':
                    try:
                        self._rpc(script, 'cleanup')
                    except Exception as error:
                        cleanup_ok = False
                        self._unsafe = 'Could not remove this request mention hook; backend is disabled'
                        response.update(status='unknown')
                        response['errors'].append(f'{self._unsafe}: {error}')
                try:
                    self._resources.finish(script, submission_possible, cleanup_ok, state)
                except Exception as error:
                    # Keep native callbacks and capture reachable after any
                    # failed lifecycle inspection; never guess they are dead.
                    if not any(item[0] is script for item in self._resources.pending):
                        self._resources.pending.append((script, cleanup_ok))
                    response.setdefault('resource_errors', []).append(f'{type(error).__name__}: {error}')
            if bridge_handler_attached:
                bridge.off('message', on_message)
            with event_lock:
                snapshot = list(events)
            response['diagnostics'] = {'connection_attempts': self.connection_attempts,
                                       'elapsed_seconds': round(time.monotonic() - started, 3),
                                       'server_pid': os.getpid(),
                                       'resources': self._resources.snapshot()}
            _save_private(journal, {'mode': mode, 'response': response, 'events': snapshot,
                                    'agent_lifetime': 'released_after_native_destroy_or_retained_while_pending'})
        return response

    def close(self):
        """Retain any uncertain native callbacks before the owning worker exits."""
        self._resources.close()

    def search_contacts(self, keywords: list[str], limit: int = 10,
                        groups_only: bool = False, sort_by_time: bool = False) -> dict:
        if (not isinstance(keywords, list) or
                any(not isinstance(x, str) or '\0' in x for x in keywords)):
            raise ValueError('Keywords must be strings without NUL')
        if type(limit) is not int or limit < 1 or type(groups_only) is not bool or type(sort_by_time) is not bool:
            raise ValueError('Search limit must be positive; filters must be boolean')
        json.dumps(keywords, ensure_ascii=False).encode('utf-8')
        with self._lock, self._ledger_lock():
            return self._run('search', {'keywords': keywords, 'limit': limit,
                            'filter_type': 2 if groups_only else 1,
                            'only_authorized': False, 'sort_by_time': sort_by_time})

    @staticmethod
    def _string_message_ids(value):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key in ('sns_id', 'moment_id') and isinstance(item, str) and item.startswith('-') and item[1:].isascii() and item[1:].isdecimal() and -(2**63) <= int(item) < 0:
                    item = int(item)
                if key in ('svr_id', 'message_id', 'sns_id', 'moment_id') and type(item) is int:
                    # SNS's JSON writer emits signed int64 while timeline IDs
                    # are uint64. Keep the same exact decimal identity in both.
                    if key in ('sns_id', 'moment_id') and -(2**63) <= item < 0:
                        item += 2**64
                    result[key] = str(item)
                else:
                    result[key] = ExperimentalBackend._string_message_ids(item)
            return result
        if isinstance(value, list):
            return [ExperimentalBackend._string_message_ids(v) for v in value]
        return value

    def get_messages(self, chat_ids: list[str], limit: int | None = 20,
                     include_xml: bool = False) -> dict:
        if not isinstance(chat_ids, list) or not chat_ids or not all(map(valid_chat_id, chat_ids)):
            raise ValueError('Expected nonempty contact/group IDs')
        if not valid_limit(limit) or type(include_xml) is not bool:
            raise ValueError('Limit must be nonnegative or null; include_xml must be boolean')
        json.dumps(chat_ids, ensure_ascii=False).encode('utf-8')
        with self._lock, self._ledger_lock():
            if limit and limit <= HISTORY_PAGE_SIZE:
                response = self._run('messages', {'chat_ids': chat_ids, 'limit': limit,
                                                 'include_xml': include_xml})
                response['result'] = self._string_message_ids(response.get('result'))
                return response
            sessions, response, page_count = [], None, 0
            for chat_id in chat_ids:
                messages, cursor, page_size, session = [], None, HISTORY_PAGE_SIZE, None
                while True:
                    if cursor is not None:
                        boundary = sum(message.get('create_time') == cursor for message in messages)
                        page_size = max(page_size, boundary + 1)
                    parameters = {'chat_ids': [chat_id], 'limit': page_size,
                                  'include_xml': include_xml}
                    if cursor is not None:
                        parameters['end_time'] = cursor
                    page = self._run('messages', parameters)
                    page_count += 1
                    page['result'] = self._string_message_ids(page.get('result'))
                    if page['status'] != 'client_success':
                        return page
                    if response is None:
                        response = page
                    returned = (page.get('result') or {}).get('sessions', [])
                    current = next((item for item in returned if item.get('chat_id') == chat_id), None)
                    if current is None:
                        break
                    if session is None:
                        session = dict(current)
                    older = current.get('messages', [])
                    # Native pages are chronological. Preserve repeated equal messages
                    # by merging sequence overlap rather than deduplicating by content.
                    overlap = 0
                    for count in range(min(len(older), len(messages)), 0, -1):
                        if older[-count:] == messages[:count]:
                            overlap = count
                            break
                    messages = older[:len(older) - overlap] + messages
                    if limit and len(messages) >= limit:
                        messages = messages[-limit:]
                        break
                    if len(older) < page_size or not older:
                        break
                    oldest = older[0].get('create_time')
                    if type(oldest) is not int:
                        raise ValueError('History page has no usable timestamp cursor')
                    # Overlap the boundary second. A crowded boundary is fetched in
                    # a larger finite page so equal timestamps cannot drop messages.
                    page_size = page_size * 2 if cursor == oldest else HISTORY_PAGE_SIZE
                    cursor = oldest
                if session is not None:
                    session['messages'] = messages
                    sessions.append(session)
            if response is None:
                raise RuntimeError('No history response')
            response['result']['sessions'] = sessions
            response['history'] = {'requested_limit': limit, 'all_records': not bool(limit),
                                   'pages': page_count}
            return response

    def send_text(self, recipient: str, text: str, idempotency_key: str) -> dict:
        if not valid_chat_id(recipient):
            raise ValueError('Expected an explicit contact/group id')
        recipient.encode('utf-8')
        if not isinstance(text, str) or not text.strip() or '\0' in text:
            raise ValueError('Text must be nonempty and without NUL')
        text.encode('utf-8')
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise ValueError('A nonempty idempotency key is required')
        path = self.state_dir / ('send-' + hashlib.sha256(idempotency_key.encode()).hexdigest() + '.json')
        with self._lock, self._ledger_lock():
            if path.exists():
                record = json.loads(path.read_text())
                if (record.get('kind', 'text') != 'text' or
                        record['recipient'] != recipient or record['text'] != text):
                    raise ValueError('Idempotency key already belongs to different recipient/text')
                if record['response']['status'] != 'not_submitted':
                    return record['response']
            response = {'status': 'unknown', 'result': None, 'delivery_confirmed': False,
                        'recipient': recipient, 'idempotency_key': idempotency_key,
                        'retry_allowed': False, 'errors': []}
            record = {'recipient': recipient, 'text': text, 'response': response}
            # Crash, cancellation or write failure must never permit a retry.
            _save_private(path, record)
            try:
                outcome = self._run('send', {'recipient': recipient, 'text': text})
                response.update(outcome)
                response['retry_allowed'] = response['status'] == 'not_submitted'
            except Exception as error:
                response['errors'].append(f'{type(error).__name__}: {error}')
            _save_private(path, record)
            return response

    def send_image(self, recipient: str, file_path: str, idempotency_key: str) -> dict:
        return self._send_media('image', recipient, file_path, idempotency_key)

    def send_file(self, recipient: str, file_path: str, idempotency_key: str) -> dict:
        return self._send_media('file', recipient, file_path, idempotency_key)

    def _send_media(self, kind, recipient, file_path, idempotency_key):
        from .media import file_identity, prepare_media
        if not valid_chat_id(recipient):
            raise ValueError('Expected an explicit contact/group ID')
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise ValueError('A nonempty idempotency key is required')
        recipient.encode('utf-8')
        source = Path(file_path).expanduser().resolve()
        key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
        ledger = self.state_dir / ('send-' + key_hash + '.json')
        with self._lock, self._ledger_lock():
            if ledger.exists():
                old = json.loads(ledger.read_text())
                if (old.get('kind') != kind or old['recipient'] != recipient or
                        old['source']['path'] != str(source)):
                    raise ValueError('Idempotency key already belongs to a different operation')
                if source.is_file() and file_identity(source)['sha256'] != old['source']['sha256']:
                    raise ValueError('Source file changed for this idempotency key')
                if old['response']['status'] != 'not_submitted':
                    return old['response']
            identity = file_identity(source)
            response = {'status': 'unknown', 'result': None, 'delivery_confirmed': False,
                        'recipient': recipient, 'idempotency_key': idempotency_key,
                        'retry_allowed': False, 'media_kind': kind, 'file_name': identity['name'],
                        'file_size': identity['size'], 'errors': []}
            record = {'kind': kind, 'recipient': recipient, 'source': identity, 'response': response}
            _save_private(ledger, record)
            submission_possible = False
            try:
                prepared = prepare_media(self.pid, kind, recipient, source, key_hash,
                                         expected_sha256=identity['sha256'])
                record['cache_path'] = prepared['cache_path']
                response['file_name'] = prepared['file_name']
                _save_private(ledger, record)
                submission_possible = True
                response.update(self._run('media', prepared['parameters']))
            except Exception as error:
                response.update(status='unknown' if submission_possible else 'not_submitted',
                                errors=[f'{type(error).__name__}: {error}'])
            response['retry_allowed'] = response['status'] == 'not_submitted'
            _save_private(ledger, record)
            return response

    def _sticker_query(self, parameters):
        from .stickers import remember_stickers
        response = self._run('emoji_query', parameters)
        if response['status'] == 'client_success':
            remember_stickers(self.state_dir, response['result'], parameters)
        return response

    def list_saved_stickers(self, limit: int | None = 20, offset: int = 0) -> dict:
        if not valid_limit(limit) or type(offset) is not int or offset < 0:
            raise ValueError('Expected a nonnegative limit and offset')
        with self._lock, self._ledger_lock():
            return self._sticker_query({'operation': 'list_saved_stickers',
                                        'limit': limit, 'offset': offset})

    def search_stickers(self, keyword: str, limit: int | None = 20,
                        cursor: str | None = None) -> dict:
        from .stickers import search_stickers
        if not valid_chat_id(keyword) or not valid_limit(limit):
            raise ValueError('Expected a keyword and nonnegative limit')
        keyword.encode('utf-8')
        with self._lock, self._ledger_lock():
            return search_stickers(self._sticker_query, self.state_dir, keyword, limit, cursor)

    def send_sticker(self, recipient: str, sticker_id: str, source: str,
                     idempotency_key: str) -> dict:
        from .stickers import selected_parameters, wait_for_material
        if not valid_chat_id(recipient) or not valid_chat_id(sticker_id) or source not in ('saved', 'search'):
            raise ValueError('Expected recipient ID, selected sticker ID and saved/search source')
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise ValueError('A nonempty idempotency key is required')
        recipient.encode('utf-8')
        sticker_id.encode('utf-8')
        parameters = {'recipient': recipient, 'sticker_id': sticker_id, 'source': source}
        ledger = self.state_dir / ('send-' + hashlib.sha256(idempotency_key.encode()).hexdigest() + '.json')
        with self._lock, self._ledger_lock():
            if ledger.exists():
                old = json.loads(ledger.read_text())
                if old.get('kind') != 'sticker' or old.get('parameters') != parameters:
                    raise ValueError('Idempotency key already belongs to a different operation')
                if old['response']['status'] != 'not_submitted':
                    return old['response']
            response = {'status': 'not_submitted', 'result': None, 'idempotency_key': idempotency_key,
                        'retry_allowed': True, 'delivery_confirmed': False, 'errors': []}
            record = {'kind': 'sticker', 'parameters': parameters, 'response': response}
            _save_private(ledger, record)
            submitted = False
            try:
                prepared = {'parameters': selected_parameters(self.state_dir, recipient, sticker_id, source)}
                mode = 'emoji_send'
                record['media'] = prepared
                response.update(status='unknown', retry_allowed=False)
                _save_private(ledger, record)
                submitted = True
                response.update(self._run(mode, prepared['parameters']))
                pending = response.get('result') or {}
                if response['status'] == 'not_submitted' and pending.get('material_pending'):
                    # This first task only queued material, before MessageManager.
                    # Its explicit not_submitted status permits the actual send
                    # after the client cache becomes ready. Never retry unknown.
                    submitted = False
                    _save_private(ledger, record)
                    if wait_for_material(pending.get('expected_local_path'), self.timeout_seconds):
                        response.update(status='unknown', retry_allowed=False)
                        _save_private(ledger, record)
                        submitted = True
                        response.update(self._run(mode, prepared['parameters']))
            except Exception as error:
                response.update(status='unknown' if submitted else 'not_submitted',
                                errors=[f'{type(error).__name__}: {error}'])
            response['retry_allowed'] = response['status'] == 'not_submitted'
            _save_private(ledger, record)
            return response

    def get_moments(self, limit: int | None = 20, cursor: str | None = None,
                    contact_id: str | None = None, include_xml: bool = False) -> dict:
        from .moments import read_moments
        if not valid_limit(limit) or type(include_xml) is not bool:
            raise ValueError('Expected a nonnegative limit and boolean include_xml')
        if contact_id is not None and not valid_chat_id(contact_id):
            raise ValueError('Expected a contact ID')
        if contact_id is not None:
            contact_id.encode('utf-8')
        with self._lock, self._ledger_lock():
            return read_moments(self._run, limit, cursor, contact_id, include_xml)

    def publish_moments(self, content: str, visibility: str, idempotency_key: str,
                        image_paths: list[str] | None = None) -> dict:
        from .media import file_identity, _cache_root, _month
        from .moments import prepare_images
        if not isinstance(content, str) or '\0' in content or visibility not in ('public', 'private'):
            raise ValueError('Expected content and explicit public/private visibility')
        if image_paths is None:
            image_paths = []
        if not isinstance(image_paths, list) or not all(isinstance(p, str) and p for p in image_paths):
            raise ValueError('Expected local image paths')
        if not content and not image_paths:
            raise ValueError('Expected content or images')
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise ValueError('A nonempty idempotency key is required')
        content.encode('utf-8')
        paths = [str(Path(path).expanduser().resolve()) for path in image_paths]
        parameters = {'content': content, 'visibility': visibility, 'image_paths': paths}
        ledger = self.state_dir / ('send-' + hashlib.sha256(idempotency_key.encode()).hexdigest() + '.json')
        with self._lock, self._ledger_lock():
            if ledger.exists():
                old = json.loads(ledger.read_text())
                if old.get('kind') != 'moments' or old.get('parameters') != parameters:
                    raise ValueError('Idempotency key already belongs to a different operation')
                for path, previous in zip(paths if 'sources' in old else [], old.get('sources', []), strict=True):
                    if Path(path).is_file() and file_identity(path)['sha256'] != previous['sha256']:
                        raise ValueError('Source image changed for this idempotency key')
                if old['response']['status'] != 'not_submitted':
                    return self._string_message_ids(old['response'])
            response = {'status': 'not_submitted', 'result': None, 'idempotency_key': idempotency_key,
                        'retry_allowed': True, 'delivery_confirmed': False, 'errors': []}
            record = {'kind': 'moments', 'parameters': parameters, 'response': response}
            submitted = False
            try:
                sources = [file_identity(path) for path in paths]
                record['sources'] = sources
                _save_private(ledger, record)
                images = prepare_images(paths, _cache_root(self.pid) / _month(), idempotency_key, sources) if paths else []
                response.update(status='unknown', retry_allowed=False)
                _save_private(ledger, record)
                submitted = True
                response.update(self._run('moments_publish', {'content': content,
                    'visibility': visibility, 'images': images}))
            except Exception as error:
                response.update(status='unknown' if submitted else 'not_submitted',
                                errors=[f'{type(error).__name__}: {error}'])
            response['retry_allowed'] = response['status'] == 'not_submitted'
            _save_private(ledger, record)
            return response

    def get_friend_info(self, contact_ids: list[str]) -> dict:
        self._validate_member_ids(contact_ids)
        with self._lock, self._ledger_lock():
            return self._run('friend_profile', {'contact_ids': contact_ids})

    def list_friend_requests(self, limit: int | None = 20, offset: int = 0) -> dict:
        if not valid_limit(limit) or type(offset) is not int or offset < 0:
            raise ValueError('Expected a nonnegative offset and limit (0/null reads all)')
        with self._lock, self._ledger_lock():
            return self._run('friend_request', {'operation': 'list_friend_requests',
                'limit': limit, 'offset': offset})

    def search_new_contact(self, query: str) -> dict:
        if not valid_chat_id(query):
            raise ValueError('Expected a nonempty WeChat search identifier')
        query.encode('utf-8')
        with self._lock, self._ledger_lock():
            return self._run('friend_request', {'operation': 'search_new_contact', 'query': query})

    def add_friend(self, query: str, idempotency_key: str, greeting: str = '', remark: str = '') -> dict:
        if not valid_chat_id(query):
            raise ValueError('Expected a nonempty WeChat search identifier')
        for text in (query, greeting, remark):
            if not isinstance(text, str) or '\0' in text:
                raise ValueError('Expected text without NUL')
            text.encode('utf-8')
        return self._operation_write('friend_request', {'operation': 'add_friend',
            'query': query, 'greeting': greeting, 'remark': remark}, idempotency_key)

    def accept_friend_request(self, request_id: str, idempotency_key: str,
                              remark: str | None = None) -> dict:
        if not valid_chat_id(request_id):
            raise ValueError('Expected an actual friend-request ID from list_friend_requests')
        request_id.encode('utf-8')
        if remark is not None:
            if not isinstance(remark, str) or '\0' in remark:
                raise ValueError('Expected a remark without NUL')
            remark.encode('utf-8')
        return self._operation_write('friend_request', {'operation': 'accept_friend_request',
            'request_id': request_id, 'remark': remark}, idempotency_key)

    def set_contact_remark(self, contact_id: str, remark: str, idempotency_key: str) -> dict:
        self._validate_member_ids([contact_id])
        if not isinstance(remark, str) or '\0' in remark:
            raise ValueError('Expected a remark without NUL')
        remark.encode('utf-8')
        return self._operation_write('friend_remark', {'operation': 'set_contact_remark',
            'contact_id': contact_id, 'remark': remark}, idempotency_key)

    def get_group_members(self, group_id: str, refresh: bool = True) -> dict:
        self._validate_group_id(group_id)
        if type(refresh) is not bool:
            raise ValueError('Expected a boolean refresh')
        with self._lock:
            response = self._group_read({'operation': 'get_group_members', 'group_id': group_id, 'refresh': refresh})
            result = response.get('result') or {}
            members = result.get('members') or []
            if response.get('status') != 'client_success' or not members:
                return response
            profiles = self.get_friend_info([member['member_id'] for member in members])
            by_id = {p['contact_id']: p for p in (profiles.get('result') or {}).get('contacts', [])}
            result = dict(result, profiles_status=profiles.get('status'), profiles_errors=profiles.get('errors', []))
            result['members'] = []
            for original in members:
                member = dict(original)
                profile = by_id.get(member['member_id'])
                member['profile'] = profile
                if profile is not None:
                    for field in ('nickname', 'remark', 'alias', 'avatar_url'):
                        if field in profile:
                            member[field] = profile[field]
                member['display_name'] = (member.get('group_nickname') or member.get('remark') or
                                          member.get('nickname') or member['member_id'])
                result['members'].append(member)
            return dict(response, result=result)

    def get_group_info(self, group_id: str, refresh: bool = True) -> dict:
        self._validate_group_id(group_id)
        if type(refresh) is not bool:
            raise ValueError('Expected a boolean refresh')
        return self._group_read({'operation': 'get_group_info', 'group_id': group_id, 'refresh': refresh})

    @staticmethod
    def _validate_group_id(group_id):
        if not valid_chat_id(group_id) or not group_id.endswith('@chatroom'):
            raise ValueError('Expected an explicit group ID')
        group_id.encode('utf-8')

    @staticmethod
    def _validate_member_ids(member_ids):
        if not isinstance(member_ids, list) or not member_ids:
            raise ValueError('Expected a nonempty list of member IDs')
        for member in member_ids:
            if not valid_chat_id(member):
                raise ValueError('Expected explicit member IDs')
            member.encode('utf-8')

    def create_group(self, member_ids: list[str], name: str, idempotency_key: str) -> dict:
        self._validate_member_ids(member_ids)
        if not isinstance(name, str) or '\0' in name:
            raise ValueError('Expected a group name without NUL')
        name.encode('utf-8')
        return self._group_write({'operation': 'create_group', 'member_ids': member_ids,
                                  'name': name}, idempotency_key)

    def invite_group_members(self, group_id: str, member_ids: list[str], idempotency_key: str,
                             mode: str = 'invite') -> dict:
        self._validate_group_id(group_id)
        self._validate_member_ids(member_ids)
        if mode not in ('add', 'invite'):
            raise ValueError('Expected add or invite mode')
        return self._group_write({'operation': 'invite_group_members', 'group_id': group_id,
                                  'member_ids': member_ids, 'mode': mode}, idempotency_key)

    def remove_group_members(self, group_id: str, member_ids: list[str], idempotency_key: str) -> dict:
        self._validate_group_id(group_id)
        self._validate_member_ids(member_ids)
        return self._group_write({'operation': 'remove_group_members', 'group_id': group_id,
                                  'member_ids': member_ids}, idempotency_key)

    def _group_write(self, parameters, idempotency_key):
        return self._operation_write('group', parameters, idempotency_key)

    def _operation_write(self, native_mode, parameters, idempotency_key):
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise ValueError('A nonempty idempotency key is required')
        ledger = self.state_dir / ('send-' + hashlib.sha256(idempotency_key.encode()).hexdigest() + '.json')
        with self._lock, self._ledger_lock():
            if ledger.exists():
                old = json.loads(ledger.read_text())
                if old.get('kind') != native_mode or old.get('parameters') != parameters:
                    raise ValueError('Idempotency key already belongs to a different operation')
                if old['response']['status'] != 'not_submitted':
                    return old['response']
            response = {'status': 'unknown', 'result': None, 'delivery_confirmed': False,
                        'idempotency_key': idempotency_key, 'retry_allowed': False, 'errors': []}
            record = {'kind': native_mode, 'parameters': parameters, 'response': response}
            if native_mode == 'group' and parameters['operation'] == 'remove_group_members':
                try:
                    membership = self._run('group', {'operation': 'get_group_members',
                        'group_id': parameters['group_id'], 'refresh': True})
                except Exception as error:
                    membership = {'status': 'unknown', 'result': None,
                                  'errors': [f'{type(error).__name__}: {error}']}
                role = (membership.get('result') or {}).get('self_role')
                allowed_roles = ('owner', 'admin')
                if membership.get('status') != 'client_success' or role not in allowed_roles:
                    denied = membership.get('status') == 'client_success' and role in ('owner', 'admin', 'member')
                    required_role = 'the group owner or an administrator'
                    response.update(status='not_submitted', retry_allowed=True,
                        error_code='group_permission_denied' if denied else 'group_role_unavailable',
                        result={'group_id': parameters['group_id'], 'self_role': role},
                        errors=[f'This account must be {required_role}' if denied
                                else f'Could not establish this account as {required_role}']
                               + membership.get('errors', []))
                    _save_private(ledger, record)
                    return response
            _save_private(ledger, record)
            try:
                response.update(self._run('mention' if parameters['operation'] == 'send_group_mention'
                                          else native_mode, parameters))
            except Exception as error:
                response['errors'].append(f'{type(error).__name__}: {error}')
            response['retry_allowed'] = response['status'] == 'not_submitted'
            _save_private(ledger, record)
            return response

    def preview_group_announcement(self, group_id: str, text: str) -> dict:
        self._validate_group_id(group_id)
        parameters = self._announcement_parameters(group_id, text, 'preview')
        parameters['operation'] = 'preview_group_announcement'
        return self._group_read(parameters)

    @staticmethod
    def _announcement_parameters(group_id, text, key):
        from xml.sax.saxutils import escape
        if not isinstance(text, str) or '\0' in text:
            raise ValueError('Expected announcement text without NUL')
        text.encode('utf-8')
        token = hashlib.sha256(key.encode()).hexdigest()
        xml = ('<group_notice_item><source><tousr>' + escape(group_id) + '</tousr></source>'
               '<datalist count="1"><dataitem datatype="1" dataid="' + token + '">'
               '<datadesc>' + escape(text) + '</datadesc></dataitem></datalist></group_notice_item>')
        return {'operation': 'set_group_announcement', 'group_id': group_id,
                'text': text, 'xml': xml, 'clear': text == ''}

    def set_group_announcement(self, group_id: str, text: str, idempotency_key: str) -> dict:
        self._validate_group_id(group_id)
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise ValueError('A nonempty idempotency key is required')
        return self._group_write(self._announcement_parameters(group_id, text, idempotency_key),
                                 idempotency_key)

    def send_group_mention(self, group_id: str, text: str, member_ids: list[str],
                           idempotency_key: str, mention_all: bool = False) -> dict:
        self._validate_group_id(group_id)
        if not isinstance(text, str) or not text.strip() or '\0' in text:
            raise ValueError('Expected nonempty mention text without NUL')
        text.encode('utf-8')
        if type(mention_all) is not bool:
            raise ValueError('Expected a boolean mention_all')
        if not isinstance(member_ids, list) or not member_ids and not mention_all:
            raise ValueError('Expected member IDs or mention_all')
        if member_ids:
            self._validate_member_ids(member_ids)
        parameters = {'operation': 'send_group_mention', 'group_id': group_id, 'text': text,
                      'at_user_list': ','.join(member_ids + (['notify@all'] if mention_all else []))}
        return self._group_write(parameters, idempotency_key)

    @staticmethod
    def _server_message_id(message_id):
        if not isinstance(message_id, str) or not message_id.isascii() or not message_id.isdecimal():
            raise ValueError('Expected a decimal server message ID string')
        value = int(message_id)
        if not 0 < value < 2**64:
            raise ValueError('Server message ID must fit a native unsigned 64-bit field')
        return str(value)

    def preview_group_pin(self, group_id: str, message_id: str) -> dict:
        self._validate_group_id(group_id)
        return self._group_read({'operation': 'preview_group_pin', 'group_id': group_id,
                                   'message_id': self._server_message_id(message_id), 'pinned': True})

    def pin_group_message(self, group_id: str, message_id: str, idempotency_key: str,
                          pinned: bool = True) -> dict:
        self._validate_group_id(group_id)
        if type(pinned) is not bool:
            raise ValueError('Expected a boolean pinned')
        return self._group_write({'operation': 'pin_group_message', 'group_id': group_id,
            'message_id': self._server_message_id(message_id), 'pinned': pinned}, idempotency_key)

    def _group_read(self, parameters):
        with self._lock, self._ledger_lock():
            return self._run('group', parameters)

    def set_group_invitation_confirmation(self, group_id: str, enabled: bool,
                                           idempotency_key: str) -> dict:
        self._validate_group_id(group_id)
        if type(enabled) is not bool:
            raise ValueError('Expected a boolean enabled')
        def varint(value):
            output = bytearray()
            while value > 127:
                output.append((value & 127) | 128)
                value >>= 7
            output.append(value)
            return bytes(output)
        name = group_id.encode('utf-8')
        # ModChatRoomAccessVerify payload: room=field1, status=field2; oplog66.
        payload = b'\x0a' + varint(len(name)) + name + b'\x10' + varint(2 if enabled else 0)
        return self._group_write({'operation': 'set_group_invitation_confirmation',
            'group_id': group_id, 'enabled': enabled, 'payload_hex': payload.hex()}, idempotency_key)
