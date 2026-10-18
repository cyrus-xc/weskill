"""Launch the local MCP using an operator-maintained private allowlist."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--config', type=Path, default=ROOT / '.state/local-targets.json')
parser.add_argument('--native-shim', type=Path,
                    default=ROOT / 'native/build/libreadonly-executor-shim.so')
parser.add_argument('--state-dir', type=Path, default=ROOT / '.state/operations')
options = parser.parse_args()
config_path = options.config.expanduser().resolve()
if not config_path.is_file():
    parser.error('Missing private configuration; copy examples/local-targets.example.json first')
try:
    recipients = json.loads(config_path.read_text())['allowed_recipients']
    if not isinstance(recipients, list) or any(not isinstance(item, str) for item in recipients):
        raise ValueError('allowed_recipients must be a list of verified internal IDs')
except (KeyError, ValueError) as error:
    parser.error(f'Invalid private configuration: {error}')
args = [sys.executable, '-m', 'wechat_mcp', '--enable-experimental-hooks',
        '--native-shim', str(options.native_shim.expanduser().resolve()),
        '--state-dir', str(options.state_dir.expanduser().resolve())]
for recipient in recipients:
    args += ['--allow-recipient', recipient]
os.execv(sys.executable, args)
