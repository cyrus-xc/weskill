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
    def __init__(self, pid, shim_path, state_dir, idle_timeout_seconds=3600):
        self.pid = pid
        self.shim_path = Path(shim_path).resolve()
        self.state_dir = Path(state_dir).resolve()
        self.idle_timeout_seconds = idle_timeout_seconds
        self.service_dir = self.state_dir.parent / 'service'
        self.service_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.service_dir, 0o700)
        self.socket_path = self.service_dir / 'service.sock'
        self.pid_path = self.service_dir / 'service.json'
        self.timeout_seconds = None  # History pagination has no aggregate socket deadline.
        self._profile_cache = None

    def _profile(self):
        if self._profile_cache is not None:
            return self._profile_cache
        value = {'pid': self.pid if self.pid is not None else discover_client_pid(),
                 'shim_path': str(self.shim_path), 'state_dir': str(self.state_dir),
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

    def search_contacts(self, keywords, limit=10, groups_only=False, sort_by_time=False):
        return self._call('search_contacts', {'keywords': keywords, 'limit': limit,
                                               'groups_only': groups_only, 'sort_by_time': sort_by_time})

    def get_messages(self, chat_ids, limit=20, include_xml=False):
        return self._call('get_messages', {'chat_ids': chat_ids, 'limit': limit, 'include_xml': include_xml})

    def send_text(self, recipient_id, text, idempotency_key):
        return self._call('send_text', {'recipient': recipient_id, 'text': text,
                                       'idempotency_key': idempotency_key})

    def send_image(self, recipient_id, file_path, idempotency_key):
        return self._call('send_image', {'recipient': recipient_id, 'file_path': str(file_path),
                                         'idempotency_key': idempotency_key})

    def send_file(self, recipient_id, file_path, idempotency_key):
        return self._call('send_file', {'recipient': recipient_id, 'file_path': str(file_path),
                                        'idempotency_key': idempotency_key})

    def list_saved_stickers(self, limit=20, offset=0):
        return self._call('list_saved_stickers', {'limit': limit, 'offset': offset})

    def search_stickers(self, keyword, limit=20, cursor=None):
        return self._call('search_stickers', {'keyword': keyword, 'limit': limit, 'cursor': cursor})

    def send_sticker(self, recipient_id, sticker_id, source, idempotency_key):
        return self._call('send_sticker', {'recipient': recipient_id, 'sticker_id': sticker_id,
            'source': source, 'idempotency_key': idempotency_key})

    def get_moments(self, limit=20, cursor=None, contact_id=None, include_xml=False):
        return self._call('get_moments', {'limit': limit, 'cursor': cursor,
            'contact_id': contact_id, 'include_xml': include_xml})

    def publish_moments(self, content, visibility, idempotency_key, image_paths=None):
        return self._call('publish_moments', {'content': content, 'visibility': visibility,
            'idempotency_key': idempotency_key, 'image_paths': image_paths})

    def get_friend_info(self, contact_ids):
        return self._call('get_friend_info', {'contact_ids': contact_ids})

    def list_friend_requests(self, limit=20, offset=0):
        return self._call('list_friend_requests', {'limit': limit, 'offset': offset})

    def search_new_contact(self, query):
        return self._call('search_new_contact', {'query': query})

    def add_friend(self, query, idempotency_key, greeting='', remark=''):
        return self._call('add_friend', {'query': query, 'idempotency_key': idempotency_key,
                                       'greeting': greeting, 'remark': remark})

    def accept_friend_request(self, request_id, idempotency_key, remark=None):
        return self._call('accept_friend_request', {'request_id': request_id,
            'idempotency_key': idempotency_key, 'remark': remark})

    def set_contact_remark(self, contact_id, remark, idempotency_key):
        return self._call('set_contact_remark', {'contact_id': contact_id, 'remark': remark,
                                              'idempotency_key': idempotency_key})

    def get_group_members(self, group_id, refresh=True):
        return self._call('get_group_members', {'group_id': group_id, 'refresh': refresh})

    def get_group_info(self, group_id, refresh=True):
        return self._call('get_group_info', {'group_id': group_id, 'refresh': refresh})

    def create_group(self, member_ids, name, idempotency_key):
        return self._call('create_group', {'member_ids': member_ids, 'name': name,
                                          'idempotency_key': idempotency_key})

    def invite_group_members(self, group_id, member_ids, idempotency_key, mode='invite'):
        return self._call('invite_group_members', {'group_id': group_id, 'member_ids': member_ids,
            'idempotency_key': idempotency_key, 'mode': mode})

    def remove_group_members(self, group_id, member_ids, idempotency_key):
        return self._call('remove_group_members', {'group_id': group_id, 'member_ids': member_ids,
                                                 'idempotency_key': idempotency_key})

    def preview_group_announcement(self, group_id, text):
        return self._call('preview_group_announcement', {'group_id': group_id, 'text': text})

    def set_group_announcement(self, group_id, text, idempotency_key):
        return self._call('set_group_announcement', {'group_id': group_id, 'text': text,
                                                  'idempotency_key': idempotency_key})

    def send_group_mention(self, group_id, text, member_ids, idempotency_key, mention_all=False):
        return self._call('send_group_mention', {'group_id': group_id, 'text': text,
            'member_ids': member_ids, 'idempotency_key': idempotency_key, 'mention_all': mention_all})

    def preview_group_pin(self, group_id, message_id):
        return self._call('preview_group_pin', {'group_id': group_id, 'message_id': message_id})

    def pin_group_message(self, group_id, message_id, idempotency_key, pinned=True):
        return self._call('pin_group_message', {'group_id': group_id, 'message_id': message_id,
            'idempotency_key': idempotency_key, 'pinned': pinned})

    def set_group_invitation_confirmation(self, group_id, enabled, idempotency_key):
        return self._call('set_group_invitation_confirmation', {'group_id': group_id,
            'enabled': enabled, 'idempotency_key': idempotency_key})
