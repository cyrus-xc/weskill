"""Isolate native connection bootstrap from long-lived MCP process state."""
from __future__ import annotations

import json
import selectors
import subprocess
import sys
import threading
import time
import uuid

from .backend import ExperimentalBackend, NativeConnectionTimeout, _save_private


class WorkerBackend(ExperimentalBackend):
    """Keep one ready native worker; restart only before an operation is sent."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._worker = None
        self._retained_workers = []
        self.startup_timeout_seconds = 22.0
        self.response_timeout_seconds = 100.0

    def _worker_command(self):
        return [sys.executable, '-u', '-m', 'weskill.native_worker']

    @staticmethod
    def _write(worker, value):
        worker.stdin.write(json.dumps(value, ensure_ascii=True) + '\n')
        worker.stdin.flush()

    @staticmethod
    def _read(worker, timeout):
        with selectors.DefaultSelector() as selector:
            selector.register(worker.stdout, selectors.EVENT_READ)
            if not selector.select(timeout):
                raise TimeoutError('Native worker response timed out')
        line = worker.stdout.readline()
        if not line:
            raise EOFError('Native worker disconnected')
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError('Invalid native worker frame')
        return value

    @staticmethod
    def _stop_unready(worker):
        # The protocol has not accepted any operation; no business scripts exist.
        worker.stdin.close()
        try:
            worker.wait(timeout=3)
        except subprocess.TimeoutExpired:
            worker.terminate()
            try:
                worker.wait(timeout=3)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=3)
        worker.stdout.close()

    def _ensure_worker(self):
        if self._worker is not None and self._worker.poll() is None:
            return self._worker
        if self._worker is not None:
            self._retained_workers.append(self._worker)
            self._worker = None
        for attempt in (1, 2):
            self.connection_attempts = attempt
            worker = subprocess.Popen(self._worker_command(), stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, text=True, bufsize=1)
            try:
                self._write(worker, {'pid': self.pid, 'shim_path': str(self.shim_path),
                    'state_dir': str(self.state_dir / 'native'),
                    'allowed_recipients': sorted(self.allowed_recipients)})
                ready = self._read(worker, self.startup_timeout_seconds)
                if ready.get('ready') is True:
                    self._worker = worker
                    return worker
                if ready.get('error_code') != 'connection_timeout':
                    raise RuntimeError(ready.get('error', 'Native worker initialization failed'))
            except (TimeoutError, EOFError):
                pass  # No operation has been sent, so replacing this worker is safe.
            except BaseException:
                self._stop_unready(worker)
                raise
            self._stop_unready(worker)
        raise NativeConnectionTimeout(
            'Native connection timed out in two fresh workers before any business '
            'request was sent; reconnect MCP and preserve sending records.')

    @property
    def draining_workers(self):
        return sum(worker.poll() is None for worker in self._retained_workers)

    @staticmethod
    def _drain(worker):
        try:
            for _ in worker.stdout:
                pass
            worker.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        finally:
            worker.stdout.close()

    def _retire(self, worker):
        self._retained_workers.append(worker)
        try:
            worker.stdin.close()
        except OSError:
            pass
        # Drain late results and let the worker finish and exit by itself.
        threading.Thread(target=self._drain, args=(worker,), daemon=True).start()

    def close_idle_workers(self):
        if self._worker is not None:
            self._retire(self._worker)
            self._worker = None
        for worker in self._retained_workers:
            try:
                worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass  # A possibly pending native task is never forcibly killed.

    def _run(self, mode, parameters):
        started = time.monotonic()
        request_id = uuid.uuid4().hex
        operation_sent = False
        worker = None
        stage = 'connection.worker'
        response = {'status': 'not_submitted', 'result': None,
                    'delivery_confirmed': False, 'errors': []}
        try:
            worker = self._ensure_worker()
            stage = 'native.worker_request'
            # Even a partial write is an uncertain submission. Never retry it.
            operation_sent = True
            self._write(worker, {'id': request_id, 'mode': mode, 'parameters': parameters})
            frame = self._read(worker, self.response_timeout_seconds)
            if frame.get('id') != request_id or not isinstance(frame.get('response'), dict):
                raise ValueError('Native worker response does not match the request')
            response.update(frame['response'])
        except Exception as error:
            response.update(status='unknown' if operation_sent else 'not_submitted',
                            error_code='connection_timeout' if isinstance(error, NativeConnectionTimeout)
                            else 'native_worker_failed', failure_stage=stage,
                            errors=[f'{type(error).__name__}: {error}'])
            if operation_sent and worker is not None:
                # A native task might still own callbacks. Retain the live process;
                # do not kill it, reuse its stream, or resubmit the operation.
                self._retire(worker)
                self._worker = None
        response.setdefault('diagnostics', {}).update(
            worker_attempts=self.connection_attempts,
            isolation='native_worker', total_seconds=round(time.monotonic() - started, 3))
        _save_private(self.state_dir / f'request-{request_id}.json', {
            'mode': mode, 'response': response,
            'worker_lifetime': 'retained_after_possible_submission'})
        return response
