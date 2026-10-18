"""Same-user local lifecycle tests. Never initialize Frida or native business."""
from pathlib import Path
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace

from weskill.service import Handler, LocalService

from weskill.service_client import ServiceBackend


class ServiceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.backend = ServiceBackend(123, '/nonexistent/fixture.so', self.root / 'operations', [])
        self.addCleanup(self.cleanup)

    def cleanup(self):
        try:
            self.backend.stop_service()
        except (OSError, RuntimeError):
            pass
        deadline = time.monotonic() + 3
        while self.backend.socket_path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.tmp.cleanup()

    def test_status_does_not_start_service(self):
        self.assertFalse(self.backend.get_service_status()['running'])
        self.assertFalse(self.backend.socket_path.exists())

    def test_ensure_is_shared_and_does_not_initialize_native_worker(self):
        first = self.backend.ensure_service()
        second_client = ServiceBackend(123, '/nonexistent/fixture.so', self.root / 'operations', [])
        second = second_client.ensure_service()
        self.assertEqual(first['service_pid'], second['service_pid'])
        self.assertEqual(first['idle_timeout_seconds'], 3600)
        self.assertFalse(first['native_connected'])
        self.assertEqual(self.backend.socket_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(first['active_requests'], 0)
        self.assertTrue(self.backend.stop_service()['stopped'])

    def test_completed_response_allows_stop_before_connection_cleanup(self):
        # Receiving the completed response must make a following stop valid,
        # even if the first handler is delayed while cleaning up its socket.
        paused, release = threading.Event(), threading.Event()

        class PausedFlushHandler(Handler):
            def setup(self):
                super().setup()
                writer = self.wfile

                class PausedWriter:
                    def __getattr__(self, name):
                        return getattr(writer, name)

                    def flush(self):
                        writer.flush()
                        if not paused.is_set():
                            paused.set()
                            release.wait(2)

                self.wfile = PausedWriter()

        server = LocalService(self.backend._profile(), self.backend.service_dir)
        server.RequestHandlerClass = PausedFlushHandler
        server.backend = SimpleNamespace(draining_workers=0, _worker=None)
        serving = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
        serving.start()
        try:
            self.backend.ensure_service()
            self.assertTrue(paused.wait(1))
            self.assertEqual(self.backend._exchange('stop', {}), {'stopped': True})
        finally:
            release.set()
            server.shutdown()
            serving.join(2)
            server.server_close()
            server.socket_path.unlink(missing_ok=True)

    def test_idle_expiry_removes_service_and_next_request_restarts_it(self):
        self.backend.idle_timeout_seconds = 0.3
        first = self.backend.ensure_service()
        time.sleep(0.55)  # Status calls would deliberately renew the deadline.
        self.assertFalse(self.backend.get_service_status()['running'])
        second = self.backend.ensure_service()
        self.assertNotEqual(first['service_pid'], second['service_pid'])

    def test_new_request_renews_idle_deadline(self):
        self.backend.idle_timeout_seconds = 0.6
        first = self.backend.ensure_service()
        time.sleep(0.35)
        self.backend.get_service_status()
        time.sleep(0.35)
        self.assertEqual(self.backend.get_service_status()['service_pid'], first['service_pid'])

    def test_simultaneous_clients_start_one_service(self):
        barrier = threading.Barrier(2)
        results, failures = [], []
        def start():
            try:
                client = ServiceBackend(123, '/nonexistent/fixture.so', self.root / 'operations', [])
                barrier.wait()
                results.append(client.ensure_service()['service_pid'])
            except Exception as error:
                failures.append(error)
        threads = [threading.Thread(target=start) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(5)
        self.assertEqual(failures, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(len(set(results)), 1)


    def test_inflight_request_blocks_manual_stop_and_idle_shutdown(self):
        self.backend.idle_timeout_seconds = 0.15
        server = LocalService(self.backend._profile(), self.backend.service_dir)
        entered, release = threading.Event(), threading.Event()
        def query(**kwargs):
            entered.set()
            release.wait(2)
            return {'status': 'client_success'}
        server.backend = SimpleNamespace(search_contacts=query, draining_workers=0, _worker=None)
        serving = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
        watching = threading.Thread(target=server.idle_watch)
        result = []
        request = threading.Thread(target=lambda: result.append(
            self.backend.search_contacts(['fixture'], 1)))
        serving.start()
        watching.start()
        request.start()
        try:
            self.assertTrue(entered.wait(1))
            time.sleep(0.25)  # Longer than the idle threshold while work is active.
            self.assertTrue(self.backend.get_service_status()['running'])
            self.assertEqual(self.backend.stop_service(), {'stopped': False, 'reason': 'busy'})
            release.set()
            request.join(2)
            self.assertEqual(result, [{'status': 'client_success'}])
        finally:
            release.set()
            request.join(2)
            server.done.set()
            server.shutdown()
            serving.join(2)
            watching.join(2)
            server.server_close()
            server.socket_path.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
