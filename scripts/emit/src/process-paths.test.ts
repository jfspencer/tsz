import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { execFileSync } from 'node:child_process';
import { COMPILER_SCOPE, compilerFileSystem, compilerInvocation, compilerPath, compilerProcessStatus } from './process-paths.js';
import { CliTranspiler } from './cli-transpiler.js';
import { resolvePinnedOracle } from './oracle.js';

test('stable native process paths and exit identity', { skip: process.platform !== 'linux' }, async () => {
const scopes: string[] = [];
try {
  const outputs: Buffer[] = [];
  for (let index = 0; index < 2; index++) {
    const scope = fs.mkdtempSync(path.join(os.tmpdir(), 'tsz-process-paths-'));
    scopes.push(scope);
    const cwd = path.join(scope, 'cwd');
    fs.mkdirSync(cwd);
    fs.writeFileSync(path.join(scope, 'parent.txt'), 'raw\r\n');
    fs.symlinkSync('../parent.txt', path.join(cwd, 'link.txt'));
    const script = path.join(cwd, 'input.cjs');
    fs.writeFileSync(script, `const fs = require('node:fs');
      fs.writeFileSync('out.js', JSON.stringify([process.cwd(), __filename, fs.realpathSync('link.txt'), fs.readFileSync('link.txt', 'utf8')]));`);
    const invocation = compilerInvocation(process.execPath, [script], scope, cwd, 1);
    assert.ok(invocation.statusPath);
    execFileSync(invocation.binary, invocation.args);
    assert.deepEqual(compilerProcessStatus(invocation.statusPath), { code: 0, signal: null });
    outputs.push(fs.readFileSync(path.join(cwd, 'out.js')));
    const vfs = compilerFileSystem(() => scope)!;
    assert.equal(vfs.readFile(`${COMPILER_SCOPE}/cwd/link.txt`), 'raw\r\n');
    assert.equal(vfs.readFile(`${COMPILER_SCOPE}/cwd/missing.ts`), null);
    assert.equal(vfs.readFile(`${COMPILER_SCOPE}/cwd`), null);
    assert.equal(vfs.fileExists(`${COMPILER_SCOPE}/cwd`), false);
    assert.equal(vfs.directoryExists(`${COMPILER_SCOPE}/cwd`), true);
    assert.equal(vfs.realpath(`${COMPILER_SCOPE}/cwd/link.txt`), `${COMPILER_SCOPE}/parent.txt`);
    assert.equal(vfs.readFile('/outside-the-fixture/missing.ts'), undefined);
    assert.deepEqual(vfs.getAccessibleEntries(`${COMPILER_SCOPE}/cwd/missing`), { files: [], directories: [] });
    assert.deepEqual(JSON.parse(outputs[index].toString()), [
      `${COMPILER_SCOPE}/cwd`, `${COMPILER_SCOPE}/cwd/input.cjs`, `${COMPILER_SCOPE}/parent.txt`, 'raw\r\n',
    ]);
    for (const [source, status] of [
      ['process.exit(143)', { code: 143, signal: null }],
      ["process.kill(process.pid, 'SIGTERM')", { code: null, signal: 'SIGTERM' }],
    ] as const) {
      fs.writeFileSync(script, source);
      fs.unlinkSync(invocation.statusPath);
      execFileSync(invocation.binary, invocation.args);
      assert.deepEqual(compilerProcessStatus(invocation.statusPath), status);
    }
    assert.throws(() => compilerPath(path.join(scope, '..', 'escaped.ts'), scope), /escapes invocation/);
    fs.writeFileSync(invocation.statusPath, '{}');
    assert.throws(() => compilerProcessStatus(invocation.statusPath), /invalid compiler process status/);
    const literal = path.join(scope, 'factory');
    const args = compilerInvocation('/bin/true', ['--jsxFactory', literal, '--outDir', cwd, script], scope, cwd, 1).args;
    assert.equal(args[args.indexOf('--jsxFactory') + 1], literal, 'non-path option values remain authored');
    assert.equal(args[args.indexOf('--outDir') + 1], `${COMPILER_SCOPE}/cwd`);
  }
  assert.deepEqual(outputs[0], outputs[1], 'parallel invocation roots produce identical visible paths');

  const oracle = resolvePinnedOracle();
  const runners = [0, 1].map(() => new CliTranspiler(10000, {
    binaryPath: oracle.binaryPath, label: 'typescript7-path-contract', diagnosticWitnessProvider: 'typescript-7-api',
  }));
  try {
    const results = await Promise.all(runners.map(runner => runner.transpile('', 2, 1, {
      jsx: 'react-jsxdev', sourceFiles: [{ name: 'input.tsx', content: 'export const value = <div/>;\n' }],
    })));
    assert.ok(results[0].jsProducts.length > 0);
    assert.deepEqual(results[0], results[1], 'native raw JSX output and diagnostic witnesses survive distinct host staging roots');
    assert.ok(results[0].jsProducts[0].content.includes(`${COMPILER_SCOPE}/cwd/input.tsx`));
    assert.ok(results[0].outcome.diagnosticWitnesses?.length);
  } finally {
    runners.forEach(runner => runner.terminate());
  }
} finally {
  scopes.forEach(scope => fs.rmSync(scope, { recursive: true, force: true }));
}
});
