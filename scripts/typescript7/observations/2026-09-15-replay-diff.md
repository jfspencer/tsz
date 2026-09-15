# Native replay observation comparison

The comparison boundary now verifies native input/result manifests and a new
candidate observation manifest, then reports every invocation's ordered
diagnostic headers and filesystem changes. This works independently of the
compiler foundation. Matching projections are not native-suite passes.

Production oracle: TypeScript 7.0.2, native commit
`2bd066d87f5bafd315be9f40889d0a60b9e58e0b`, corpus commit
`4d4f005c8541e0255a9d8791205fdce326e462bc`.

## Verification

- `scripts/safe-run.sh python3 -m unittest discover -s scripts/typescript7 -p 'test_*.py'`:
  **56 pass**, including 12 new comparison contracts. These cover exact binary
  and newline differences, missing/extra files, removed inputs, UTF-8 byte to
  UTF-16 span conversion, duplicate diagnostics, unsupported/timeouts/signals,
  missing structured output, unchanged writes, symlink limits, and corruption.
- `replay.py` against `7.0.2-result-capture-smoke` using TSZ binary SHA-256
  `26be1f11fbaa0a4c8ab4ccd5f491ef6aaf9a985241a7ef9b05295845a0baf1b4`:
  **21 invocations**, 11 process observations and 10 unsupported auxiliary
  invocations. Candidate capture SHA-256:
  `8ef20d07054904b10f12f170a56b12be667d24410928c9ff0d3c58b1c6e774e3`.
- `replay_diff.py`: **11 filesystem mismatches, 10 unavailable filesystem
  comparisons, 21 unavailable diagnostic-header/completion observations**.
  Every original input identity is present. The single 21-row difference shard
  hashes to `9fc0ced66a0a7a919d4b34881f397d5dfd86753d0a13496f999cacad039d822b`.

The primary invocations terminate during TSZ argument validation: native harness
options `noErrorTruncation` and `skipDefaultLibCheck` are valid in 7.0.2 but TSZ
reports TS5023. Their expected output files are absent. The adapter retains
these authored options and the raw rejection instead of silently dropping them.
This identifies an option-support gap before scanner parity can be measured
through these native fixtures.

Ignored artifacts: `artifacts/typescript7/7.0.2-replay-comparison/` and
`artifacts/typescript7/7.0.2-replay-diff/`, alongside the original native capture.
Both commands exit 1 because full native-suite parity remains unmeasured.
Native phase APIs, diagnostic chains/flags, emit events, traces, auxiliary
compilation and other test drivers remain unfinished.
