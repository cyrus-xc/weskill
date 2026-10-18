"""Real child-process protocol tests with an isolated non-native worker fixture."""
from pathlib import Path
import sys
import tempfile
import unittest

from weskill.worker_backend import WorkerBackend

FIXTURE = r'''
import json,os,sys,time
from pathlib import Path
config=json.loads(sys.stdin.readline())
state=Path(config['state_dir']);state.mkdir(parents=True,exist_ok=True)
starts=state/'starts'
count=int(starts.read_text())+1 if starts.exists() else 1
starts.write_text(str(count))
mode=sys.argv[1]
if mode=='fail_always' or mode=='fail_first' and count==1:
    print(json.dumps({'ready':False,'error_code':'connection_timeout','error':'fixture timeout'}),flush=True)
    raise SystemExit(0)
if mode=='permission':
    print(json.dumps({'ready':False,'error_code':'connection_failed','error':'fixture permission denied'}),flush=True)
    raise SystemExit(0)
print(json.dumps({'ready':True}),flush=True)
for line in sys.stdin:
    request=json.loads(line)
    calls=state/'operations'
    calls.write_text(str(int(calls.read_text())+1 if calls.exists() else 1))
    if mode=='crash':os._exit(7)
    if mode=='slow':time.sleep(3)
    print(json.dumps({'id':request['id'],'response':{'status':'client_success',
          'result':{'success':True},'delivery_confirmed':False,'errors':[]}}),flush=True)
'''


class WorkerProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.script = self.directory / 'fixture_worker.py'
        self.script.write_text(FIXTURE)
        self.backend = WorkerBackend(123, '/nonexistent/fixture.so', self.directory,
                                     ['wxid_fixture_contact'])
        self.addCleanup(self.cleanup)

    def cleanup(self):
        processes = [self.backend._worker, *self.backend._retained_workers]
        for worker in set(p for p in processes if p is not None):
            # These are exclusively the non-native fixtures created above.
            if worker.poll() is None:
                worker.terminate()
            worker.wait(timeout=5)
            if worker.stdin and not worker.stdin.closed:
                worker.stdin.close()
            if worker.stdout and not worker.stdout.closed:
                worker.stdout.close()
        self.tmp.cleanup()

    def mode(self, mode):
        self.backend._worker_command = lambda: [sys.executable, '-u', str(self.script), mode]

    def counter(self, name):
        p = self.directory / 'native' / name
        return int(p.read_text()) if p.exists() else 0

    def test_failed_startup_is_replaced_before_sending_one_operation(self):
        self.mode('fail_first')
        result = self.backend.send_text('wxid_fixture_contact', 'fixture', 'stable')
        self.assertEqual(result['status'], 'client_success')
        self.assertEqual(self.counter('starts'), 2)
        self.assertEqual(self.counter('operations'), 1)
        self.assertEqual(self.backend.send_text('wxid_fixture_contact', 'fixture', 'stable'), result)
        self.assertEqual(self.counter('operations'), 1)

    def test_ready_worker_is_reused_across_queries(self):
        self.mode('ready')
        for _ in range(2):
            result = self.backend.search_contacts(['fixture'], 1)
            self.assertEqual(result['status'], 'client_success')
        self.assertEqual(self.counter('starts'), 1)
        self.assertEqual(self.counter('operations'), 2)

    def test_startup_failures_are_bounded_and_never_accept_operations(self):
        self.mode('fail_always')
        result = self.backend.send_text('wxid_fixture_contact', 'fixture', 'failed-start')
        self.assertEqual(result['status'], 'not_submitted')
        self.assertEqual(result['error_code'], 'connection_timeout')
        self.assertEqual(self.counter('starts'), 2)
        self.assertEqual(self.counter('operations'), 0)
        self.assertEqual(self.backend.send_text('wxid_fixture_contact', 'fixture', 'failed-start'), result)
        self.assertEqual(self.counter('starts'), 2)

    def test_permission_failure_does_not_restart_the_worker(self):
        self.mode('permission')
        result = self.backend.search_contacts(['fixture'], 1)
        self.assertEqual(result['status'], 'not_submitted')
        self.assertEqual(self.counter('starts'), 1)
        self.assertEqual(self.counter('operations'), 0)

    def test_worker_crash_after_request_is_unknown_and_not_repeated(self):
        self.mode('crash')
        result = self.backend.send_text('wxid_fixture_contact', 'fixture', 'crashed')
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(self.backend.send_text('wxid_fixture_contact', 'fixture', 'crashed'), result)
        self.assertEqual(self.counter('starts'), 1)
        self.assertEqual(self.counter('operations'), 1)

    def test_response_timeout_retains_worker_and_blocks_duplicate_send(self):
        self.mode('slow')
        self.backend.response_timeout_seconds = 0.05
        result = self.backend.send_text('wxid_fixture_contact', 'fixture', 'pending')
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(len(self.backend._retained_workers), 1)
        self.assertIsNone(self.backend._retained_workers[0].poll())
        self.assertEqual(self.backend.send_text('wxid_fixture_contact', 'fixture', 'pending'), result)
        self.assertEqual(self.counter('operations'), 1)


if __name__ == '__main__':
    unittest.main()
