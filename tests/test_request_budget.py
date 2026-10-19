import multiprocessing
import tempfile
import unittest
from pathlib import Path

from weskill.request_budget import NativeRequestBudget


class Clock:
    def __init__(self):self.now=1000.0
    def time(self):return self.now
    def sleep(self,seconds):self.now+=seconds


class RequestBudgetTests(unittest.TestCase):
    def test_sliding_window_and_restarts_share_twenty_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock=Clock();path=Path(tmp)/'budget.sqlite3'
            for _ in range(20):
                budget=NativeRequestBudget(path,clock=clock.time,sleep=clock.sleep)
                self.assertEqual(budget.delay_or_reserve('search'),0)
            clock.now+=30
            self.assertEqual(budget.delay_or_reserve('send'),30)
            receipt=budget.acquire('messages')
            self.assertEqual(receipt['waited_seconds'],30)
            self.assertEqual(clock.now,1060)

    def test_every_rolling_window_is_bounded_not_calendar_minutes(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock=Clock();budget=NativeRequestBudget(Path(tmp)/'b.sqlite3',clock=clock.time,sleep=clock.sleep)
            admitted=[]
            for n in range(83):
                if n%2:clock.now+=0.1
                budget.acquire('messages' if n%3 else 'send')
                admitted.append(clock.now)
                self.assertLessEqual(sum(clock.now-60<t<=clock.now for t in admitted),20)

    def test_separate_processes_cannot_each_claim_twenty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'b.sqlite3'
            # Fixed clock permits fast, deterministic saturation without waiting.
            NativeRequestBudget(path,clock=lambda:1000).delay_or_reserve('search')
            ctx=multiprocessing.get_context('fork');queue=ctx.Queue()
            def reserve():queue.put(NativeRequestBudget(path,clock=lambda:1000).delay_or_reserve('messages'))
            children=[ctx.Process(target=reserve) for _ in range(24)]
            for child in children:child.start()
            for child in children:
                child.join(5);self.assertEqual(child.exitcode,0)
            delays=[queue.get(timeout=1) for _ in children]
            self.assertEqual(delays.count(0),19)
            self.assertEqual(delays.count(60),5)
            queue.close()
