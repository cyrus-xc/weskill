import multiprocessing
from pathlib import Path
import tempfile
import time
import unittest

from weskill.request_budget import NativeRequestBudget


class OperationLockTests(unittest.TestCase):
    def test_jitter_endpoints_hold_until_operation_finishes_and_release_after_error(self):
        with tempfile.TemporaryDirectory() as directory:
            now=[1000.0];draws=[];delays=iter([1.0,3.0])
            def jitter(low,high):draws.append((low,high));return next(delays)
            def sleep(seconds):now[0]+=seconds
            budget=NativeRequestBudget(Path(directory)/'budget.db',clock=lambda:now[0],sleep=sleep,jitter=jitter)
            with budget.operation('search') as first:
                self.assertEqual(now[0],1000)
                now[0]+=10 # A long native query keeps the gate for its duration.
            self.assertEqual(now[0],1011)
            self.assertEqual(first['cooldown_seconds'],1)
            with self.assertRaisesRegex(ValueError,'native failure'):
                with budget.operation('send') as second:
                    raise ValueError('native failure')
            self.assertEqual(now[0],1014)
            self.assertEqual(second['cooldown_seconds'],3)
            self.assertEqual(draws,[(1.0,3.0)]*2)

    def test_cooldown_survives_interrupted_wait_and_new_budget_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'b.db';now=[1000.0]
            def interrupt(seconds):raise KeyboardInterrupt()
            budget=NativeRequestBudget(path,clock=lambda:now[0],sleep=interrupt,jitter=lambda low,high:3.0)
            with self.assertRaises(KeyboardInterrupt):
                with budget.operation('search'):pass
            seen=[]
            def sleep(seconds):now[0]+=seconds
            restarted=NativeRequestBudget(path,clock=lambda:now[0],sleep=sleep,jitter=lambda low,high:1.0)
            with restarted.operation('messages'):seen.append(now[0])
            self.assertEqual(seen,[1003])
            self.assertEqual(now[0],1004)

    def test_two_processes_never_overlap_and_keep_cooldown_between_operations(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'b.db'
            ctx=multiprocessing.get_context('fork');barrier=ctx.Barrier(2);queue=ctx.Queue()
            def operation(number):
                gate=NativeRequestBudget(path,jitter=lambda low,high:1.0)
                barrier.wait()
                with gate.operation('fixture'):
                    queue.put(('enter',number,time.monotonic()))
                    time.sleep(0.05)
                    queue.put(('leave',number,time.monotonic()))
            children=[ctx.Process(target=operation,args=(i,)) for i in range(2)]
            for child in children:child.start()
            for child in children:
                child.join(7)
                if child.is_alive():child.terminate();child.join()
                self.assertEqual(child.exitcode,0)
            records=[queue.get(timeout=1) for _ in range(4)]
            records.sort(key=lambda x:x[2])
            self.assertEqual([r[0] for r in records],['enter','leave','enter','leave'])
            self.assertEqual(records[0][1],records[1][1])
            self.assertNotEqual(records[0][1],records[2][1])
            self.assertGreaterEqual(records[2][2]-records[1][2],1.0)
            queue.close()
