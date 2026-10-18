"""Launch the local MCP and manage its shared same-user service."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--service', choices=['start', 'status', 'stop'])
parser.add_argument('--native-shim', type=Path,
                    default=ROOT / 'native/build/libreadonly-executor-shim.so')
parser.add_argument('--state-dir', type=Path, default=ROOT / '.state/operations')
options = parser.parse_args()
if options.service:
    from weskill.service_client import ServiceBackend
    service = ServiceBackend(None, options.native_shim.expanduser().resolve(),
                             options.state_dir.expanduser().resolve())
    action = {'start': service.ensure_service, 'status': service.get_service_status,
              'stop': service.stop_service}[options.service]
    import json
    print(json.dumps(action(), ensure_ascii=False))
    raise SystemExit(0)
args = [sys.executable, '-m', 'weskill', '--enable-experimental-hooks',
        '--native-shim', str(options.native_shim.expanduser().resolve()),
        '--state-dir', str(options.state_dir.expanduser().resolve())]
os.execv(sys.executable, args)
