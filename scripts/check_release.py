"""Check Git-visible release files without staging, deleting or publishing them."""
from pathlib import Path
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    paths = subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
        cwd=ROOT,
    ).decode().split('\0')
    names = sorted(set(filter(None, paths)))
    errors = []
    forbidden = ('research/', '.state/', '.venv/', 'native/build/', 'build/', 'dist/')
    private_markers = []
    targets = ROOT / '.state/local-targets.json'
    if targets.exists():
        private_markers += json.loads(targets.read_text()).get('allowed_recipients', [])
    markers = ROOT / '.state/publication-private-markers.json'
    if markers.exists():
        private_markers += json.loads(markers.read_text())
    home_path = re.compile(r'(?<![\w/])/(?:home|Users)/[^\s\"\'<>]+')
    for name in names:
        if name.startswith(forbidden):
            errors.append(f'{name}: private/generated path is visible to Git')
        if name.startswith('scripts/') and name not in {
            'scripts/run_local_mcp.py', 'scripts/check_release.py'
        }:
            errors.append(f'{name}: experimental probe is visible to Git')
        path = ROOT / name
        if path.is_symlink():
            errors.append(f'{name}: symlink requires explicit release review')
            continue
        if not path.is_file():
            continue
        try:
            content = path.read_text()
        except UnicodeDecodeError:
            if path.suffix not in {'.png', '.jpg', '.webp'}:
                errors.append(f'{name}: unexpected binary in source release')
            continue
        if home_path.search(content):
            errors.append(f'{name}: contains an absolute personal home path')
        if any(isinstance(marker, str) and marker and marker in content
               for marker in private_markers):
            errors.append(f'{name}: contains a local private marker (value withheld)')
        if re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', content):
            errors.append(f'{name}: contains private key material')
        if path.suffix == '.json':
            try:
                json.loads(content)
            except ValueError:
                errors.append(f'{name}: invalid JSON')

    plugin = ROOT / 'plugins/wechat-mcp'
    for host in ('codex', 'claude'):
        manifest = plugin / f'.{host}-plugin/plugin.json'
        value = json.loads(manifest.read_text())
        if value.get('name') != 'wechat-mcp' or value.get('version') != '0.1.0':
            errors.append(f'{manifest.relative_to(ROOT)}: inconsistent plugin identity')
    required = [ROOT / '.agents/plugins/marketplace.json',
                ROOT / '.claude-plugin/marketplace.json',
                plugin / 'skills/wechat-mcp/SKILL.md', plugin / 'LICENSE',
                plugin / 'assets/logo.svg', plugin / 'skills/wechat-mcp/assets/logo.svg']
    for path in required:
        if not path.is_file():
            errors.append(f'{path.relative_to(ROOT)}: required release file is missing')
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print(f'PASS: {len(names)} Git-visible files; no configured private markers or excluded artifacts found.')
    print('This is a local preflight, not an exhaustive secret scan or a marketplace approval.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
