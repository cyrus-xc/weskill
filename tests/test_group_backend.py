"""Group requests share the durable write ledger and serialized native worker."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from test_backend import StandinBackend, CONTACT, GROUP


class ManagedGroupBackend(StandinBackend):
    role = 'owner'
    role_failure = False

    def _run(self, mode, parameters):
        if parameters.get('operation') == 'get_group_members':
            self.role_checks = getattr(self, 'role_checks', 0) + 1
            return {'status': 'unknown' if self.role_failure else 'client_success',
                    'result': {'success': not self.role_failure, 'self_role': self.role}, 'errors': []}
        return super()._run(mode, parameters)


class GroupBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.backend = ManagedGroupBackend(self.directory)

    def test_group_write_replay_survives_restart(self):
        result = self.backend.create_group([CONTACT], '测试群', 'create')
        other = StandinBackend(self.directory)
        self.assertEqual(other.create_group([CONTACT], '测试群', 'create'), result)
        self.assertEqual(other.calls, [])
        ledger = self.directory / ('send-' + hashlib.sha256(b'create').hexdigest() + '.json')
        self.assertEqual(json.loads(ledger.read_text())['parameters']['name'], '测试群')
        self.assertEqual(ledger.stat().st_mode & 0o777, 0o600)

    def test_unknown_cannot_replay_and_key_cannot_change_action(self):
        self.backend.outcome = TimeoutError('pending')
        result = self.backend.invite_group_members(GROUP, [CONTACT], 'invite')
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(self.backend.invite_group_members(GROUP, [CONTACT], 'invite'), result)
        with self.assertRaises(ValueError):
            self.backend.invite_group_members(GROUP, [CONTACT], 'invite', mode='add')
        with self.assertRaises(ValueError):
            self.backend.send_text(GROUP, 'different operation', 'invite')
        self.assertEqual(len(self.backend.calls), 1)

    def test_not_submitted_can_retry_original_operation(self):
        self.backend.outcome = {'status': 'not_submitted', 'result': None}
        self.assertTrue(self.backend.pin_group_message(GROUP, '18446744073709551610', 'pin')['retry_allowed'])
        self.backend.outcome = {'status': 'client_success', 'result': {'success': True}}
        self.assertEqual(self.backend.pin_group_message(GROUP, '18446744073709551610', 'pin')['status'], 'client_success')
        self.assertEqual(self.backend.calls[-1][1]['message_id'], '18446744073709551610')

    def test_mentions_use_metadata_for_multiple_members_and_all(self):
        self.backend.send_group_mention(GROUP, '@甲 @乙', ['legacy_a', 'legacy_b'], 'mention', True)
        mode, parameters = self.backend.calls[0]
        self.assertEqual(mode, 'mention')
        self.assertEqual(parameters['at_user_list'], 'legacy_a,legacy_b,notify@all')
        self.assertEqual(parameters['text'], '@甲 @乙')

    def test_announcement_roundtrip_input_and_clear_are_distinct_operations(self):
        self.backend.set_group_announcement(GROUP, '中文 & <text> 😀', 'set')
        self.backend.set_group_announcement(GROUP, '', 'clear')
        published, cleared = [v for _, v in self.backend.calls]
        self.assertIn('中文 &amp; &lt;text&gt; 😀', published['xml'])
        self.assertFalse(published['clear'])
        self.assertTrue(cleared['clear'])
        with self.assertRaises(ValueError):
            self.backend.set_group_announcement(GROUP, 'changed', 'set')

    def test_invalid_parameters_do_not_submit(self):
        for args in [('not-a-group', '1'), (GROUP, '0'), (GROUP, str(2**64)), (GROUP, '1.5')]:
            with self.assertRaises(ValueError):
                self.backend.pin_group_message(*args, 'invalid')
        with self.assertRaises(ValueError):
            self.backend.send_group_mention(GROUP, 'text', [], 'invalid')
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(list(self.directory.glob('send-*.json')), [])

    def test_group_reads_share_the_native_serialization_lock(self):
        active = 0
        peak = 0
        control = threading.Lock()
        class BlockingBackend(StandinBackend):
            def _run(self, mode, parameters):
                nonlocal active, peak
                with control:
                    active += 1
                    peak = max(peak, active)
                time.sleep(.02)
                with control:
                    active -= 1
                return {'status': 'client_success', 'result': {'success': True}}
        backend = BlockingBackend(self.directory)
        threads = [threading.Thread(target=method, args=(GROUP,))
                   for method in [backend.get_group_members, backend.get_group_info]]
        for thread in threads: thread.start()
        for thread in threads:
            thread.join(2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(peak, 1)

    def test_invitation_confirmation_wire_and_shared_key(self):
        self.backend.set_group_invitation_confirmation(GROUP, True, 'approval-on')
        self.backend.set_group_invitation_confirmation(GROUP, False, 'approval-off')
        enabled = self.backend.calls[0][1]
        disabled = self.backend.calls[1][1]
        name = GROUP.encode()
        self.assertEqual(bytes.fromhex(enabled['payload_hex']), b'\x0a' + bytes([len(name)]) + name + b'\x10\x02')
        self.assertEqual(bytes.fromhex(disabled['payload_hex']), b'\x0a' + bytes([len(name)]) + name + b'\x10\x00')
        with self.assertRaises(ValueError):
            self.backend.set_group_invitation_confirmation(GROUP, False, 'approval-on')

    def test_removal_replay_survives_restart_and_binds_members_and_operation(self):
        result = self.backend.remove_group_members(GROUP, [CONTACT, 'legacy_b'], 'remove')
        recovered = ManagedGroupBackend(self.directory)
        self.assertEqual(recovered.remove_group_members(GROUP, [CONTACT, 'legacy_b'], 'remove'), result)
        self.assertEqual(recovered.calls, [])
        for call in [lambda: recovered.remove_group_members(GROUP, [CONTACT], 'remove'),
                     lambda: recovered.invite_group_members(GROUP, [CONTACT, 'legacy_b'], 'remove')]:
            with self.assertRaises(ValueError): call()

    def test_invalid_removal_inputs_do_not_create_a_ledger(self):
        for call in [lambda: self.backend.remove_group_members(GROUP, [], 'invalid'),
                     lambda: self.backend.remove_group_members(GROUP, [''], 'invalid')]:
            with self.assertRaises(ValueError): call()
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(list(self.directory.glob('send-*.json')), [])

    def test_only_owner_or_admin_can_submit_removal(self):
        for role in ('owner', 'admin', 'member', 'unknown'):
            with self.subTest(role=role):
                self.backend.role = role
                before = len(self.backend.calls)
                result = self.backend.remove_group_members(GROUP, [CONTACT], f'remove-{role}')
                self.assertEqual(result['status'], 'client_success' if role in ('owner', 'admin') else 'not_submitted')
                self.assertEqual(len(self.backend.calls) - before, 1 if role in ('owner', 'admin') else 0)

    def test_role_query_failure_submits_nothing_and_original_key_can_retry_after_permission_change(self):
        self.backend.role_failure = True
        result = self.backend.remove_group_members(GROUP, [CONTACT], 'pending-permission')
        self.assertEqual(result['status'], 'not_submitted')
        self.assertEqual(result['error_code'], 'group_role_unavailable')
        self.assertEqual(self.backend.calls, [])
        self.backend.role_failure = False
        self.backend.role = 'member'
        result = self.backend.remove_group_members(GROUP, [CONTACT], 'pending-permission')
        self.assertEqual(result['error_code'], 'group_permission_denied')
        self.backend.role = 'admin'
        result = self.backend.remove_group_members(GROUP, [CONTACT], 'pending-permission')
        self.assertEqual(result['status'], 'client_success')
        checks = self.backend.role_checks
        self.assertEqual(self.backend.remove_group_members(GROUP, [CONTACT], 'pending-permission'), result)
        self.assertEqual(self.backend.role_checks, checks)
        self.assertEqual(len(self.backend.calls), 1)


class GroupToolContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_dangerous_group_tools_are_identified_and_use_explicit_ids_and_keys(self):
        from weskill.server import create_server
        server = create_server(Path('/nonexistent/fixture-client'), backend=object())
        tools = {tool.name: tool for tool in await server.list_tools()}
        self.assertEqual(len(tools), 31)
        for name, required in [('remove_group_members', {'group_id', 'member_ids', 'idempotency_key'})]:
            tool = tools[name]
            self.assertFalse(tool.annotations.readOnlyHint)
            self.assertTrue(tool.annotations.destructiveHint)
            self.assertTrue(tool.annotations.idempotentHint)
            self.assertEqual(set(tool.inputSchema['required']), required)
