"""Isolated native protocol model: no Frida and no installed client access."""
from types import SimpleNamespace
from unittest.mock import Mock


class Script:
    def __init__(self, session, bridge):
        self.session, self.bridge = session, bridge
        self.handlers = []
        self.eternalize = Mock()
        self.unload = Mock()
        self.state = {'invoked': False, 'completed': False, 'destroyed': False,
                      'invocationCount': 0, 'completionCount': 0, 'errors': []}
        self.exports_sync = SimpleNamespace(setup=Mock(), submit_task=self.submit,
            prepare=lambda *args: 'fixture-task', bridge_status=lambda: dict(session.counts),
            status=lambda: dict(self.state), cleanup=Mock())

    def on(self, name, callback):
        self.handlers.append(callback)

    def off(self, name, callback):
        self.handlers.remove(callback)

    def load(self):
        pass

    def emit(self, payload):
        for callback in list(self.handlers):
            callback({'type': 'send', 'payload': payload}, None)

    def submit(self, task):
        self.session.counts['allocations'] += 1
        if task is None:
            self.session.counts['noopRuns'] += 1
            self.emit({'kind': 'executor_noop', 'tid': 42})
        else:
            self.session.business_submissions += 1
            if self.session.submission_error:
                raise self.session.submission_error
            current = self.session.agent
            current.state.update(invoked=True, completed=True,
                destroyed=self.session.destroyed, invocationCount=1, completionCount=1)
            current.emit({'kind': self.session.result_kind,
                          'result': {'success': True}, 'error': ''})
        self.session.counts['invokes'] += 1
        self.session.counts['frees'] += 1
        return 0


class Session:
    def __init__(self, *, destroyed=True, result_kind='text_send_result', submission_error=None):
        self.destroyed, self.result_kind, self.submission_error = destroyed, result_kind, submission_error
        self.scripts = []
        self.agent = None
        self.business_submissions = 0
        self.counts = {'idle': True, 'live': '0', 'invokes': 0, 'noopRuns': 0,
                       'allocations': 0, 'frees': 0, 'tid': '42'}

    def create_script(self, source):
        bridge = 'const queryExports = rpc.exports' in source
        script = Script(self, bridge)
        self.scripts.append(script)
        if not bridge:
            self.agent = script
        return script
