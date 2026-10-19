"""Prove release requires native ownership completion, not just send success."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from native_standin import Session
from test_connection import Token
from weskill.backend import ExperimentalBackend


class NativeResourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.backend = ExperimentalBackend(123, '/nonexistent/fixture.so', self.tmp.name)
        self.backend._frida = SimpleNamespace(Cancellable=Token)
        self.backend._verify_binding = Mock()
        self.session = Session(result_kind='friend_profile_result')
        self.backend._ensure_session = Mock(return_value=self.session)
        timer = patch('weskill.backend.threading.Timer')
        timer.start()
        self.addCleanup(timer.stop)

    def query(self):
        return self.backend.get_friend_info(['fixture'])

    def test_many_queries_reuse_one_bridge_and_release_all_business_agents(self):
        for _ in range(25):
            self.assertEqual(self.query()['status'], 'client_success')
        bridges = [s for s in self.session.scripts if s.bridge]
        agents = [s for s in self.session.scripts if not s.bridge]
        self.assertEqual(len(bridges), 1)
        bridges[0].exports_sync.setup.assert_called_once()
        self.assertEqual(len(bridges[0].handlers), 0)
        self.assertTrue(all(s.unload.call_count == 1 for s in agents))
        self.assertEqual(self.backend._resources.snapshot()['resident_scripts'], 1)
        self.assertEqual(self.backend._resources.snapshot()['pending_agents'], 0)
        self.backend.close()
        bridges[0].unload.assert_called_once()
        bridges[0].eternalize.assert_not_called()

    def test_successful_send_keeps_callback_until_late_native_destroy_then_reaps(self):
        self.session.result_kind = 'text_send_result'
        self.session.destroyed = False
        sent = self.backend.send_text('fixture', 'text', 'once')
        self.assertEqual(sent['status'], 'client_success')
        original = self.session.agent
        original.unload.assert_not_called()
        original.state['destroyed'] = True
        self.session.destroyed = True
        self.session.result_kind = 'friend_profile_result'
        self.query()
        original.unload.assert_called_once()
        self.assertEqual(self.backend._resources.snapshot()['pending_agents'], 0)

    def test_executor_live_task_prevents_release_even_after_owner_destroy(self):
        self.query()
        agent = self.backend._resources.create_agent(self.session, 'rpc.exports = {};')
        self.session.counts.update(idle=False, live='1')
        self.backend._resources.finish(agent, True, True, {'completed': True, 'destroyed': True})
        agent.unload.assert_not_called()
        self.backend.close()
        agent.eternalize.assert_called_once()

    def test_failed_hook_cleanup_keeps_script_despite_completed_state(self):
        self.query()
        agent = self.backend._resources.create_agent(self.session, 'rpc.exports = {};')
        agent.state.update(completed=True, destroyed=True)
        self.backend._resources.finish(agent, True, False, agent.state)
        self.backend._resources.reap()
        agent.unload.assert_not_called()
        self.backend.close()
        agent.eternalize.assert_called_once()

    def test_setup_failure_unloads_unposted_bridge_and_allows_explicit_retry(self):
        original = self.session.create_script
        def create(source):
            script = original(source)
            if len(self.session.scripts) == 1:
                script.exports_sync.setup.side_effect = ValueError('fixture setup failure')
            return script
        self.session.create_script = create
        first = self.query()
        self.assertEqual(first['status'], 'not_submitted')
        self.assertEqual(self.session.business_submissions, 0)
        self.session.scripts[0].unload.assert_called_once()
        self.assertEqual(self.query()['status'], 'client_success')
