"""Media ledger regression tests; no WeChat calls."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_backend import StandinBackend, CONTACT


class MediaLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'own.txt'
        self.source.write_text('own fixture')
        self.backend = StandinBackend(self.root / 'ledger')
        self.preparation = patch('weskill.media.prepare_media', return_value={
            'parameters': {'chat_id': CONTACT, 'message_type': 49, 'content_xml': '<msg/>'},
            'cache_path': str(self.root / 'cache'), 'file_name': 'own.txt'})
        self.prepare = self.preparation.start()
        self.addCleanup(self.preparation.stop)

    def test_media_success_replays_after_restart_and_source_removal(self):
        result = self.backend.send_file(CONTACT, self.source, 'same')
        self.source.unlink()
        other = StandinBackend(self.root / 'ledger')
        self.assertEqual(other.send_file(CONTACT, self.source, 'same'), result)
        self.assertEqual(len(self.backend.calls), 1)
        self.assertEqual(other.calls, [])
        self.assertEqual(result['status'], 'client_success')
        self.assertEqual(result['file_size'], 11)

    def test_unknown_does_not_resend(self):
        self.backend.outcome = TimeoutError('pending')
        result = self.backend.send_image(CONTACT, self.source, 'unknown')
        self.assertEqual(result['status'], 'unknown')
        self.assertFalse(result['retry_allowed'])
        self.assertEqual(self.backend.send_image(CONTACT, self.source, 'unknown'), result)
        self.assertEqual(len(self.backend.calls), 1)

    def test_preparation_failure_allows_explicit_retry(self):
        self.prepare.side_effect = RuntimeError('not logged in')
        first = self.backend.send_file(CONTACT, self.source, 'retry')
        self.assertEqual(first['status'], 'not_submitted')
        self.assertTrue(first['retry_allowed'])
        self.assertEqual(self.backend.calls, [])
        self.prepare.side_effect = None
        self.assertEqual(self.backend.send_file(CONTACT, self.source, 'retry')['status'], 'client_success')
        self.assertEqual(len(self.backend.calls), 1)

    def test_changed_bytes_and_cross_kind_keys_rejected(self):
        self.backend.send_file(CONTACT, self.source, 'bound')
        with self.assertRaises(ValueError):
            self.backend.send_image(CONTACT, self.source, 'bound')
        with self.assertRaises(ValueError):
            self.backend.send_text(CONTACT, 'text', 'bound')
        self.source.write_text('changed')
        with self.assertRaises(ValueError):
            self.backend.send_file(CONTACT, self.source, 'bound')
        self.backend.send_text(CONTACT, 'text', 'text-key')
        with self.assertRaises(ValueError):
            self.backend.send_file(CONTACT, self.source, 'text-key')
        self.assertEqual(len(self.backend.calls), 2)

    def test_uint64_message_ids_are_strings(self):
        value = 18446744073709551610
        self.assertEqual(self.backend._string_message_ids({'message_id': value}), {'message_id': str(value)})
