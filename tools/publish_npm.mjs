// Publish once. A retry accepts an existing version only if its bytes match.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { metadata } from '../lib/runtime.mjs';
const archive = `dist/weskill-${metadata.version}.tgz`;
const response = await fetch(`https://registry.npmjs.org/${metadata.name}/${metadata.version}`);
if (response.ok) {
  const published = await response.json();
  const integrity = 'sha512-' + createHash('sha512').update(readFileSync(archive)).digest('base64');
  assert.equal(published.dist.integrity, integrity, 'This version exists with different bytes; do not overwrite or move its tag.');
  console.log(`${metadata.name}@${metadata.version} already published with identical bytes`);
} else {
  assert.equal(response.status, 404, `Registry check failed: HTTP ${response.status}`);
  const result = spawnSync('npm', ['publish', archive, '--access', 'public', '--ignore-scripts'], { stdio: 'inherit', shell: false });
  if (result.error) throw result.error;
  process.exitCode = result.status ?? 1;
}
