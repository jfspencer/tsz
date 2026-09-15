import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { detailRowsFingerprint, type InvocationEvidence } from './result-evidence.js';

const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'tsz-emit-evidence-'));
const runner = fileURLToPath(new URL('./runner.js', import.meta.url));
const binary = path.join(directory, 'candidate.mjs');
fs.writeFileSync(binary, `#!/usr/bin/env node
import fs from 'node:fs';
if (process.env.EVIDENCE_SCENARIO === 'timeout') {
  setInterval(() => {}, 1000);
} else if (process.env.EVIDENCE_SCENARIO === 'crash') {
  process.kill(process.pid, 'SIGTERM');
} else {
  fs.writeFileSync('observed.js', Buffer.from([0, 128, 255, 13, 10]));
  process.exit(3);
}
`, { mode: 0o755 });

try {
  for (const scenario of ['incomplete', 'timeout', 'crash']) {
    const reportPath = path.join(directory, `${scenario}.json`);
    const run = spawnSync(process.execPath, [runner,
      '--filter=ArrowFunction1', '--max=1', '--js-only', '--timeout=1000', '--concurrency=1',
      `--json-out=${reportPath}`,
    ], {
      encoding: 'utf8', timeout: 30_000,
      env: { ...process.env, TSZ_BIN: binary, EVIDENCE_SCENARIO: scenario },
    });
    assert.equal(run.status, 1, run.stderr + run.stdout);
    const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
    assert.equal(report.detailSchemaVersion, 3);
    assert.equal(report.results.length, 1);
    assert.equal(report.detailFingerprint, detailRowsFingerprint(report.results));
    const row = report.results[0];
    assert.equal(row.artifactState, scenario);
    const oracle: InvocationEvidence = row.oracleEvidence;
    assert.equal(oracle.state, 'observed', 'candidate failure must not discard the oracle observation');
    if (oracle.state === 'observed') assert.ok(oracle.jsProducts.length > 0);
    const candidate: InvocationEvidence = row.tszEvidence;
    if (scenario === 'incomplete') {
      assert.equal(candidate.state, 'observed');
      if (candidate.state === 'observed') {
        assert.equal(candidate.outcome.exitCode, 3);
        assert.equal(candidate.outcome.diagnosticWitnesses, null);
        assert.equal(candidate.jsProducts.length, 1);
        assert.equal(candidate.jsProducts[0].byteLength, 5);
      }
    } else {
      assert.equal(candidate.state, 'unavailable');
      if (candidate.state === 'unavailable') assert.equal(candidate.reason, scenario);
    }
  }
} finally {
  fs.rmSync(directory, { recursive: true, force: true });
}
console.log('emit-runner-evidence: incomplete products and surviving oracle observations retained');
