# Emit report evidence

Schema 3 reports retain `oracleEvidence` and `tszEvidence` on every row. The
comparison still uses each compiler's original products; reporting does not
change the invocation, normalize emitted bytes, or change the pass rules.

Each invocation has one of these states:

- `observed`: exit code, ordered diagnostic codes, structured diagnostic
  witnesses when available, and JS/DTS product manifests.
- `unavailable`: timeout or crash prevented the adapter from returning a
  result. This does not assert that the compiler wrote no files or diagnostics.
- `not-run`: an unsupported harness feature or failure before invocation.

An observed product contains its invocation-relative path, byte length, and
SHA-256 of its original bytes. Empty files, absent files, duplicate paths,
non-UTF-8 bytes, and line endings remain distinguishable. Product enumeration
order is insignificant; diagnostic order is significant. Both JS and DTS
manifests are retained even when only one surface was selected for scoring.

`diagnosticWitnesses: null` means identity is unknown. An empty array means the
provider supplied an empty diagnostic sequence. Witnesses retain the canonical
path, UTF-16 span, category, code, message chain, and related information from
the existing diagnostic adapter. These reports do not archive raw process
stdout/stderr; their scope is the canonical diagnostic and emitted-file
products. Missing witnesses cannot prove diagnostic parity.

The runner waits for both compiler invocations and retains either returned
result when its peer fails. A rejected invocation's partial files are currently
unavailable; they are never represented as a measured empty product set.

`detailFingerprint` now covers these payload records as well as the existing
status fields. It excludes elapsed time and sorts rows by stable identity.
Canonical JSON uses sorted object keys, preserved array order, and ASCII Unicode
escapes. The TypeScript producer and Python query tool share a cross-language
test, including non-ASCII text and lone surrogates. Historical schema 1/2
fingerprints remain readable under their original rules.

For before/after evidence, first reject duplicate or changed row key sets, then
compare each invocation's availability, outcome, and product manifest. Equal
failure counts or shortened error summaries are insufficient. Unavailable
observations and unknown diagnostic witnesses remain explicit limits even when
their records are unchanged. The existing regression-set gate still checks
status transitions, product parity, and oracle-clean diagnostic code growth;
it does not replace a full payload audit.
