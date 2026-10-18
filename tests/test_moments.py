import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from weskill.backend import ExperimentalBackend
from weskill.media import file_identity
from weskill.moments import decode_moment, prepare_images, read_moments


def page(ids, following=None, top=()):
    return {'status': 'client_success', 'result': {'success': True,
        'moments': [{'moment_id': str(i)} for i in ids],
        'top_moments': [{'moment_id': str(i)} for i in top],
        'has_more': following is not None, 'next_cursor': following}}


class MomentsTests(unittest.TestCase):
    def test_signed_native_sns_json_maps_to_same_unsigned_timeline_identity(self):
        result = ExperimentalBackend._string_message_ids({'sns_id': -2, 'nested': {'moment_id': 2**64-2}})
        self.assertEqual(result['sns_id'], result['nested']['moment_id'])

    def test_empty_filtered_page_can_follow_native_continuation(self):
        first = page([], 'next')
        first['result']['continuation_only'] = True
        run = Mock(side_effect=[first, page([3])])
        result = read_moments(run, 0, None, None, False)['result']
        self.assertEqual(result['moments'], [{'moment_id': '3'}])
        self.assertFalse(result['pagination_stalled'])

    def test_pages_keep_uint64_strings_and_separate_top_posts(self):
        run = Mock(side_effect=[page([2**63+2], 'next', [100]), page([2**63+1], None, [100])])
        result = read_moments(run, 0, None, None, False)['result']
        self.assertEqual([r['moment_id'] for r in result['moments']], [str(2**63+2), str(2**63+1)])
        self.assertEqual(result['top_moments'], [{'moment_id': '100'}])
        self.assertEqual(run.call_args_list[1].args[1]['cursor'], 'next')
        self.assertEqual(result['pages_fetched'], 2)

    def test_stalled_page_reports_incomplete_instead_of_looping(self):
        run = Mock(return_value=page([], 'same'))
        result = read_moments(run, None, None, None, False)['result']
        self.assertTrue(result['pagination_stalled'])
        self.assertTrue(result['has_more'])
        run.assert_called_once()

    def test_failure_keeps_previously_read_rows_explicitly_partial(self):
        run = Mock(side_effect=[page([2], 'older'), {'status': 'client_error', 'result': None}])
        result = read_moments(run, 0, None, None, False)
        self.assertEqual(result['status'], 'client_error')
        self.assertEqual(result['partial_result']['moments'], [{'moment_id': '2'}])
        self.assertEqual(result['partial_result']['next_cursor'], 'older')

    def test_cursor_scope_and_uint64_validation_precede_native_calls(self):
        run = Mock()
        for cursor in ({'contact_id': 'other', 'max_id': '1'}, {'contact_id': None, 'max_id': str(2**64)}):
            with self.assertRaises(ValueError):
                read_moments(run, 20, json.dumps(cursor), None, False)
        run.assert_not_called()

    def test_xml_keeps_media_repetition_location_attributes_and_optional_raw(self):
        xml = '<SnsDataItem><location latitude="1"/><media><id>1</id><id>2</id></media></SnsDataItem>'
        row = decode_moment({'moment_id': '7', 'native_xml': xml})
        self.assertNotIn('native_xml', row)
        self.assertEqual(row['details']['location']['latitude'], '1')
        self.assertEqual(row['details']['media']['id'], ['1', '2'])
        self.assertEqual(decode_moment({'native_xml': xml}, True)['native_xml'], xml)

    def test_image_preparation_retains_original_and_makes_real_rgb_jpeg_and_thumb(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'alpha.png'
            Image.new('RGBA', (512, 320), (0, 255, 0, 128)).save(source)
            prepared = prepare_images([str(source)], folder, 'one', [file_identity(source)])[0]
            self.assertEqual(Path(prepared['source_path']).read_bytes(), source.read_bytes())
            self.assertEqual((prepared['width'], prepared['height']), (512, 320))
            with Image.open(prepared['data_path']) as image:
                self.assertEqual((image.format, image.mode, image.size), ('JPEG', 'RGB', (512, 320)))
            with Image.open(prepared['thumb_path']) as image:
                self.assertEqual(image.size, (256, 160))

    def test_published_request_is_not_replayed_and_visibility_binds_key(self):
        with tempfile.TemporaryDirectory() as folder:
            backend = ExperimentalBackend(123, '/tmp/unused-shim', folder)
            backend._run = Mock(return_value={'status': 'client_success', 'result': {'success': True, 'sns_id': '9'}})
            first = backend.publish_moments('hello', 'private', 'key')
            self.assertEqual(first, backend.publish_moments('hello', 'private', 'key'))
            backend._run.assert_called_once()
            with self.assertRaises(ValueError):
                backend.publish_moments('hello', 'public', 'key')

    def test_changed_picture_never_reuses_completed_key(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / 'test.png'
            Image.new('RGB', (8, 8), 'red').save(image)
            backend = ExperimentalBackend(123, '/tmp/unused-shim', folder)
            backend._run = Mock(return_value={'status': 'client_success', 'result': {'success': True}})
            with patch('weskill.media._cache_root', return_value=Path(folder)):
                backend.publish_moments('', 'private', 'key', [str(image)])
            Image.new('RGB', (8, 8), 'blue').save(image)
            with self.assertRaises(ValueError):
                backend.publish_moments('', 'private', 'key', [str(image)])
            backend._run.assert_called_once()
