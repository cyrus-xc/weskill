import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { homedir } from 'node:os';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

export const root = fileURLToPath(new URL('../', import.meta.url));
export const metadata = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8'));
export const cli = path.join(root, 'bin/weskill.mjs');

export function execute(command, args, options = {}) {
  const result = spawnSync(command, args, { stdio: 'inherit', ...options, shell: false });
  if (result.error) throw new Error(`Cannot run ${command}: ${result.error.message}`);
  if (result.signal) throw new Error(`${command} stopped by ${result.signal}`);
  if (result.status !== 0) throw new Error(`${command} exited with status ${result.status}`);
}

export async function serve(command, args) {
  await new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: 'inherit', shell: false });
    const interrupt = () => child.kill('SIGINT');
    const terminate = () => child.kill('SIGTERM');
    process.on('SIGINT', interrupt);
    process.on('SIGTERM', terminate);
    const cleanup = () => {
      process.off('SIGINT', interrupt);
      process.off('SIGTERM', terminate);
    };
    child.on('error', error => { cleanup(); reject(error); });
    child.on('exit', (code, signal) => {
      cleanup();
      if (signal) process.exitCode = signal === 'SIGINT' ? 130 : 143;
      else process.exitCode = code ?? 1;
      resolve();
    });
  });
}

function sourceFiles(folder) {
  return readdirSync(folder, { withFileTypes: true }).flatMap(entry => {
    const file = path.join(folder, entry.name);
    if (entry.isDirectory()) return entry.name === '__pycache__' ? [] : sourceFiles(file);
    return /\.(py|js|json|c|S)$/.test(entry.name) ? [file] : [];
  });
}

export function locations(options = {}) {
  const base = path.resolve(options['data-dir'] || process.env.WESKILL_DATA_DIR ||
    path.join(process.env.XDG_DATA_HOME || path.join(homedir(), '.local/share'), 'weskill'));
  const hash = createHash('sha256');
  const files = [...sourceFiles(path.join(root, 'src/weskill')),
    path.join(root, 'native/readonly_executor_shim.c'), path.join(root, 'native/readonly_executor_shim.S'),
    path.join(root, 'lib/bootstrap.py'), path.join(root, 'pyproject.toml')].sort();
  for (const file of files) hash.update(path.relative(root, file)).update(readFileSync(file));
  const fingerprint = hash.digest('hex').slice(0, 16);
  const runtime = path.join(base, 'runtime', `${metadata.version}-${fingerprint}`);
  return { base, runtime, python: path.join(runtime, 'venv/bin/python'),
    shim: path.join(runtime, 'libreadonly-executor-shim.so'),
    state: path.join(base, 'state/operations'),
    ready: path.join(runtime, options.diagnostics ? 'diagnostics.ready' : 'native.ready') };
}

function findPython(selected) {
  const choices = selected ? [selected] : [process.env.WESKILL_PYTHON, 'python3.12', 'python3', 'python'].filter(Boolean);
  for (const candidate of choices) {
    const result = spawnSync(candidate, ['-c', 'import sys;sys.exit(0 if sys.version_info >= (3,12) else 1)'],
      { stdio: 'ignore', shell: false });
    if (!result.error && result.status === 0) return candidate;
  }
  throw new Error('Python 3.12+ is required. Install python3 and venv, or pass --python /path/to/python.');
}

export function ensureRuntime(options = {}) {
  const loc = locations(options);
  if (!existsSync(loc.ready) || !existsSync(loc.python) || (!options.diagnostics && !existsSync(loc.shim))) {
    const python = findPython(options.python);
    execute(python, [path.join(root, 'lib/bootstrap.py'), '--package-root', root,
      '--runtime-dir', loc.runtime, ...(options.diagnostics ? ['--diagnostics'] : [])],
    { stdio: ['ignore', process.stderr, process.stderr] });
  }
  return loc;
}

export function connection(options = {}) {
  const args = [cli, 'mcp'];
  if (options.diagnostics) args.push('--diagnostics');
  if (options['data-dir']) args.push('--data-dir', path.resolve(options['data-dir']));
  if (options.python) args.push('--python', options.python);
  for (const flag of ['client-path', 'wechat-pid']) if (options[flag]) args.push(`--${flag}`, options[flag]);
  return { command: process.execPath, args };
}
