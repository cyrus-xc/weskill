"""Check that PID discovery cannot silently select an unrelated/second client."""
from pathlib import Path
import tempfile
import unittest
from weskill.identity import discover_client_pid

class DiscoveryTests(unittest.TestCase):
    def test_main_executable_only_and_ambiguity_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for pid, target in [(10, '/opt/wechat/wechat'), (11, '/opt/wechat/RadiumWMPF/runtime/WeChatAppEx'),
                                (12, '/tmp/wechat')]:
                (root / str(pid)).mkdir()
                (root / str(pid) / 'exe').symlink_to(target)
            self.assertEqual(discover_client_pid(root), 10)
            (root / '13').mkdir()
            (root / '13' / 'exe').symlink_to('/opt/wechat/wechat')
            with self.assertRaises(ValueError):
                discover_client_pid(root)
            (root / '13' / 'exe').unlink()
            (root / '10' / 'exe').unlink()
            with self.assertRaises(ValueError):
                discover_client_pid(root)
