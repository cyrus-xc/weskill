import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from weskill.backend import ExperimentalBackend
from weskill.emoji import system_emojis
from weskill.stickers import remember_stickers, search_stickers


class StickerTests(unittest.TestCase):
    def test_system_tokens_are_client_aliases_and_no_count_cap(self):
        all_rows = system_emojis(limit=0)
        self.assertGreater(all_rows['returned'], 200)
        self.assertIn('[微笑]', [r['code'] for r in system_emojis('微笑')['emojis']])
        self.assertEqual(system_emojis(limit=None)['emojis'], all_rows['emojis'])

    def test_material_credentials_stay_in_private_record(self):
        with tempfile.TemporaryDirectory() as folder:
            result = {'stickers': [{'sticker_id': 'x', 'source': 'search', 'aes_key': 'secret', 'thumb_url': 'preview'}]}
            remember_stickers(folder, result, {'keyword': 'hello'})
            self.assertEqual(set(result['stickers'][0]), {'sticker_id', 'source', 'preview_url', 'available_locally'})
            record = next((Path(folder) / 'stickers').glob('*.json'))
            self.assertEqual(json.loads(record.read_text())['record']['aes_key'], 'secret')
            self.assertEqual(record.stat().st_mode & 0o777, 0o600)

    def test_cursor_preserves_unconsumed_native_page_without_refetch(self):
        with tempfile.TemporaryDirectory() as folder:
            query = Mock(side_effect=[{'status': 'client_success', 'result': {
                'stickers': [{'sticker_id': str(i)} for i in range(3)], 'native_cursor': 0,
                'next_native_cursor': 4, 'has_more': True}},
                {'status': 'client_success', 'result': {'stickers': [{'sticker_id': '3'}],
                    'native_cursor': 4, 'next_native_cursor': None, 'has_more': False}}])
            first = search_stickers(query, folder, 'hello', 2, None)['result']
            second = search_stickers(query, folder, 'hello', 2, first['next_cursor'])['result']
            self.assertEqual([r['sticker_id'] for r in first['stickers']], ['0', '1'])
            self.assertEqual([r['sticker_id'] for r in second['stickers']], ['2', '3'])
            self.assertFalse(second['has_more'])
            self.assertEqual(query.call_count, 2)
            self.assertEqual(query.call_args.args[0]['native_cursor'], 4)

    def test_resume_deduplicates_overlapping_native_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            query = Mock(side_effect=[{'status': 'client_success', 'result': {
                'stickers': [{'sticker_id': 'a'}, {'sticker_id': 'b'}], 'native_cursor': 0,
                'next_native_cursor': 3, 'has_more': True}},
                {'status': 'client_success', 'result': {'stickers': [{'sticker_id': 'a'}, {'sticker_id': 'c'}],
                    'native_cursor': 3, 'next_native_cursor': None, 'has_more': False}}])
            first = search_stickers(query, folder, 'hello', 2, None)['result']
            second = search_stickers(query, folder, 'hello', 2, first['next_cursor'])['result']
            self.assertEqual([row['sticker_id'] for row in second['stickers']], ['c'])
            self.assertFalse(second['has_more'])

    def test_download_preparation_can_finish_before_one_actual_send(self):
        with tempfile.TemporaryDirectory() as folder:
            remember_stickers(folder, {'stickers': [{'sticker_id': 'x', 'source': 'search'}]},
                              {'keyword': 'hello', 'native_cursor': 0})
            backend = ExperimentalBackend(123, '/tmp/unused-shim', folder)
            backend._run = Mock(side_effect=[{'status': 'not_submitted', 'result': {
                'material_pending': True, 'expected_local_path': '/tmp/native-cache'}, 'errors': []},
                {'status': 'client_success', 'result': {'success': True}, 'errors': []}])
            with patch('weskill.stickers.wait_for_material', return_value=True) as wait:
                result = backend.send_sticker('contact', 'x', 'search', 'key')
            self.assertEqual(result['status'], 'client_success')
            self.assertEqual(backend._run.call_count, 2)
            self.assertEqual({call.args[0] for call in backend._run.call_args_list}, {'emoji_send'})
            wait.assert_called_once()
            backend.send_sticker('contact', 'x', 'search', 'key')
            self.assertEqual(backend._run.call_count, 2)

    def test_unknown_is_never_replayed_even_if_payload_mentions_pending_material(self):
        with tempfile.TemporaryDirectory() as folder:
            remember_stickers(folder, {'stickers': [{'sticker_id': 'x', 'source': 'search'}]}, {'keyword': 'hello'})
            backend = ExperimentalBackend(123, '/tmp/unused-shim', folder)
            backend._run = Mock(return_value={'status': 'unknown', 'result': {'material_pending': True}, 'errors': []})
            with patch('weskill.stickers.wait_for_material') as wait:
                for _ in range(2):
                    self.assertEqual(backend.send_sticker('contact', 'x', 'search', 'key')['status'], 'unknown')
            backend._run.assert_called_once()
            wait.assert_not_called()

    def test_unknown_sticker_never_sends_and_same_key_can_retry_not_submitted(self):
        with tempfile.TemporaryDirectory() as folder:
            backend = ExperimentalBackend(123, '/tmp/unused-shim', folder)
            backend._run = Mock()
            for _ in range(2):
                result = backend.send_sticker('contact', 'missing', 'saved', 'key')
                self.assertEqual(result['status'], 'not_submitted')
                self.assertTrue(result['retry_allowed'])
            backend._run.assert_not_called()
