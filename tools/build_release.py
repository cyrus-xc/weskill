"""Build public Python and plugin archives; npm pack is run by the workflow."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import zipfile

root = Path(__file__).resolve().parents[1]
version = json.loads((root / 'package.json').read_text())['version']
subprocess.run([sys.executable, '-m', 'build', '--no-isolation'], cwd=root, check=True)
plugin = root / 'plugins/weskill'
with zipfile.ZipFile(root / f'dist/weskill-plugin-{version}.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
    for file in sorted(plugin.rglob('*')):
        if file.is_file():
            archive.write(file, file.relative_to(plugin))
patterns = [f'weskill-{version}.tgz', f'weskill-{version}.tar.gz',
            f'weskill-{version}-*.whl', f'weskill-plugin-{version}.zip']
artifacts = [file for pattern in patterns for file in sorted((root / 'dist').glob(pattern))]
assert len(artifacts) == 4, 'Expected npm, source, wheel and plugin archives'
for file in artifacts:
    if file.suffix == '.zip' or file.suffix == '.whl':
        with zipfile.ZipFile(file) as archive:
            names = archive.namelist()
    else:
        import tarfile
        with tarfile.open(file) as archive:
            names = archive.getnames()
    for name in names:
        assert not set(Path(name).parts) & {'.state', 'research', '.venv', '__pycache__'}, name
        assert not name.endswith(('INTEGRATION.md', 'ARCHITECTURE.md', 'CLOSEOUT.md')), name
(root / 'dist/SHA256SUMS').write_text(''.join(
    f'{hashlib.sha256(file.read_bytes()).hexdigest()}  {file.name}\n' for file in artifacts))
print('Built four release artifacts and SHA256SUMS')
