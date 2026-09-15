import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import type { TranspileResult } from './cli-transpiler.js';
import type { DiagnosticWitness } from './diagnostic-witness.js';
import { detailRowsFingerprint, invocationEvidence } from './result-evidence.js';

const diagnostic: DiagnosticWitness = {
  path: 'renamed.ts', start: 4, length: 2, category: 'error', code: 'TS2322',
  text: 'é 🙂 \ud800', messageChain: [], relatedInformation: [],
};
const invocation: TranspileResult = {
  outcome: { exitCode: 3, diagnosticCodes: ['TS2322'], diagnosticWitnesses: [diagnostic] },
  jsProducts: [{ path: 'out/a.js', content: 'abc' }],
  dtsProducts: [],
};
const evidence = (value: TranspileResult) => invocationEvidence({ status: 'fulfilled', value });
const observed = evidence(invocation);
assert.equal(observed.state, 'observed');
if (observed.state !== 'observed') throw new Error('expected measured evidence');
assert.deepEqual(observed.jsProducts, [{
  path: 'out/a.js', byteLength: 3,
  sha256: 'sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
}]);
assert.deepEqual(observed.outcome.diagnosticWitnesses, [diagnostic]);

const row = { name: 'case', artifactState: 'incomplete', jsMatch: false, tszEvidence: observed };
const fingerprint = (value: TranspileResult) => detailRowsFingerprint([{ ...row, tszEvidence: evidence(value) }]);
const baseline = fingerprint(invocation);
const changes: TranspileResult[] = [
  { ...invocation, jsProducts: [{ path: 'out/a.js', content: 'abd' }] },
  { ...invocation, jsProducts: [{ path: 'out/b.js', content: 'abc' }] },
  { ...invocation, jsProducts: [] },
  { ...invocation, jsProducts: [...invocation.jsProducts, ...invocation.jsProducts] },
  { ...invocation, dtsProducts: invocation.jsProducts, jsProducts: [] },
  { ...invocation, outcome: { ...invocation.outcome, exitCode: 2 } },
  { ...invocation, outcome: { ...invocation.outcome, diagnosticWitnesses: undefined } },
  ...[
    { start: 5 }, { length: 3 }, { text: 'different' }, { path: 'other.ts' },
    { relatedInformation: [diagnostic] },
    { messageChain: [{ text: 'detail', code: 'TS2322', category: 'error' as const, next: [] }] },
  ].map(change => ({ ...invocation, outcome: {
    ...invocation.outcome, diagnosticWitnesses: [{ ...diagnostic, ...change }],
  } })),
];
for (const changed of changes) {
  assert.notEqual(fingerprint(changed), baseline, 'unchanged status cannot hide payload changes');
}
assert.notDeepEqual(
  evidence({ ...invocation, outcome: { exitCode: 3, diagnosticCodes: [] } }),
  evidence({ ...invocation, outcome: { exitCode: 3, diagnosticCodes: [], diagnosticWitnesses: [] } }),
  'unknown witnesses are distinct from a proven empty sequence',
);

const products = [...invocation.jsProducts, { path: 'out/z.js', content: '\x00\x80\xff\r\n' }];
assert.equal(
  fingerprint({ ...invocation, jsProducts: products }),
  fingerprint({ ...invocation, jsProducts: [...products].reverse() }),
  'filesystem enumeration order does not change product identity',
);
const binary = evidence({ ...invocation, jsProducts: [products[1]] });
assert.equal(binary.state, 'observed');
if (binary.state === 'observed') assert.equal(binary.jsProducts[0].byteLength, 5);
assert.notEqual(
  fingerprint({ ...invocation, jsProducts: [products[1]] }),
  fingerprint({ ...invocation, jsProducts: [{ ...products[1], content: '\x00\x80\xff\n' }] }),
  'line endings are emitted bytes, not harness normalization',
);
assert.notEqual(
  fingerprint({ ...invocation, outcome: { ...invocation.outcome, diagnosticWitnesses: [diagnostic, { ...diagnostic, start: 8 }] } }),
  fingerprint({ ...invocation, outcome: { ...invocation.outcome, diagnosticWitnesses: [{ ...diagnostic, start: 8 }, diagnostic] } }),
  'diagnostic order remains significant',
);
assert.deepEqual(invocationEvidence({ status: 'rejected', reason: new Error('TIMEOUT:tsz') }), {
  state: 'unavailable', reason: 'timeout', error: 'TIMEOUT:tsz',
});
assert.deepEqual(invocationEvidence({ status: 'rejected', reason: new Error('CRASH:tsz:SIGTERM') }), {
  state: 'unavailable', reason: 'crash', error: 'CRASH:tsz:SIGTERM',
});

// Exercise the independent Python consumer, including non-ASCII messages,
// lone surrogate escaping, nested key ordering, and UTF-16 row ordering.
const rows = [row, { ...row, name: '\ue000' }, { ...row, name: '🙂' }];
assert.equal(detailRowsFingerprint(rows), detailRowsFingerprint([...rows].reverse()));
assert.equal(detailRowsFingerprint(rows), detailRowsFingerprint(rows.map(item => ({ ...item, elapsed: 50 }))));
const queryPath = fileURLToPath(new URL('../query-emit.py', import.meta.url));
const python = spawnSync('python3', ['-c', `
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location('query_emit', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(module.emit_detail_row_fingerprint(json.load(sys.stdin)))
`, queryPath], { input: JSON.stringify({ detailSchemaVersion: 3, results: rows }), encoding: 'utf8' });
assert.equal(python.status, 0, python.stderr);
assert.equal(python.stdout.trim(), detailRowsFingerprint(rows));
console.log('emit-result-evidence: exact bytes, ordered diagnostics, unknown states, and cross-language fingerprints verified');
