"""Offline public contracts omitted by the per-feature tests; never attach WeChat."""

import json
from pathlib import Path
import shutil
import tempfile
import tomllib
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from weskill import __version__
from weskill.backend import ExperimentalBackend
from weskill.server import create_server
from weskill.stickers import remember_stickers


ROOT = Path(__file__).resolve().parents[1]


class DiscoveryContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_matches_sdk_discovery_without_starting_a_backend(self):
        for enabled in (False, True):
            with self.subTest(native_enabled=enabled):
                backend = Mock(spec=[]) if enabled else None
                server = create_server(Path('/nonexistent/fixture-client'), backend=backend)
                tools = {tool.name: tool for tool in await server.list_tools()}
                _, report = await server.call_tool('get_capabilities', {})
                self.assertEqual(set(report['available_tools']), set(tools))
                self.assertEqual(len(report['available_tools']), len(tools))
                self.assertEqual(report['business_operations_available'], enabled)
                self.assertEqual(report['toolbox_version'], __version__)
                self.assertEqual(any(item['execution_available'] for item in report['capabilities']), enabled)
                for item in report['capabilities']:
                    self.assertIn(item['status'], report['status_definitions'])
                self.assertTrue(all(item['execution_available'] is False
                                    for item in report['capabilities']
                                    if not enabled or item['id'] == 'receive_messages'))
                if backend is not None:
                    self.assertEqual(backend.mock_calls, [])

    async def test_business_write_schemas_require_a_key_and_declare_idempotency(self):
        server = create_server(Path('/nonexistent/fixture-client'), backend=object())
        writes = [tool for tool in await server.list_tools()
                  if not tool.annotations.readOnlyHint
                  and tool.name not in {'ensure_service', 'stop_service'}]
        self.assertTrue(writes)
        for tool in writes:
            with self.subTest(tool=tool.name):
                self.assertIn('idempotency_key', tool.inputSchema['required'])
                self.assertEqual(tool.inputSchema['properties']['idempotency_key']['type'], 'string')
                self.assertTrue(tool.annotations.idempotentHint)
                self.assertTrue(tool.annotations.openWorldHint)


class InterruptedSocialWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ledger = self.root / 'ledger'

    def backend(self):
        backend = ExperimentalBackend(123, '/nonexistent/fixture-shim', self.ledger)
        backend._run = Mock(side_effect=KeyboardInterrupt('interrupted after submission reservation'))
        return backend

    def test_moments_interruption_survives_restart_and_missing_source_image(self):
        image = self.root / 'own.png'
        Image.new('RGB', (8, 8), 'blue').save(image)
        first = self.backend()
        with patch('weskill.media._cache_root', return_value=self.root / 'cache'):
            with self.assertRaises(KeyboardInterrupt):
                first.publish_moments('text', 'private', 'interrupted-moment', [str(image)])
        first._run.assert_called_once()
        image.unlink()
        recovered = self.backend()
        with patch('weskill.moments.prepare_images') as prepare:
            result = recovered.publish_moments('text', 'private', 'interrupted-moment', [str(image)])
        self.assertEqual(result['status'], 'unknown')
        self.assertFalse(result['retry_allowed'])
        self.assertFalse(result['delivery_confirmed'])
        recovered._run.assert_not_called()
        prepare.assert_not_called()

    def test_sticker_interruption_survives_restart_without_material_credentials(self):
        remember_stickers(self.ledger, {'stickers': [{'sticker_id': 'chosen', 'source': 'search'}]},
                          {'keyword': 'fixture', 'native_cursor': 0})
        first = self.backend()
        with self.assertRaises(KeyboardInterrupt):
            first.send_sticker('fixture-contact', 'chosen', 'search', 'interrupted-sticker')
        first._run.assert_called_once()
        shutil.rmtree(self.ledger / 'stickers')
        recovered = self.backend()
        with patch('weskill.stickers.selected_parameters') as select:
            result = recovered.send_sticker('fixture-contact', 'chosen', 'search', 'interrupted-sticker')
        self.assertEqual(result['status'], 'unknown')
        self.assertFalse(result['retry_allowed'])
        recovered._run.assert_not_called()
        select.assert_not_called()

    def test_invalid_social_write_inputs_do_not_reserve_or_submit(self):
        backend = self.backend()
        backend._run.side_effect = None
        invalid_calls = [
            lambda: backend.send_sticker('fixture-contact', 'chosen', 'unselected', 'key'),
            lambda: backend.send_sticker('fixture-contact', 'chosen', 'saved', ''),
            lambda: backend.publish_moments('text', 'unspecified', 'key'),
            lambda: backend.publish_moments('', 'private', 'key'),
            lambda: backend.publish_moments('text', 'private', 'key', 'not-a-path-list'),
            lambda: backend.publish_moments('bad\0text', 'private', 'key'),
        ]
        for call in invalid_calls:
            with self.assertRaises(ValueError):
                call()
        backend._run.assert_not_called()
        self.assertEqual(list(self.ledger.glob('send-*.json')), [])

    def test_non_utf8_social_ids_are_rejected_before_reservation_or_native_query(self):
        remember_stickers(self.ledger, {'stickers': [{'sticker_id': 'chosen', 'source': 'saved'}]}, {})
        backend = self.backend()
        backend._run.side_effect = None
        invalid_calls = [
            lambda: backend.send_sticker('\ud800', 'chosen', 'saved', 'invalid-recipient'),
            lambda: backend.send_sticker('fixture-contact', '\ud800', 'saved', 'invalid-sticker'),
            lambda: backend.get_moments(contact_id='\ud800'),
        ]
        for call in invalid_calls:
            with self.assertRaises(UnicodeError):
                call()
        backend._run.assert_not_called()
        self.assertEqual(list(self.ledger.glob('send-*.json')), [])


class ReleaseContractTests(unittest.TestCase):
    def test_published_versions_match_the_runtime_and_package(self):
        project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
        self.assertEqual(project['version'], __version__)
        for host in ('codex', 'claude'):
            path = ROOT / 'plugins/weskill' / f'.{host}-plugin/plugin.json'
            manifest = json.loads(path.read_text())
            self.assertEqual(manifest['name'], project['name'])
            self.assertEqual(manifest['version'], __version__)
        marketplace = json.loads((ROOT / '.claude-plugin/marketplace.json').read_text())
        entries = [plugin for plugin in marketplace['plugins'] if plugin['name'] == project['name']]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['version'], __version__)


if __name__ == '__main__':
    unittest.main()
