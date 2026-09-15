import { createHash } from 'node:crypto';
import type { EmitProduct, CompilerOutcome } from './canonical-products.js';
import type { TranspileResult } from './cli-transpiler.js';

/** A hash of the original emitted bytes, with path and multiplicity preserved. */
export interface ProductEvidence {
  path: string;
  byteLength: number;
  sha256: string;
}

export type InvocationEvidence =
  | {
      state: 'observed';
      outcome: Omit<CompilerOutcome, 'diagnosticWitnesses'> & { diagnosticWitnesses: NonNullable<CompilerOutcome['diagnosticWitnesses']> | null };
      jsProducts: ProductEvidence[];
      dtsProducts: ProductEvidence[];
    }
  | { state: 'unavailable'; reason: 'timeout' | 'crash'; error: string }
  | { state: 'not-run'; reason: 'unsupported' | 'not-started' };

/** Stable JSON field ordering; array order (including diagnostic order) matters. */
export function canonicalJson(value: unknown): string {
  return JSON.stringify(value, (_key, item: unknown) => {
    if (item !== null && typeof item === 'object' && !Array.isArray(item)) {
      const record = item as Record<string, unknown>;
      return Object.fromEntries(Object.keys(record).sort().map(key => [key, record[key]]));
    }
    return item;
  }).replace(/[\u007f-\uffff]/g, character =>
    `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`);
}

function sha256(value: string | Buffer): string {
  return `sha256:${createHash('sha256').update(value).digest('hex')}`;
}

function productEvidence(products: readonly EmitProduct[]): ProductEvidence[] {
  return products.map(product => {
    // The adapter's Latin-1 string is a lossless byte container, not UTF-8 text.
    const bytes = Buffer.from(product.content, 'latin1');
    return { path: product.path, byteLength: bytes.length, sha256: sha256(bytes) };
  }).sort((left, right) => {
    const a = `${left.path}\0${left.sha256}\0${left.byteLength}`;
    const b = `${right.path}\0${right.sha256}\0${right.byteLength}`;
    return a < b ? -1 : a > b ? 1 : 0;
  });
}

/** Missing diagnostic witnesses are unknown, never an empty diagnostic list. */
export function invocationEvidence(result: PromiseSettledResult<TranspileResult>): InvocationEvidence {
  if (result.status === 'rejected') {
    const error = result.reason instanceof Error ? result.reason.message : String(result.reason);
    return { state: 'unavailable', reason: error.startsWith('TIMEOUT:') ? 'timeout' : 'crash', error };
  }
  const { outcome, jsProducts, dtsProducts } = result.value;
  return {
    state: 'observed',
    outcome: {
      exitCode: outcome.exitCode,
      diagnosticCodes: outcome.diagnosticCodes,
      diagnosticWitnesses: outcome.diagnosticWitnesses ?? null,
    },
    jsProducts: productEvidence(jsProducts),
    dtsProducts: productEvidence(dtsProducts),
  };
}

export function detailRowsFingerprint(results: Array<Record<string, unknown>>): string {
  const rows = results.map(result => ({
    // Include payload evidence even when match flags and summaries do not change.
    artifactState: result.artifactState ?? null,
    baselineFile: result.baselineFile ?? null,
    dtsError: result.dtsError ?? null,
    dtsMatch: result.dtsMatch ?? null,
    dtsProductError: result.dtsProductError ?? null,
    dtsProductMatch: result.dtsProductMatch ?? null,
    dtsSelected: result.dtsSelected ?? null,
    dtsStatus: result.dtsStatus ?? null,
    jsError: result.jsError ?? null,
    jsMatch: result.jsMatch ?? null,
    jsProductError: result.jsProductError ?? null,
    jsProductMatch: result.jsProductMatch ?? null,
    jsSelected: result.jsSelected ?? null,
    jsStatus: result.jsStatus ?? null,
    name: result.name ?? null,
    oracleEvidence: result.oracleEvidence ?? null,
    outcomeError: result.outcomeError ?? null,
    outcomeMatch: result.outcomeMatch ?? null,
    testPath: result.testPath ?? null,
    tszEvidence: result.tszEvidence ?? null,
  })).sort((left, right) => {
    const leftKey = `${left.name ?? ''}\0${left.baselineFile ?? ''}\0${left.testPath ?? ''}`;
    const rightKey = `${right.name ?? ''}\0${right.baselineFile ?? ''}\0${right.testPath ?? ''}`;
    if (leftKey < rightKey) return -1;
    if (leftKey > rightKey) return 1;
    return 0;
  });
  return sha256(canonicalJson(rows));
}

