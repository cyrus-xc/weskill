#!/usr/bin/env node
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { parseArgs } from 'node:util';
import { root, metadata, execute, serve, ensureRuntime, connection } from '../lib/runtime.mjs';

const help = `weSkill ${metadata.version} — Linux WeChat Skills + local MCP

npm install -g weskill
weskill setup                     Prepare Python 3.12+ and the native bridge
weskill install codex             Register MCP and install five Codex Skills
weskill install claude            Register MCP and install five Claude Skills
weskill config                    Print generic MCP JSON for other clients
weskill skills --dir <directory>  Copy Skills to another agent's skills folder
weskill mcp                       Start the stdio MCP server
weskill service start|status|stop Manage the shared local execution service

Options: --python <path>  --data-dir <path>  --diagnostics
Native operations: Linux ARM64, supported WeChat build; see README.
`;

function copySkills(destination, overwrite) {
  const source = path.join(root, 'plugins/weskill/skills');
  // Check the whole destination first; conflicting local edits are not lost.
  function check(folder, relative = '') {
    for (const item of readdirSync(folder, { withFileTypes: true })) {
      const rel = path.join(relative, item.name), from = path.join(folder, item.name);
      if (item.isDirectory()) check(from, rel);
      else {
        const target = path.join(destination, rel);
        if (!overwrite && existsSync(target) && !readFileSync(target).equals(readFileSync(from)))
          throw new Error(`Local file differs: ${target}. Use --force to replace packaged Skill files.`);
      }
    }
  }
  check(source);
  mkdirSync(destination, { recursive: true });
  cpSync(source, destination, { recursive: true, force: true });
  console.log(`Installed five weSkill Skills into ${destination}`);
}

async function main() {
  const { values: options, positionals } = parseArgs({ allowPositionals: true, options: {
    help: { type: 'boolean', short: 'h' }, version: { type: 'boolean', short: 'v' },
    diagnostics: { type: 'boolean' }, python: { type: 'string' }, 'data-dir': { type: 'string' },
    dir: { type: 'string' }, force: { type: 'boolean' }, 'client-path': { type: 'string' },
    'wechat-pid': { type: 'string' },
  } });
  if (options.version) { console.log(metadata.version); return; }
  const [command, target, ...extra] = positionals;
  if (options.help || !command) { console.log(help); return; }
  if (extra.length) throw new Error(`Unexpected arguments: ${extra.join(' ')}`);
  if (!['install', 'service'].includes(command) && target) throw new Error(`Unexpected argument: ${target}`);
  if (command === 'config') {
    console.log(JSON.stringify({ mcpServers: { weskill: connection(options) } }, null, 2));
  } else if (command === 'skills') {
    if (!options.dir) throw new Error('Use weskill skills --dir <your agent skills directory>.');
    copySkills(path.resolve(options.dir), options.force);
  } else if (command === 'install') {
    if (!['codex', 'claude'].includes(target)) throw new Error('Choose weskill install codex or weskill install claude. Other agents: weskill config / weskill skills --dir.');
    const server = connection(options);
    if (target === 'codex') {
      execute('codex', ['mcp', 'add', 'weskill', '--', server.command, ...server.args]);
      execute('codex', ['plugin', 'marketplace', 'add', root]);
      execute('codex', ['plugin', 'add', 'weskill@weskill-local']);
    } else {
      execute('claude', ['mcp', 'add', '--transport', 'stdio', '--scope', 'user', 'weskill', '--', server.command, ...server.args]);
      execute('claude', ['plugin', 'marketplace', 'add', root]);
      execute('claude', ['plugin', 'install', 'weskill@weskill-local']);
    }
  } else if (command === 'setup') {
    const loc = ensureRuntime(options);
    console.log(`weSkill ${metadata.version} ready: ${loc.runtime}`);
  } else if (command === 'mcp') {
    const loc = ensureRuntime(options);
    const args = ['-m', 'weskill'];
    if (options['client-path']) args.push('--client-path', options['client-path']);
    if (!options.diagnostics) args.push('--enable-experimental-hooks', '--native-shim', loc.shim, '--state-dir', loc.state);
    if (options['wechat-pid']) args.push('--wechat-pid', options['wechat-pid']);
    // stdin/stdout belong exclusively to MCP; bootstrap writes only stderr.
    await serve(loc.python, args);
  } else if (command === 'service') {
    if (!['start', 'status', 'stop'].includes(target)) throw new Error('Choose weskill service start, status or stop.');
    const loc = ensureRuntime(options);
    execute(loc.python, [path.join(root, 'scripts/run_local_mcp.py'), '--service', target,
      '--native-shim', loc.shim, '--state-dir', loc.state]);
  } else {
    throw new Error(`Unknown command: ${command}. Run weskill --help.`);
  }
}

main().catch(error => { console.error(`weSkill: ${error.message}`); process.exitCode = 1; });
