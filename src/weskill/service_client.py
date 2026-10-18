"""Local Unix-socket adapter; native state belongs to one shared idle service."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

from .backend import _save_private
from .identity import discover_client_pid


class ServiceBackend:
    def __init__(self, pid, shim_path, state_dir, allowed_recipients, idle_timeout_seconds=3600):
        self.pid = pid
        self.shim_path = Path(shim_path).resolve()
        self.state_dir = Path(state_dir).resolve()
        self.allowed_recipients = frozenset(allowed_recipients)
        self.idle_timeout_seconds = idle_timeout_seconds
        self.service_dir = self.state_dir.parent / 'service'
        self.service_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.service_dir, 0o700)
        self.socket_path = self.service_dir / 'service.sock'
        self.pid_path = self.service_dir / 'service.json'
        self.timeout_seconds = 170.0
        self._profile_cache = None

    def _profile(self):
        if self._profile_cache is not None:
            return self._profile_cache
        value = {'pid': self.pid if self.pid is not None else discover_client_pid(),
                 'shim_path': str(self.shim_path), 'state_dir': str(self.state_dir),
                 'allowed_recipients': sorted(self.allowed_recipients),
                 'idle_timeout_seconds': self.idle_timeout_seconds}
        value['profile_key'] = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        self._profile_cache = value
        return value

    def _exchange(self, method, arguments, profile_key=None, timeout=None):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout or self.timeout_seconds)
            connection.connect(str(self.socket_path))
            connection.sendall(json.dumps({'method': method, 'arguments': arguments,
                                          'profile_key': profile_key}).encode() + b'\n')
            with connection.makefile('rb') as stream:
                line = stream.readline()
            if not line:
                raise EOFError('Local service disconnected; preserve the original idempotency key')
            value = json.loads(line)
            if value.get('error'):
                raise RuntimeError(value['error'])
            return value['result']

    def _start(self, profile):
        lock = os.open(self.service_dir / 'start.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                self._exchange('status', {}, timeout=2)
                return
            except (FileNotFoundError, ConnectionRefusedError):
                pass
            profile_path = self.service_dir / 'profile.json'
            _save_private(profile_path, profile)
            log = os.open(self.service_dir / 'service.log', os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
            try:
                process = subprocess.Popen([sys.executable, '-u', '-m', 'weskill.service',
                    '--profile', str(profile_path)], stdin=subprocess.DEVNULL, stdout=log,
                    stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
                threading.Thread(target=process.wait, daemon=True).start()
            finally:
                os.close(log)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    self._exchange('status', {}, timeout=1)
                    return
                except (FileNotFoundError, ConnectionRefusedError):
                    if process.poll() is not None:
                        raise RuntimeError('Local service could not start; inspect the private service log')
                    time.sleep(0.05)
            raise TimeoutError('Local service startup timed out')
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            os.close(lock)

    def _call(self, method, arguments):
        profile = self._profile()
        try:
            # Start/reconnect only if connect failed. Never replay an accepted request.
            return self._exchange(method, arguments, profile['profile_key'])
        except (FileNotFoundError, ConnectionRefusedError):
            self._start(profile)
            return self._exchange(method, arguments, profile['profile_key'])

    def ensure_service(self):
        return self._call('ensure', {})

    def get_service_status(self):
        try:
            return self._exchange('status', {}, timeout=3)
        except (FileNotFoundError, ConnectionRefusedError):
            return {'running': False, 'idle_timeout_seconds': self.idle_timeout_seconds}

    def stop_service(self):
        try:
            result = self._exchange('stop', {}, timeout=3)
            if result.get('stopped'):
                deadline = time.monotonic() + 7
                while self.socket_path.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                if self.socket_path.exists():
                    return {'stopped': False, 'reason': 'shutdown_pending'}
            if result.get('stopped'):
                self._profile_cache = None
            return result
        except (FileNotFoundError, ConnectionRefusedError):
            self._profile_cache = None
            return {'stopped': True, 'already_stopped': True}

    def search_contacts(self, keywords, limit=10, groups_only=False):
        return self._call('search_contacts', {'keywords': keywords, 'limit': limit,
                                               'groups_only': groups_only})

    def get_messages(self, chat_ids, limit=10):
        return self._call('get_messages', {'chat_ids': chat_ids, 'limit': limit})

    def send_text(self, recipient_id, text, idempotency_key):
        if recipient_id not in self.allowed_recipients:
            raise PermissionError('Recipient is outside the explicit allowlist')
        return self._call('send_text', {'recipient': recipient_id, 'text': text,
                                       'idempotency_key': idempotency_key})
