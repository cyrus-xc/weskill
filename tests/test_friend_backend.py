"""Friend operations preserve native values and the shared durable write contract."""
from pathlib import Path
import tempfile
import unittest

from test_backend import StandinBackend, CONTACT


class FriendBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)

    def test_profiles_preserve_missing_and_unicode_native_fields(self):
        outcome = {'status': 'client_success', 'result': {'success': True, 'contacts': [
            {'contact_id': CONTACT, 'nickname': '中文 😀', 'remark': '', 'city': None},
            {'contact_id': 'uncached_member', 'found': False}]}, 'errors': []}
        backend = StandinBackend(self.directory, outcome)
        self.assertEqual(backend.get_friend_info([CONTACT, 'uncached_member']), outcome)
        self.assertEqual(backend.calls[0][0], 'friend_profile')
        self.assertEqual(list(self.directory.glob('send-*.json')), [])

    def test_unknown_friend_write_is_durable_across_backend_instances(self):
        parameters = {'operation': 'set_contact_remark', 'contact_id': CONTACT, 'remark': '测试 😀'}
        first = StandinBackend(self.directory, TimeoutError('possibly submitted'))
        result = first._operation_write('friend_remark', parameters, 'friend-write')
        self.assertEqual(result['status'], 'unknown')
        recovered = StandinBackend(self.directory)
        self.assertEqual(recovered._operation_write('friend_remark', parameters, 'friend-write'), result)
        self.assertEqual(recovered.calls, [])
        with self.assertRaises(ValueError):
            recovered._operation_write('friend_request', parameters, 'friend-write')
        with self.assertRaises(ValueError):
            recovered.send_text(CONTACT, 'different action', 'friend-write')

    def test_remark_can_be_cleared_and_replay_binds_exact_value(self):
        backend = StandinBackend(self.directory)
        changed = backend.set_contact_remark(CONTACT, '测试 😀', 'remark')
        self.assertEqual(backend.set_contact_remark(CONTACT, '测试 😀', 'remark'), changed)
        self.assertEqual(len(backend.calls), 1)
        with self.assertRaises(ValueError):
            backend.set_contact_remark(CONTACT, '', 'remark')
        backend.set_contact_remark(CONTACT, '', 'clear')
        self.assertEqual(backend.calls[-1][1]['remark'], '')

    def test_group_profiles_merge_by_id_preserving_roles_and_missing_members(self):
        class ProfileBackend(StandinBackend):
            def _run(self, mode, parameters):
                if mode == 'group':
                    return {'status': 'client_success', 'result': {'success': True,
                        'members': [{'member_id': 'a', 'role': 'owner', 'group_nickname': '群昵称'},
                                    {'member_id': 'b', 'role': 'member'}]}}
                return {'status': 'client_success', 'result': {'contacts': [
                    {'contact_id': 'b', 'found': False},
                    {'contact_id': 'a', 'found': True, 'nickname': '昵称', 'remark': '备注'}]}}
        backend = ProfileBackend(self.directory)
        members = backend.get_group_members('12345678@chatroom')['result']['members']
        self.assertEqual(members[0]['role'], 'owner')
        self.assertEqual(members[0]['display_name'], '群昵称')
        self.assertEqual(members[0]['nickname'], '昵称')
        self.assertFalse(members[1]['profile']['found'])
        self.assertEqual(members[1]['display_name'], 'b')

    def test_profile_failure_is_visible_without_discarding_native_members(self):
        class ProfileBackend(StandinBackend):
            def _run(self, mode, parameters):
                if mode == 'group':
                    return {'status': 'client_success', 'result': {'members': [{'member_id': 'a'}]}}
                return {'status': 'unknown', 'errors': ['profile query interrupted']}
        result = ProfileBackend(self.directory).get_group_members('12345678@chatroom')['result']
        self.assertEqual(result['profiles_status'], 'unknown')
        self.assertEqual(result['profiles_errors'], ['profile query interrupted'])
        self.assertIsNone(result['members'][0]['profile'])

    def test_friend_request_writes_bind_identity_and_intent_without_replay(self):
        backend = StandinBackend(self.directory)
        result = backend.add_friend('test_wechat_identifier', 'add', '你好 😀', '测试')
        self.assertEqual(backend.add_friend('test_wechat_identifier', 'add', '你好 😀', '测试'), result)
        with self.assertRaises(ValueError):
            backend.add_friend('test_wechat_identifier', 'add', 'different greeting', '测试')
        with self.assertRaises(ValueError):
            backend.accept_friend_request('selected-request', 'add')
        result = backend.accept_friend_request('selected-request', 'accept', None)
        self.assertEqual(backend.accept_friend_request('selected-request', 'accept', None), result)
        with self.assertRaises(ValueError):
            backend.accept_friend_request('selected-request', 'accept', '')
        self.assertEqual(len(backend.calls), 2)

    def test_request_list_all_and_offset_have_no_toolkit_count_cap(self):
        backend = StandinBackend(self.directory)
        for limit in [20, 100000, 0, None]:
            backend.list_friend_requests(limit, 3)
        self.assertEqual([call[1]['limit'] for call in backend.calls], [20, 100000, 0, None])
        for limit, offset in [(-1, 0), (True, 0), (20, -1), (20, False)]:
            with self.assertRaises(ValueError):
                backend.list_friend_requests(limit, offset)

    def test_invalid_profile_input_never_invokes_native(self):
        backend = StandinBackend(self.directory)
        for contacts in [[], [''], ['bad\0id'], ['\ud800'], 'not-a-list']:
            with self.assertRaises((ValueError, UnicodeError)):
                backend.get_friend_info(contacts)
        self.assertEqual(backend.calls, [])
