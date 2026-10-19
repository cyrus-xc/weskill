"""Connection timeout recovery without real native calls or message sends."""
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from weskill.backend import ExperimentalBackend, NativeConnectionTimeout


class OperationCancelledError(Exception):
    pass


class Token:
    def __init__(self):
        self.is_cancelled = False
    def cancel(self):
        self.is_cancelled = True
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


class Timer:
    def __init__(self, delay, callback):
        self.callback = callback
        self.daemon = False
    def start(self):
        # Model the existing watchdog expiring while attachment is pending.
        self.callback()
    def cancel(self):
        pass


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.backend = ExperimentalBackend(123, '/nonexistent/fixture.so', self.tmp.name)
        self.backend._verify_binding = Mock()

    def frida(self, effects):
        device = SimpleNamespace(attach=Mock(side_effect=effects))
        value = SimpleNamespace(Cancellable=Token, OperationCancelledError=OperationCancelledError,
                                get_local_device=Mock(return_value=device))
        return value, device

    def test_watchdog_cancel_is_reported_before_business_submission(self):
        frida, device = self.frida([OperationCancelledError('operation was cancelled')])
        with patch('weskill.backend.threading.Timer', Timer):
            with self.assertRaisesRegex(TimeoutError, 'before'):
                self.backend._attach_session(frida)
        self.assertEqual(device.attach.call_count, 1)
        self.assertEqual(self.backend._scripts, [])

    def test_successful_worker_attachment_is_not_repeated(self):
        session = object()
        frida, device = self.frida([session])
        with patch('weskill.backend.threading.Timer'):
            self.assertIs(self.backend._attach_session(frida), session)
        self.assertEqual(device.attach.call_count, 1)
        self.assertEqual(self.backend.connection_attempts, 1)

    def test_external_cancellation_without_watchdog_is_not_retried(self):
        frida, device = self.frida([OperationCancelledError('external cancellation')])
        with patch('weskill.backend.threading.Timer'):
            with self.assertRaises(OperationCancelledError):
                self.backend._attach_session(frida)
        self.assertEqual(device.attach.call_count, 1)

    def test_identity_change_before_attachment_stops_connection(self):
        frida, device = self.frida([OperationCancelledError('operation was cancelled'), object()])
        self.backend._verify_binding.side_effect = ValueError('Target PID was reused')
        with patch('weskill.backend.threading.Timer', Timer):
            with self.assertRaisesRegex(ValueError, 'PID was reused'):
                self.backend._attach_session(frida)
        self.assertEqual(device.attach.call_count, 0)

    def test_permission_error_is_not_retried(self):
        frida, device = self.frida([PermissionError('ptrace denied')])
        with patch('weskill.backend.threading.Timer'):
            with self.assertRaises(PermissionError):
                self.backend._attach_session(frida)
        self.assertEqual(device.attach.call_count, 1)


    def test_exhausted_connection_allows_explicit_retry_before_submission(self):
        backend = ExperimentalBackend(123, '/nonexistent/fixture.so', self.tmp.name)
        backend._ensure_session = Mock(side_effect=NativeConnectionTimeout(
            'Native connection timed out before any business task was submitted'))
        first = backend.send_text('wxid_fixture_contact', 'fixture text', 'cancelled-connect')
        self.assertEqual(first['status'], 'not_submitted')
        self.assertEqual(first['error_code'], 'connection_timeout')
        self.assertEqual(first['failure_stage'], 'connection')
        self.assertIs(first['retry_allowed'], True)
        self.assertEqual(backend.send_text('wxid_fixture_contact', 'fixture text',
                                          'cancelled-connect'), first)
        self.assertEqual(backend._ensure_session.call_count, 2)

    def test_cancellation_at_business_submission_is_unknown_and_never_repeated(self):
        backend = ExperimentalBackend(123, '/nonexistent/fixture.so', self.tmp.name)
        backend._frida = SimpleNamespace(Cancellable=Token)
        backend._verify_binding = Mock()
        from native_standin import Session
        session = Session(submission_error=OperationCancelledError('operation was cancelled'))
        backend._ensure_session = Mock(return_value=session)
        with patch('weskill.backend.threading.Timer'):
            first = backend.send_text('wxid_fixture_contact', 'fixture text', 'during-submit')
        self.assertEqual(first['status'], 'unknown')
        self.assertEqual(first['failure_stage'], 'native.submit_task')
        self.assertEqual(session.business_submissions, 1)
        self.assertEqual(backend.send_text('wxid_fixture_contact', 'fixture text',
                                          'during-submit'), first)
        self.assertEqual(session.business_submissions, 1)
        backend._ensure_session.assert_called_once()
        self.assertEqual(len(backend._resources.pending), 1)
        backend.close()
        for script in session.scripts:
            script.eternalize.assert_called_once()
            script.unload.assert_not_called()
    def test_client_success_does_not_wait_for_callback_destruction_or_history(self):
        backend = self.backend
        from native_standin import Session
        session = Session(destroyed=False)
        backend._ensure_session = Mock(return_value=session)
        backend._frida = SimpleNamespace(Cancellable=Token)
        with patch('weskill.backend.threading.Timer'):
            result = backend.send_text('filehelper', 'fixture', 'client-success-only')
        self.assertEqual(result['status'], 'client_success')
        self.assertEqual(len(backend._resources.pending), 1)
        session.agent.unload.assert_not_called()
        session.agent.eternalize.assert_not_called()
        self.assertEqual(backend._ensure_session.call_count, 1)



if __name__ == '__main__':
    unittest.main()
