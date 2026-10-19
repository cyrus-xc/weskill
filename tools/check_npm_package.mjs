import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { metadata, root } from '../lib/runtime.mjs';

const npm = process.env.npm_execpath || process.env.WESKILL_NPM_CLI;
const args = ['pack', '--dry-run', '--json', '--ignore-scripts'];
const result = spawnSync(npm ? process.execPath : 'npm', npm ? [npm, ...args] : args,
  { cwd: root, encoding: 'utf8', shell: false });
assert.equal(result.status, 0, result.stderr);
const parsed = JSON.parse(result.stdout);
const pack = Array.isArray(parsed) ? parsed[0] : Object.values(parsed)[0];
const paths = new Set(pack.files.map(file => file.path));
for (const file of ['bin/weskill.mjs', 'lib/bootstrap.py', 'lib/runtime.mjs', 'pyproject.toml',
  'native/readonly_executor_shim.c', 'native/readonly_executor_shim.S', 'src/weskill/server.py',
  'src/weskill/assets/executor_bridge.js', '.agents/plugins/marketplace.json',
  '.claude-plugin/marketplace.json', 'plugins/weskill/.codex-plugin/plugin.json', `docs/releases/${metadata.version}.md`])
  assert(paths.has(file), `Missing runtime file: ${file}`);
const markerFile = path.join(root, '.state/publication-private-markers.json');
const markers = existsSync(markerFile) ? JSON.parse(readFileSync(markerFile, 'utf8')) : [];
for (const file of paths) {
  assert(!/(^|\/)(\.state|research|\.venv|__pycache__|node_modules|\.env)(\/|$)/.test(file), file);
  assert(!/\.(pyc|so|log|core)$/.test(file), file);
  assert(!/(INTEGRATION|ARCHITECTURE|CLOSEOUT)\.md$/.test(file), file);
  const bytes = readFileSync(path.join(root, file));
  if (!/\.(png|jpg|webp|gif)$/.test(file)) {
    const text = bytes.toString('utf8');
    assert(!/(?<![\w/])\/(?:home|Users)\/[^\s"'<>]+/.test(text), `${file}: personal path`);
    assert(!markers.some(marker => marker && text.includes(marker)), `${file}: local private marker`);
  }
}
const pythonVersion = /version = "([^"]+)"/.exec(readFileSync(path.join(root, 'pyproject.toml'), 'utf8'))[1];
assert.equal(metadata.version, pythonVersion);
for (const host of ['codex', 'claude']) {
  const plugin = JSON.parse(readFileSync(path.join(root, `plugins/weskill/.${host}-plugin/plugin.json`), 'utf8'));
  assert.equal(plugin.version, metadata.version);
}
if (process.env.RELEASE_TAG) assert.equal(process.env.RELEASE_TAG, `v${metadata.version}`);
console.log(`PASS: npm ${pack.name}@${pack.version}, ${paths.size} explicit files, no local state or private reports`);
