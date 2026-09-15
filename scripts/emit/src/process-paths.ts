import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

// Each invocation gets a private mount at this same path. No compiler sees the
// random host staging directory in its source filenames or generated literals.
export const COMPILER_SCOPE = '/tmp/tsz-emit-scope';
export const compilerPathMode = process.platform === 'linux' ? 'linux-bubblewrap' : 'host';
export const compilerScope = (physicalScope: string): string => compilerPathMode === 'host' ? physicalScope : COMPILER_SCOPE;
const pathFlags = new Set(['--baseUrl', '--outFile', '--outDir', '--declarationDir', '--rootDir', '--diagnostics-json']);

export function compilerPath(value: string, scope: string): string {
  if (compilerPathMode === 'host') return value;
  const relative = path.relative(scope, value);
  if (relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
    throw new Error(`compiler path escapes invocation scope: ${value}`);
  }
  return path.join(COMPILER_SCOPE, relative);
}

export function compilerInvocation(binary: string, args: string[], scope: string, cwd: string, rootCount: number) {
  if (compilerPathMode === 'host') return { binary, args, statusPath: undefined };
  fs.mkdirSync(COMPILER_SCOPE, { recursive: true });
  if (!fs.lstatSync(COMPILER_SCOPE).isDirectory()) throw new Error('compiler mount destination is not a directory');
  const statusPath = path.join(scope, '.compiler-process.json');
  const compilerArgs = args.map((arg, index) =>
    index >= args.length - rootCount || pathFlags.has(args[index - 1]) ? compilerPath(arg, scope) : arg);
  return {
    binary: 'bwrap',
    args: [
      '--bind', '/', '/', '--bind', scope, COMPILER_SCOPE,
      '--unshare-pid', '--die-with-parent', '--chdir', compilerPath(cwd, scope), '--',
      process.execPath, fileURLToPath(new URL('./process-observer.js', import.meta.url)),
      compilerPath(statusPath, scope), binary, ...compilerArgs,
    ],
    statusPath,
  };
}

/** A namespace wrapper exit is not evidence of the compiler's exit. */
export function compilerProcessStatus(statusPath: string): { code: number | null; signal: string | null } {
  const status: unknown = JSON.parse(fs.readFileSync(statusPath, 'utf8'));
  if (status === null || typeof status !== 'object') throw new Error('missing compiler process status');
  const value = status as Record<string, unknown>;
  if (Object.keys(value).sort().join(',') !== 'code,signal' ||
      !(value.code === null && typeof value.signal === 'string' ||
        Number.isInteger(value.code) && Number(value.code) >= 0 && Number(value.code) <= 255 && value.signal === null)) {
    throw new Error(`invalid compiler process status: ${JSON.stringify(status)}`);
  }
  return value as { code: number | null; signal: string | null };
}

/** Present the same mounted paths through the pinned native API's VFS hooks. */
export function compilerFileSystem(currentScope: () => string | undefined) {
  if (compilerPathMode === 'host') return undefined;
  const hostPath = (name: string): string | undefined => {
    const scope = currentScope();
    if (scope === undefined) return undefined;
    const relative = path.relative(COMPILER_SCOPE, name);
    if (relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) return undefined;
    return path.join(scope, relative);
  };
  const stat = (name: string) => {
    const host = hostPath(name);
    return host === undefined ? undefined : fs.statSync(host, { throwIfNoEntry: false }) ?? null;
  };
  return {
    fileExists(name: string) { const info = stat(name); return info === undefined ? undefined : info?.isFile() ?? false; },
    directoryExists(name: string) { const info = stat(name); return info === undefined ? undefined : info?.isDirectory() ?? false; },
    readFile(name: string) {
      const host = hostPath(name);
      if (host === undefined) return undefined;
      return fs.statSync(host, { throwIfNoEntry: false })?.isFile() ? fs.readFileSync(host, 'utf8') : null;
    },
    getAccessibleEntries(name: string) {
      const host = hostPath(name);
      if (host === undefined) return undefined;
      const entries = { files: [] as string[], directories: [] as string[] };
      if (!fs.statSync(host, { throwIfNoEntry: false })?.isDirectory()) return entries;
      for (const child of fs.readdirSync(host).sort((a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b)))) {
        const info = fs.statSync(path.join(host, child), { throwIfNoEntry: false });
        if (info?.isDirectory()) entries.directories.push(child);
        else if (info?.isFile()) entries.files.push(child);
      }
      return entries;
    },
    realpath(name: string) {
      const host = hostPath(name);
      if (host === undefined) return undefined;
      const resolved = physicalRealpath(host);
      const scope = currentScope()!;
      const relative = path.relative(scope, resolved);
      return relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)
        ? resolved : compilerPath(resolved, scope);
    },
  };
}

function physicalRealpath(name: string): string {
  try { return fs.realpathSync.native(name); }
  catch (error) {
    if (error instanceof Error && 'code' in error && (error.code === 'ENOENT' || error.code === 'ENOTDIR')) return name;
    throw error;
  }
}
