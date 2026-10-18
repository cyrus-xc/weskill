"""Stand-in ledger and input validation tests, never native integration tests."""
import json
import multiprocessing
from pathlib import Path
import tempfile
import threading
import unittest

from weskill.backend import ExperimentalBackend

CONTACT = 'wxid_fixture_contact'
GROUP = '12345678@chatroom'


class StandinBackend(ExperimentalBackend):
    def __init__(self, directory, outcome=None):
        super().__init__(123, '/nonexistent/standin.so', directory)
        self.calls = []
        self.outcome = outcome or {'status': 'client_success', 'result': {'success': True},
                                   'delivery_confirmed': False, 'errors': []}

    def _run(self, mode, parameters):
        self.calls.append((mode, parameters))
        if mode == 'send':
            records = list(self.state_dir.glob('send-*.json'))
            assert records, 'Durable record must exist before side effects'
            assert any(json.loads(p.read_text())['response']['status'] == 'unknown'
                       for p in records), 'Submission starts as durable unknown'
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return dict(self.outcome)


class BackendLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)

    def test_new_contacts_and_groups_work_without_registration(self):
        backend = StandinBackend(self.directory)
        for index, recipient in enumerate(['wxid_new_contact', '98765432@chatroom']):
            sent = backend.send_text(recipient, 'fixture', f'new-target-{index}')
            self.assertEqual(sent['status'], 'client_success')
            read = backend.get_messages([recipient], 1)
            self.assertEqual(read['status'], 'client_success')
        self.assertEqual([mode for mode, _ in backend.calls],
                         ['send', 'messages', 'send', 'messages'])

    def test_invalid_recipient_rejects_before_ledger_or_side_effects(self):
        backend = StandinBackend(self.directory)
        for recipient in [None, [], '', '  ', 'wxid_bad\0']:
            with self.assertRaises(ValueError):
                backend.send_text(recipient, 'test', 'invalid-target')
        self.assertEqual(backend.calls, [])
        self.assertEqual(list(self.directory.glob('send-*.json')), [])

    def test_client_success_is_not_delivery_and_replay_survives_restart(self):
        first = StandinBackend(self.directory)
        expected = first.send_text(CONTACT, 'one authorized text', 'stable-key')
        second = StandinBackend(self.directory)
        self.assertEqual(second.send_text(CONTACT, 'one authorized text', 'stable-key'), expected)
        self.assertEqual(len(first.calls), 1)
        self.assertEqual(second.calls, [])
        self.assertEqual(expected['status'], 'client_success')
        self.assertIs(expected['delivery_confirmed'], False)
        self.assertIs(expected['retry_allowed'], False)
        ledger = next(self.directory.glob('send-*.json'))
        self.assertEqual(ledger.stat().st_mode & 0o777, 0o600)

    def test_same_key_cannot_change_target_or_text(self):
        backend = StandinBackend(self.directory)
        backend.send_text(CONTACT, 'text', 'bound')
        for recipient, text in [(CONTACT, 'different'), (GROUP, 'text')]:
            with self.assertRaises(ValueError):
                backend.send_text(recipient, text, 'bound')
        self.assertEqual(len(backend.calls), 1)

    def test_native_timeout_remains_unknown_without_retry(self):
        backend = StandinBackend(self.directory, TimeoutError('completion pending'))
        result = backend.send_text(GROUP, 'group text', 'timeout')
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(backend.send_text(GROUP, 'group text', 'timeout'), result)
        self.assertEqual(len(backend.calls), 1)

    def test_crash_after_reservation_leaves_unknown_for_next_process(self):
        backend = StandinBackend(self.directory, KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            backend.send_text(CONTACT, 'text', 'interrupted')
        recovered = StandinBackend(self.directory)
        result = recovered.send_text(CONTACT, 'text', 'interrupted')
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(recovered.calls, [])

    def test_not_submitted_can_be_explicitly_retried_without_changing_key(self):
        backend = StandinBackend(self.directory, {'status': 'not_submitted', 'result': None,
            'delivery_confirmed': False, 'errors': ['attach cancelled']})
        first = backend.send_text(CONTACT, 'text', 'attach-failed')
        self.assertEqual(first['status'], 'not_submitted')
        backend.outcome = {'status': 'client_success', 'result': {'success': True}}
        second = backend.send_text(CONTACT, 'text', 'attach-failed')
        self.assertEqual(second['status'], 'client_success')
        self.assertEqual(backend.send_text(CONTACT, 'text', 'attach-failed'), second)
        self.assertEqual(len(backend.calls), 2)

    def test_shared_ledger_serializes_independent_backend_instances(self):
        first = StandinBackend(self.directory)
        second = StandinBackend(self.directory)
        start = threading.Barrier(2)
        results = []
        def call(backend):
            start.wait()
            results.append(backend.send_text(CONTACT, 'same text', 'concurrent'))
        threads = [threading.Thread(target=call, args=(x,)) for x in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(first.calls) + len(second.calls), 1)

    def test_cross_process_ledger_allows_only_one_side_effect(self):
        context = multiprocessing.get_context('fork')
        barrier = context.Barrier(2)
        results = context.Queue()
        audit = self.directory / 'standin-side-effects'
        directory = self.directory
        class AuditedBackend(StandinBackend):
            def _run(self, mode, parameters):
                with audit.open('a') as stream:
                    stream.write('one\n')
                return super()._run(mode, parameters)
        def worker():
            backend = AuditedBackend(directory)
            barrier.wait()
            results.put(backend.send_text(CONTACT, 'text', 'process-shared'))
        processes = [context.Process(target=worker) for _ in range(2)]
        for process in processes:
            process.start()
        for process in processes:
            process.join(5)
            if process.is_alive():
                process.terminate()
                process.join()
                self.fail('Ledger worker did not complete')
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(results.get(timeout=1), results.get(timeout=1))
        self.assertEqual(audit.read_text().splitlines(), ['one'])
        results.close()

    def test_corrupt_existing_ledger_fails_closed(self):
        backend = StandinBackend(self.directory)
        backend.send_text(CONTACT, 'text', 'corrupt')
        next(self.directory.glob('send-*.json')).write_text('{')
        recovered = StandinBackend(self.directory)
        with self.assertRaises(json.JSONDecodeError):
            recovered.send_text(CONTACT, 'text', 'corrupt')
        self.assertEqual(recovered.calls, [])

    def test_search_has_no_artificial_count_or_keyword_caps(self):
        backend = StandinBackend(self.directory)
        backend.search_contacts(['测试群'], limit=5, groups_only=True)
        self.assertEqual(backend.calls[0][1]['filter_type'], 2)
        backend.search_contacts(['x' * 1000] * 12, limit=500, sort_by_time=True)
        self.assertEqual(backend.calls[-1][1]['limit'], 500)
        self.assertTrue(backend.calls[-1][1]['sort_by_time'])
        for keywords, limit in [([None], 5), (['x'], -1), (['x'], True), ('x', 5)]:
            with self.assertRaises(ValueError):
                backend.search_contacts(keywords, limit)
        self.assertEqual(len(backend.calls), 2)

    def test_message_query_defaults_and_caller_selected_options(self):
        backend = StandinBackend(self.directory)
        backend.get_messages([CONTACT, GROUP], limit=2)
        self.assertEqual(backend.calls, [('messages', {
            'chat_ids': [CONTACT, GROUP], 'limit': 2, 'include_xml': False})])
        self.assertEqual(list(self.directory.glob('send-*.json')), [])

    def test_history_defaults_20_accepts_all_and_large_counts_and_batch(self):
        backend = StandinBackend(self.directory)
        backend.get_messages(['filehelper'])
        self.assertEqual(backend.calls[-1][1]['limit'], 20)
        for limit in [500, 0, None]:
            backend.get_messages(['legacy_username'] * 12, limit, include_xml=True)
            self.assertEqual(backend.calls[-1][1]['limit'], 200)
            self.assertEqual(len(backend.calls[-1][1]['chat_ids']), 1)
            self.assertTrue(backend.calls[-1][1]['include_xml'])

    def test_message_query_rejects_invalid_input(self):
        backend = StandinBackend(self.directory)
        for ids, limit in [([], 2), ([CONTACT], -1), ([CONTACT], True),
                           ('fixture', 2), ([None], 2), (['bad\0id'], 2)]:
            with self.assertRaises(ValueError):
                backend.get_messages(ids, limit)
        self.assertEqual(backend.calls, [])

    def test_all_history_pages_include_dense_timestamp_boundaries(self):
        class PagedBackend(ExperimentalBackend):
            def __init__(self, directory):
                super().__init__(123, '/nonexistent/fixture.so', directory)
                self.rows = [{'svr_id': i, 'create_time': 1000 + i // 500,
                              'content': 'repeated', 'sender_id': 'fixture'} for i in range(1300)]
                self.limits = []

            def _run(self, mode, parameters):
                self.limits.append(parameters['limit'])
                rows = [row for row in self.rows
                        if row['create_time'] <= parameters.get('end_time', 99999)]
                return {'status': 'client_success', 'result': {'success': True,
                    'sessions': [{'chat_id': 'fixture', 'messages': rows[-parameters['limit']:]}]}}

        backend = PagedBackend(self.directory)
        all_rows = backend.get_messages(['fixture'], None)['result']['sessions'][0]['messages']
        self.assertEqual([int(row['svr_id']) for row in all_rows], list(range(1300)))
        self.assertIn(400, backend.limits)  # Dense seconds are expanded without gaps.
        selected = backend.get_messages(['fixture'], 450)['result']['sessions'][0]['messages']
        self.assertEqual([int(row['svr_id']) for row in selected], list(range(850, 1300)))

    def test_large_server_message_id_survives_json_for_javascript_clients(self):
        server_id = 18446744073709551601
        backend = StandinBackend(self.directory, {
            'status': 'client_success', 'delivery_confirmed': False, 'errors': [],
            'result': {'success': True, 'sessions': [{'messages': [{'svr_id': server_id}]}]}})
        response = backend.get_messages([CONTACT], 1)
        wire = json.loads(json.dumps(response))
        self.assertEqual(wire['result']['sessions'][0]['messages'][0]['svr_id'], str(server_id))
        self.assertFalse(wire['delivery_confirmed'])

    def test_text_bounds_reject_before_side_effects(self):
        backend = StandinBackend(self.directory)
        for text in ['  ', 'NUL\0', '\ud800']:
            with self.assertRaises(ValueError):
                backend.send_text(CONTACT, text, 'invalid')
        self.assertEqual(backend.calls, [])
    def test_long_text_legacy_ids_and_long_idempotency_keys_are_accepted(self):
        backend = StandinBackend(self.directory)
        response = backend.send_text('filehelper', '😀' * 10000, 'k' * 1000)
        self.assertEqual(response['status'], 'client_success')
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(backend.calls[0][0], 'send')  # No history verification.



if __name__ == '__main__':
    unittest.main()
