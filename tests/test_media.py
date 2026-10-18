"""Filesystem fixtures only: no real WeChat account, process, or business calls."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from weskill.media import _cache_root, file_identity, prepare_media


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = self.root / 'account' / 'cache'
        self.cache.mkdir(parents=True)
        self.source = self.root / 'report.txt'
        self.source.write_bytes(b'own fixture bytes\n')

    def prepare(self, kind='file', path=None, token='unique-token', expected=None):
        with patch('weskill.media._cache_root', return_value=self.cache), \
                patch('weskill.media._month', return_value='2026-10'):
            return prepare_media(123, kind, 'fixture-contact', path or self.source,
                                 token, expected)

    def test_identity_is_absolute_and_hashes_the_local_bytes(self):
        identity = file_identity(self.source)
        self.assertEqual(identity['path'], str(self.source.resolve()))
        self.assertEqual(identity['name'], 'report.txt')
        self.assertEqual(identity['size'], len(self.source.read_bytes()))
        self.assertEqual(identity['sha256'], hashlib.sha256(self.source.read_bytes()).hexdigest())

    def test_image_matches_raw_url_md5_and_keeps_staged_bytes_private(self):
        result = self.prepare(kind='image', token='one/token')
        url = 'https://weskill.invalid/local/one%2Ftoken.png'
        self.assertEqual(result['parameters'], {
            'chat_id': 'fixture-contact', 'message_type': 3, 'content_xml': url})
        cached = Path(result['cache_path'])
        self.assertEqual(cached, self.cache / '2026-10' / 'HttpResource' /
                         hashlib.md5(url.encode()).hexdigest())
        self.assertEqual(cached.read_bytes(), self.source.read_bytes())
        self.assertEqual(cached.stat().st_mode & 0o777, 0o600)
        self.assertEqual(cached.parent.stat().st_mode & 0o777, 0o700)

    def test_file_title_is_the_exact_existing_cache_basename(self):
        result = self.prepare()
        cached = Path(result['cache_path'])
        self.assertEqual(cached, self.cache / '2026-10' / 'chatbot' / 'file' / 'report.txt')
        self.assertEqual(result['file_name'], 'report.txt')
        self.assertIn('<title>report.txt</title><type>6</type>',
                      result['parameters']['content_xml'])
        self.assertEqual(cached.read_bytes(), self.source.read_bytes())

    def test_file_collision_preserves_old_bytes_and_reuses_identical_bytes(self):
        first = self.prepare()
        same = self.prepare(token='another-token')
        self.assertEqual(first['cache_path'], same['cache_path'])
        self.source.write_bytes(b'different fixture')
        changed = self.prepare()
        self.assertNotEqual(first['cache_path'], changed['cache_path'])
        self.assertEqual(Path(first['cache_path']).read_bytes(), b'own fixture bytes\n')
        self.assertEqual(Path(changed['cache_path']).read_bytes(), b'different fixture')
        self.assertEqual(self.prepare()['cache_path'], changed['cache_path'])

    def test_xml_special_characters_get_a_readable_exact_title(self):
        source = self.root / '研发<1>&".txt'
        source.write_bytes(b'own fixture')
        result = self.prepare(path=source)
        self.assertEqual(result['file_name'], '研发_1___.txt')
        self.assertIn('<title>研发_1___.txt</title>', result['parameters']['content_xml'])
        self.assertEqual(Path(result['cache_path']).name, result['file_name'])

    def test_changed_source_is_not_published(self):
        expected = file_identity(self.source)['sha256']
        self.source.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            self.prepare(expected=expected)
        self.assertEqual(list(self.cache.rglob('*.*')), [])
        self.assertEqual(list(self.cache.rglob('.weskill-*')), [])

    def test_image_key_cannot_overwrite_other_bytes(self):
        result = self.prepare(kind='image')
        self.source.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'different bytes'):
            self.prepare(kind='image')
        self.assertEqual(Path(result['cache_path']).read_bytes(), b'own fixture bytes\n')

    def test_discovery_uses_selected_process_database_fds_only(self):
        proc = self.root / 'proc'
        fds = proc / '123' / 'fd'
        fds.mkdir(parents=True)
        database = self.root / 'account' / 'db_storage' / 'message' / 'test.db'
        database.parent.mkdir(parents=True)
        database.touch()
        (fds / '1').symlink_to(database)
        (fds / '2').symlink_to(self.source)
        self.assertEqual(_cache_root(123, proc), self.cache)
        other = self.root / 'another-account' / 'db_storage' / 'test.db'
        other.parent.mkdir(parents=True)
        other.touch()
        (fds / '3').symlink_to(other)
        with self.assertRaisesRegex(RuntimeError, 'Multiple active'):
            _cache_root(123, proc)
        (fds / '1').unlink()
        (fds / '3').unlink()
        with self.assertRaisesRegex(RuntimeError, 'No active'):
            _cache_root(123, proc)

    def test_directory_source_is_rejected(self):
        with self.assertRaises((ValueError, IsADirectoryError)):
            self.prepare(path=self.root)
        self.assertEqual(list(self.cache.rglob('.weskill-*')), [])


if __name__ == '__main__':
    unittest.main()
