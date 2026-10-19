import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { cli, metadata, root } from '../../lib/runtime.mjs';

function invoke(args, env = {}) {
  return spawnSync(process.execPath, [cli, ...args], {
    encoding: 'utf8', env: { ...process.env, ...env }, shell: false,
  });
}
function temporary(t) {
  const folder = mkdtempSync(path.join(os.tmpdir(), 'weskill npm '));
  t.after(() => rmSync(folder, { recursive: true, force: true }));
  return folder;
}

test('version/help and generic MCP configuration work without Python or WeChat', () => {
  assert.equal(invoke(['--version']).stdout.trim(), metadata.version);
  assert.match(invoke(['--help']).stdout, /install codex/);
  const output = invoke(['config', '--diagnostics', '--data-dir', '/tmp/with spaces']);
  assert.equal(output.status, 0, output.stderr);
  const server = JSON.parse(output.stdout).mcpServers.weskill;
  assert.equal(server.command, process.execPath);
  assert.deepEqual(server.args, [cli, 'mcp', '--diagnostics', '--data-dir', '/tmp/with spaces']);
});

test('invalid command/input is nonzero and never writes MCP stdout', () => {
  for (const args of [['unknown'], ['mcp', '--nonexistent'], ['install', 'unknown'], ['skills']]) {
    const output = invoke(args);
    assert.notEqual(output.status, 0);
    assert.equal(output.stdout, '');
    assert.match(output.stderr, /weSkill:/);
  }
});

test('all five portable Skills copy from the npm bundle and preserve local edits', t => {
  const destination = path.join(temporary(t), 'agent skills');
  assert.equal(invoke(['skills', '--dir', destination]).status, 0);
  assert.equal(readdirSync(destination).length, 5);
  const file = path.join(destination, 'weskill/SKILL.md');
  const expected = readFileSync(path.join(root, 'plugins/weskill/skills/weskill/SKILL.md'), 'utf8');
  assert.equal(readFileSync(file, 'utf8'), expected);
  assert.equal(invoke(['skills', '--dir', destination]).status, 0);
  writeFileSync(file, 'local instruction');
  assert.notEqual(invoke(['skills', '--dir', destination]).status, 0);
  assert.equal(readFileSync(file, 'utf8'), 'local instruction');
  assert.equal(invoke(['skills', '--dir', destination, '--force']).status, 0);
  assert.equal(readFileSync(file, 'utf8'), expected);
});

for (const agent of ['codex', 'claude']) {
  test(`${agent} registers stdio and installs the bundled plugin without invoking a shell`, t => {
    const folder = temporary(t), log = path.join(folder, 'calls.jsonl');
    const executable = path.join(folder, agent);
    writeFileSync(executable, `#!${process.execPath}\n` +
      `require('fs').appendFileSync(process.env.WESKILL_TEST_LOG, JSON.stringify(process.argv.slice(2))+'\\n');\n`, { mode: 0o755 });
    const output = invoke(['install', agent, '--diagnostics'], {
      PATH: folder + path.delimiter + process.env.PATH,
      WESKILL_TEST_LOG: log,
    });
    assert.equal(output.status, 0, output.stderr);
    const calls = readFileSync(log, 'utf8').trim().split('\n').map(x => JSON.parse(x));
    assert.equal(calls.length, 3);
    const divider = calls[0].indexOf('--');
    assert.deepEqual(calls[0].slice(divider+1), [process.execPath, cli, 'mcp', '--diagnostics']);
    assert.deepEqual(calls[0].slice(0, divider), agent === 'codex'
      ? ['mcp', 'add', 'weskill']
      : ['mcp', 'add', '--transport', 'stdio', '--scope', 'user', 'weskill']);
    assert.deepEqual(calls[1], ['plugin', 'marketplace', 'add', root]);
    assert.deepEqual(calls[2], ['plugin', agent === 'codex' ? 'add' : 'install', 'weskill@weskill-local']);
  });
}

test('stdio process forwards termination to its owned server child', async t => {
  const { spawn } = await import('node:child_process');
  const { once } = await import('node:events');
  const { pathToFileURL } = await import('node:url');
  const folder = temporary(t), marker = path.join(folder, 'terminated');
  const childCode = `process.on('SIGTERM',()=>{require('fs').writeFileSync(${JSON.stringify(marker)},'done');process.exit(0)});console.log(process.pid);setInterval(()=>{},1000);`;
  const code = `import {serve} from ${JSON.stringify(pathToFileURL(path.join(root, 'lib/runtime.mjs')).href)};await serve(process.execPath,['-e',${JSON.stringify(childCode)}]);`;
  const wrapper = spawn(process.execPath, ['--input-type=module', '-e', code], { stdio: ['ignore', 'pipe', 'pipe'] });
  t.after(() => { if (wrapper.exitCode === null) wrapper.kill('SIGTERM'); });
  const [data] = await once(wrapper.stdout, 'data');
  const childPid = Number(data.toString().trim());
  assert(Number.isInteger(childPid) && childPid > 0);
  const ended = once(wrapper, 'exit');
  wrapper.kill('SIGTERM');
  await ended;
  assert.equal(readFileSync(marker, 'utf8'), 'done');
  assert.throws(() => process.kill(childPid, 0), { code: 'ESRCH' });
});
