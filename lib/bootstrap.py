"""Create the user-owned Python runtime; never attach to WeChat during setup."""
import argparse
import fcntl
import os
from pathlib import Path
import platform
import subprocess
import sys
import venv


def run(args):
    subprocess.run(args, check=True, stdout=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-root', required=True, type=Path)
    parser.add_argument('--runtime-dir', required=True, type=Path)
    parser.add_argument('--diagnostics', action='store_true')
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        parser.error('Python 3.12+ is required')
    if not args.diagnostics and (platform.system() != 'Linux' or platform.machine().lower() not in {'aarch64', 'arm64'}):
        parser.error('Native operations currently require Linux ARM64. Use --diagnostics for ELF diagnostics.')
    args.runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(args.runtime_dir, 0o700)
    marker = args.runtime_dir / ('diagnostics.ready' if args.diagnostics else 'native.ready')
    python = args.runtime_dir / 'venv/bin/python'
    shim = args.runtime_dir / 'libreadonly-executor-shim.so'
    # flock releases on process exit, including interruption. Concurrent MCP
    # launches never install dependencies into the same venv at the same time.
    with (args.runtime_dir / 'setup.lock').open('a') as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        if marker.is_file() and python.is_file() and (args.diagnostics or shim.is_file()):
            return
        base_marker = args.runtime_dir / 'diagnostics.ready'
        base_ready = base_marker.is_file() and python.is_file()
        if not python.is_file():
            venv.EnvBuilder(with_pip=True).create(args.runtime_dir / 'venv')
        print('weSkill: preparing the Python runtime...', file=sys.stderr, flush=True)
        if not base_ready:
            project = str(args.package_root.resolve()) + ('' if args.diagnostics else '[hooks]')
            run([str(python), '-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', project])
            base_marker.write_text('ready\n')
            os.chmod(base_marker, 0o600)
        elif not args.diagnostics:
            # Adding native dependencies must not uninstall files from a base
            # runtime that a diagnostic MCP process may already be importing.
            run([str(python), '-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', 'frida==16.7.19'])
        if not args.diagnostics:
            temporary = shim.with_suffix('.pending.so')
            run([os.environ.get('CC', 'cc'), '-std=c11', '-O2', '-fPIC', '-shared',
                 str(args.package_root / 'native/readonly_executor_shim.c'),
                 str(args.package_root / 'native/readonly_executor_shim.S'), '-o', str(temporary)])
            temporary.replace(shim)
        marker.write_text('ready\n')
        os.chmod(marker, 0o600)
        print('weSkill: runtime ready; WeChat was not attached.', file=sys.stderr, flush=True)


if __name__ == '__main__':
    main()
