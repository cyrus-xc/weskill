"""Opt-in native experiments. Client callbacks never prove server delivery.

One session per backend; one permanently retained script per request. No native
operation runs during construction. The caller must keep this backend alive for
the lifetime of WeChat, including after timed-out requests.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import uuid

MAIN_SHA256 = '71e22a172018bf250b7b70493382bf55024727144eb7f13cf9b312cdf02e5bbc'
RECIPIENT = re.compile(r'^(wxid_[A-Za-z0-9_-]{1,128}|[1-9][0-9]{4,31}@chatroom)$')


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
    def __init__(self, pid: int, shim_path: Path | str, state_dir: Path | str,
                 allowed_recipients):
        if type(pid) is not int or pid <= 0:
            raise ValueError('Expected an explicit positive WeChat PID')
        self.pid = pid
        self.shim_path = Path(shim_path).resolve()
        self.state_dir = Path(state_dir).resolve()
        self.allowed_recipients = frozenset(allowed_recipients)
        if any(not isinstance(x, str) or not RECIPIENT.fullmatch(x)
               for x in self.allowed_recipients):
            raise ValueError('Allowlist must contain verified contact/group ids')
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.state_dir, 0o700)
        self._lock = threading.RLock()
        self._session = None
        self._binding = None
        self._scripts = []
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
                     'send': 'send_text_agent.js'}[mode]
            assets = files('weskill').joinpath('assets')
            source = assets.joinpath(asset).read_text() + '\n' + assets.joinpath('executor_bridge.js').read_text()
            script = session.create_script(source)
            self._scripts.append(script)  # Never unload or detach after task allocation.
            script.on('message', on_message)
            script.load()
            self._rpc(script, 'setup', str(self.shim_path))
            if self._rpc(script, 'submit_task', None) != 0:
                raise RuntimeError('Executor no-op submission rejected')
            noop = self._wait_idle(script, 1)
            if noop.get('noopRuns') != 1 or int(noop['tid']) <= 0:
                raise RuntimeError('Executor no-op did not identify one native thread')
            with event_lock:
                noops = [m.get('payload', {}) for m in events if m.get('type') == 'send'
                         and m.get('payload', {}).get('kind') == 'executor_noop']
            if len(noops) != 1 or noops[0].get('tid') != int(noop['tid']):
                raise RuntimeError('Executor TID evidence differs')
            tid = int(noop['tid'])
            if mode in ('search', 'messages'):
                task = self._rpc(script, 'prepare', tid, parameters)
            else:
                task = self._rpc(script, 'prepare', tid, parameters['recipient'], parameters['text'])
            self._verify_binding()
            # RPC failure after this point cannot prove absence of submission.
            submission_possible = True
            if self._rpc(script, 'submit_task', task) != 0:
                submission_possible = False  # Native shim returned before post.
                raise RuntimeError('Native task submission rejected; no retry')
            executor = self._wait_idle(script, 2)
            if executor['tid'] != noop['tid']:
                raise RuntimeError('Executor task ran on a different thread')
            deadline = time.monotonic() + self.timeout_seconds
            while time.monotonic() < deadline:
                state = self._rpc(script, 'status')
                if state.get('completed') and state.get('destroyed'):
                    break
                if state.get('errors'):
                    break
                time.sleep(0.05)
            response['agent_state'] = state
            with event_lock:
                kind = {'search': 'contact_query_result', 'messages': 'message_list_result',
                        'send': 'text_send_result'}[mode]
                payloads = [m.get('payload', {}) for m in events if m.get('type') == 'send'
                            and m.get('payload', {}).get('kind') == kind]
            healthy = (state and state.get('invoked') and state.get('completed')
                       and state.get('destroyed') and state.get('invocationCount') == 1
                       and state.get('completionCount') == 1 and not state.get('errors'))
            if healthy and len(payloads) == 1:
                payload = payloads[0]
                # Native message ids are 64-bit JSON numbers; Python parses the
                # untouched serialization rather than Frida's rounded JS Number.
                native_result = (json.loads(payload['raw_json'])
                                 if mode == 'messages' and payload.get('raw_json')
                                 else payload.get('result'))
                response['result'] = native_result
                response['errors'] = [payload['error']] if payload.get('error') else []
                if (not payload.get('error') and isinstance(native_result, dict)
                        and native_result.get('success') is True):
                    response['status'] = 'client_success'
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
            if script is not None:
                try:
                    # Frida16 destroys the RPC handle here. No RPC after this.
                    script.eternalize()
                except Exception as error:
                    # Keep both Script and Session alive even if this fails.
                    self._unsafe = 'Could not eternalize callback agent; backend is disabled'
                    response['errors'].append(f'{self._unsafe}: {error}')
            with event_lock:
                snapshot = list(events)
            response['diagnostics'] = {'connection_attempts': self.connection_attempts,
                                       'elapsed_seconds': round(time.monotonic() - started, 3),
                                       'server_pid': os.getpid()}
            _save_private(journal, {'mode': mode, 'response': response, 'events': snapshot,
                                    'agent_lifetime': 'until_wechat_exits'})
        return response

    def search_contacts(self, keywords: list[str], limit: int = 10,
                        groups_only: bool = False) -> dict:
        if (not isinstance(keywords, list) or not 1 <= len(keywords) <= 8
                or any(not isinstance(x, str) or not x.strip() or len(x) > 128 or '\0' in x
                       for x in keywords)):
            raise ValueError('Expected 1–8 nonempty keywords, each at most 128 characters')
        if type(limit) is not int or not 1 <= limit <= 50 or type(groups_only) is not bool:
            raise ValueError('Limit must be 1–50; groups_only must be boolean')
        json.dumps(keywords, ensure_ascii=False).encode('utf-8')  # Reject lone surrogates.
        with self._lock, self._ledger_lock():
            return self._run('search', {'keywords': keywords, 'limit': limit,
                            'filter_type': 2 if groups_only else 1,
                            'only_authorized': False, 'sort_by_time': False})

    def get_messages(self, chat_ids: list[str], limit: int = 10) -> dict:
        if (not isinstance(chat_ids, list) or not 1 <= len(chat_ids) <= 8
                or any(not isinstance(x, str) or not RECIPIENT.fullmatch(x) for x in chat_ids)):
            raise ValueError('Expected 1–8 explicit contact/group ids')
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError('Message limit must be 1–20')
        if any(x not in self.allowed_recipients for x in chat_ids):
            raise PermissionError('Message queries are limited to the experimental allowlist')
        with self._lock, self._ledger_lock():
            response = self._run('messages', {'chat_ids': chat_ids, 'limit': limit, 'include_xml': False})
            # Protocol consumers may be JavaScript. IDs must survive >2**53.
            def ids_as_strings(value):
                if isinstance(value, dict):
                    return {k: str(v) if k == 'svr_id' and type(v) is int else ids_as_strings(v)
                            for k, v in value.items()}
                if isinstance(value, list):
                    return [ids_as_strings(v) for v in value]
                return value
            response['result'] = ids_as_strings(response.get('result'))
            return response

    def send_text(self, recipient: str, text: str, idempotency_key: str) -> dict:
        if recipient not in self.allowed_recipients:
            raise PermissionError('Recipient is outside the explicit experimental allowlist')
        if (not isinstance(text, str) or not text.strip() or '\0' in text
                or len(text.encode('utf-16-le')) // 2 > 4096):
            raise ValueError('Text must be nonempty, without NUL, at most 4096 UTF-16 units')
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128:
            raise ValueError('An idempotency key of 1–128 characters is required')
        path = self.state_dir / ('send-' + hashlib.sha256(idempotency_key.encode()).hexdigest() + '.json')
        with self._lock, self._ledger_lock():
            if path.exists():
                record = json.loads(path.read_text())
                if record['recipient'] != recipient or record['text'] != text:
                    raise ValueError('Idempotency key already belongs to different recipient/text')
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
            except Exception as error:
                response['errors'].append(f'{type(error).__name__}: {error}')
            _save_private(path, record)
            return response
