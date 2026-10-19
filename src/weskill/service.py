"""One same-user local service; expire after one hour without completed work."""
import argparse
import json
import os
from pathlib import Path
import socket
import socketserver
import stat
import struct
import threading
import time

from .backend import _save_private
from .worker_backend import WorkerBackend


class LocalService(socketserver.ThreadingUnixStreamServer):
    daemon_threads = False
    block_on_close = True

    def __init__(self, profile, service_dir):
        self.profile = profile
        self.service_dir = service_dir
        self.socket_path = service_dir / 'service.sock'
        self.backend = WorkerBackend(profile['pid'], profile['shim_path'], profile['state_dir'])
        self.state_lock = threading.Lock()
        self.last_request = time.monotonic()
        self.active_requests = 0
        self.stopping = False
        self.done = threading.Event()
        if self.socket_path.exists() or self.socket_path.is_symlink():
            if not stat.S_ISSOCK(self.socket_path.lstat().st_mode):
                raise ValueError('Refusing to replace a non-socket service path')
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.5)
                try:
                    probe.connect(str(self.socket_path))
                except (FileNotFoundError, ConnectionRefusedError):
                    self.socket_path.unlink(missing_ok=True)
                else:
                    raise RuntimeError('A local service is already running')
        super().__init__(str(self.socket_path), Handler)
        os.chmod(self.socket_path, 0o600)

    def snapshot(self):
        from .request_budget import NativeRequestBudget
        idle = max(0, time.monotonic() - self.last_request)
        return {'running': True, 'service_pid': os.getpid(), 'wechat_pid': self.profile['pid'],
                'active_requests': max(0, self.active_requests - 1), 'stopping': self.stopping,
                'draining_workers': self.backend.draining_workers,
                'idle_timeout_seconds': self.profile['idle_timeout_seconds'],
                'expires_in_seconds': max(0, round(self.profile['idle_timeout_seconds'] - idle, 1)),
                'native_request_budget': NativeRequestBudget().snapshot(),
                'native_connected': self.backend._worker is not None
                                    and self.backend._worker.poll() is None}

    def idle_watch(self):
        interval = min(1.0, self.profile['idle_timeout_seconds'] / 4)
        while not self.done.wait(interval):
            with self.state_lock:
                expired = (not self.active_requests and not self.backend.draining_workers and not self.stopping and
                    time.monotonic() - self.last_request >= self.profile['idle_timeout_seconds'])
                if expired:
                    self.stopping = True
            if expired:
                self.shutdown()
                return


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        server = self.server
        counted = False
        shutdown_requested = False
        self.request.settimeout(10)
        try:
            _, uid, _ = struct.unpack('3i', self.request.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
            if uid != os.getuid():
                raise PermissionError('Local service only accepts the same user')
            line = self.rfile.readline()
            if not line.endswith(b'\n'):
                raise ValueError('Invalid local request frame')
            request = json.loads(line)
            method = request['method']
            with server.state_lock:
                if server.stopping:
                    raise RuntimeError('Service is stopping; reconnect after shutdown')
                if method not in {'status', 'stop'} and request.get('profile_key') != server.profile['profile_key']:
                    raise RuntimeError('Service profile changed; stop the idle service and reconnect MCP')
                if method == 'stop':
                    if server.active_requests or server.backend.draining_workers:
                        result = {'stopped': False, 'reason': 'busy'}
                    else:
                        server.stopping = True
                        result = {'stopped': True}
                else:
                    server.active_requests += 1
                    counted = True
                    server.last_request = time.monotonic()
                    result = None
            if method in {'status', 'ensure'}:
                with server.state_lock:
                    result = server.snapshot()
            elif method != 'stop':
                if method not in {'publish_moments', 'send_sticker', 'search_stickers', 'get_moments', 'list_saved_stickers', 'search_contacts', 'get_messages', 'get_friend_info', 'list_friend_requests', 'search_new_contact', 'add_friend', 'accept_friend_request', 'set_contact_remark', 'send_text', 'send_image', 'send_file', 'get_group_members', 'get_group_info', 'create_group', 'invite_group_members', 'remove_group_members', 'preview_group_announcement', 'set_group_announcement', 'send_group_mention', 'preview_group_pin', 'pin_group_message', 'set_group_invitation_confirmation'}:
                    raise ValueError('Unsupported local service method')
                result = getattr(server.backend, method)(**request['arguments'])
            response = {'result': result}
            shutdown_requested = method == 'stop' and result.get('stopped')
        except Exception as error:
            response = {'error': f'{type(error).__name__}: {error}'}
        finally:
            if counted:
                with server.state_lock:
                    server.active_requests -= 1
                    server.last_request = time.monotonic()
        # Publish completion before the caller can receive a response and stop.
        # server_close still waits for these non-daemon handlers to finish I/O.
        try:
            self.wfile.write(json.dumps(response, ensure_ascii=True).encode() + b'\n')
            self.wfile.flush()
        except OSError:
            pass
        finally:
            if shutdown_requested:
                threading.Thread(target=server.shutdown, daemon=True).start()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text())
    idle = profile['idle_timeout_seconds']
    if not isinstance(idle, (int, float)) or isinstance(idle, bool) or idle <= 0:
        raise ValueError('Idle timeout must be positive')
    server = LocalService(profile, args.profile.parent)
    _save_private(server.service_dir / 'service.json', {'pid': os.getpid(),
                                                       'profile_key': profile['profile_key']})
    threading.Thread(target=server.idle_watch, daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.05)
    finally:
        server.done.set()
        server.server_close()
        server.backend.close_idle_workers()
        server.socket_path.unlink(missing_ok=True)
        (server.service_dir / 'service.json').unlink(missing_ok=True)


if __name__ == '__main__':
    main()
