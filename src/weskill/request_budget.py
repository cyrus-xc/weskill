"""Per-user, cross-process rolling budget for native business submissions."""
import contextlib
import fcntl
import os
from pathlib import Path
import random
import sqlite3
import time

LIMIT = 20
WINDOW_SECONDS = 60


class NativeRequestBudget:
    def __init__(self, path=None, *, clock=time.time, sleep=time.sleep, jitter=random.uniform):
        state=Path(os.environ.get('XDG_STATE_HOME',Path.home()/'.local/state'))
        self.path=Path(path) if path is not None else state/'weskill/native-requests.sqlite3'
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.clock=clock
        self.sleep=sleep
        self.jitter=jitter

    def _cooldown(self, until=None):
        with contextlib.closing(sqlite3.connect(self.path,timeout=30,isolation_level=None)) as conn:
            os.chmod(self.path,0o600)
            conn.execute('CREATE TABLE IF NOT EXISTS operation_gate(id INTEGER PRIMARY KEY CHECK(id=1),not_before REAL NOT NULL)')
            if until is not None:
                conn.execute('INSERT INTO operation_gate VALUES(1,?) ON CONFLICT(id) DO UPDATE SET not_before=excluded.not_before',(until,))
            row=conn.execute('SELECT not_before FROM operation_gate WHERE id=1').fetchone()
            return row[0] if row else 0.0

    def _wait_until(self, deadline):
        while (remaining:=deadline-self.clock())>0:
            try:
                self.sleep(remaining)
            except InterruptedError:
                continue

    @contextlib.contextmanager
    def operation(self, mode):
        """Serialize the entire native operation and its post-operation cooldown."""
        fd=os.open(str(self.path)+'.operation.lock',os.O_CREAT|os.O_RDWR,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX)
            self._wait_until(self._cooldown())
            delay=float(self.jitter(1.0,3.0))
            if not 1.0<=delay<=3.0:
                raise ValueError('Native cooldown must be between 1 and 3 seconds')
            receipt=self.acquire(mode)
            receipt['cooldown_seconds']=round(delay,3)
            try:
                yield receipt
            finally:
                deadline=self.clock()+delay
                try:
                    self._cooldown(deadline)
                except Exception as error:
                    # A post-submission persistence failure must not turn a
                    # confirmed send into "not submitted" and permit replay.
                    receipt['cooldown_persistence_error']=type(error).__name__
                self._wait_until(deadline)
        finally:
            fcntl.flock(fd,fcntl.LOCK_UN)
            os.close(fd)

    def delay_or_reserve(self, mode):
        with contextlib.closing(sqlite3.connect(self.path,timeout=30,isolation_level=None)) as conn:
            os.chmod(self.path,0o600)
            conn.execute('CREATE TABLE IF NOT EXISTS requests(started REAL NOT NULL,mode TEXT NOT NULL)')
            conn.execute('BEGIN IMMEDIATE')
            try:
                now=self.clock()
                conn.execute('DELETE FROM requests WHERE started<=?',(now-WINDOW_SECONDS,))
                count,oldest=conn.execute('SELECT count(*),min(started) FROM requests').fetchone()
                if count>=LIMIT:
                    delay=max(0.001,oldest+WINDOW_SECONDS-now)
                else:
                    conn.execute('INSERT INTO requests VALUES(?,?)',(now,mode))
                    delay=0.0
                conn.commit()
                return delay
            except BaseException:
                conn.rollback()
                raise

    def acquire(self, mode):
        waited=0.0
        while delay:=self.delay_or_reserve(mode):
            self.sleep(delay)
            waited+=delay
        return {'limit':LIMIT,'window_seconds':WINDOW_SECONDS,'waited_seconds':round(waited,3)}

    def snapshot(self):
        rows=[]
        cooldown=0.0
        now=self.clock()
        if self.path.exists():
            with contextlib.closing(sqlite3.connect(self.path,timeout=30)) as conn:
                tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'requests' in tables:
                    rows=conn.execute('SELECT started,mode FROM requests WHERE started>?',(now-WINDOW_SECONDS,)).fetchall()
                if 'operation_gate' in tables:
                    row=conn.execute('SELECT not_before FROM operation_gate WHERE id=1').fetchone()
                    cooldown=max(0,row[0]-now) if row else 0.0
        from collections import Counter
        return {'limit':LIMIT,'window_seconds':WINDOW_SECONDS,'used':len(rows),
                'by_mode':dict(Counter(r[1] for r in rows)),
                'operation_cooldown_seconds':{'min':1,'max':3},
                'cooldown_remaining_seconds':round(cooldown,3),
                'retry_after_seconds':max(0,min(r[0] for r in rows)+WINDOW_SECONDS-now) if len(rows)>=LIMIT else 0}
