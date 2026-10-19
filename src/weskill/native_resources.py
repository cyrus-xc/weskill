"""Reuse the executor bridge; release only provably finished business agents.

The bridge owns the native task counters and capture. A business agent can be
unloaded once the executor has no live task and its native completion owner has
called destroy. Uncertain agents remain loaded, with working RPC handles, until
that condition becomes observable. Worker shutdown eternalizes anything still
possibly referenced by native code.
"""
from importlib.resources import files
import json


class NativeResources:
    def __init__(self, owner):
        self.owner = owner
        self.bridge = None
        self.pending = []
        self.created = 0
        self.released = 0
        self.closed = False

    def ensure_bridge(self, session):
        if self.closed:
            raise RuntimeError('Native resources are closed')
        if self.bridge is None:
            source = 'rpc.exports = {};\n' + files('weskill').joinpath('assets/executor_bridge.js').read_text()
            bridge = session.create_script(source)
            self.bridge = bridge
            self.owner._scripts.append(bridge)
            try:
                bridge.load()
                self.owner._rpc(bridge, 'setup', str(self.owner.shim_path))
            except BaseException:
                # Setup never posts a native callback. It is safe to dispose
                # this incomplete bridge and allow an explicit fresh attempt.
                bridge.unload()
                self.owner._scripts.remove(bridge)
                self.bridge = None
                raise
        return self.bridge

    def create_agent(self, session, source):
        module = json.dumps(self.owner.shim_path.name)
        source = f'const bridgeKeepalive = {{module: Process.getModuleByName({module})}};\n' + source
        script = session.create_script(source)
        self.owner._scripts.append(script)
        self.created += 1
        return script

    def _idle(self):
        if self.bridge is None:
            return True
        state = self.owner._rpc(self.bridge, 'bridge_status')
        return (state.get('idle') is True and int(state.get('live', 0)) == 0
                and int(state.get('allocations', 0)) == int(state.get('frees', 0)))

    @staticmethod
    def _finished(state):
        return bool(state and state.get('completed') and state.get('destroyed'))

    def _unload(self, script):
        script.unload()
        self.owner._scripts.remove(script)
        self.released += 1

    def finish(self, script, submitted, cleanup_ok, state):
        if not cleanup_ok:
            self.pending.append((script, False))
            return
        if (not submitted or self._finished(state)) and self._idle():
            self._unload(script)
        else:
            self.pending.append((script, True))

    def reap(self):
        if not self.pending or not self._idle():
            return
        kept = []
        for script, can_reap in self.pending:
            if not can_reap:
                kept.append((script, False))
                continue
            try:
                state = self.owner._rpc(script, 'status')
                if self._finished(state):
                    self._unload(script)
                else:
                    kept.append((script, True))
            except Exception:
                # A failed status read is not evidence that native owners died.
                kept.append((script, True))
        self.pending = kept

    def snapshot(self):
        return {'policy': 'shared_executor_bridge; release_completed_agents',
                'resident_scripts': len(self.owner._scripts),
                'pending_agents': len(self.pending), 'agents_created': self.created,
                'agents_released': self.released, 'bridge_reused': self.bridge is not None}

    def close(self):
        if self.closed:
            return
        self.closed = True
        # With no business agent left, every posted task has already passed
        # the idle+destroy proof in finish/reap. No native owner retains capture.
        if not self.pending and self.owner._scripts == [self.bridge]:
            self.bridge.unload()
            self.owner._scripts.clear()
            self.bridge = None
            return
        errors = []
        for script in list(self.owner._scripts):
            try:
                script.eternalize()
            except Exception as error:
                errors.append(f'{type(error).__name__}: {error}')
        if errors:
            self.owner._unsafe = 'Could not retain all pending native resources: ' + '; '.join(errors)
