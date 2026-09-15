# Native completed compiler results

Production oracle: TypeScript 7.0.2, native commit
`2bd066d87f5bafd315be9f40889d0a60b9e58e0b` and locked corpus commit
`4d4f005c8541e0255a9d8791205fdce326e462bc`.

The reporting overlay now pairs each captured compiler invocation with its
completed native result. It reads the existing diagnostic list, emit result,
output recorder and trace. No additional semantic query or baseline comparison
is performed by capture. Missing completed results remain explicit failures.

Verification:

- `scripts/safe-run.sh python3 -m unittest discover -s scripts/typescript7 -p 'test_*.py'`:
  **44 tests pass**, including injected native Go contracts for binary output,
  Unicode source byte spans, diagnostic chains/related information, and unchanged
  result objects. Integrity tests reject corrupted blobs, bad references,
  missing diagnostic arrays and duplicate output identities.
- `suite.py oracle --package ./internal/testrunner --run '^TestSubmodule$/parser.numericSeparators'`:
  **80 pass, one upstream skip, 50 baseline products**. All 50 products are
  byte-identical to the prior restored native smoke.
- Both initial and repeated runs captured **21/21 completed invocations**,
  **248 diagnostics**, **245 output files**, and **186 shared result blobs**.
  Result manifest SHA-256:
  `06d8dd9fb936e31525f3b7becf2f51cf2695504fbc2ad0bc314b4d11ced29c00`.
- The input manifest remains unchanged:
  `9b868a18399e02d28c887a1a99ae6be7e33d2b40498d0408b05a2714176903f8`.

Ignored artifacts: `artifacts/typescript7/7.0.2-result-capture-smoke/` and
`7.0.2-result-capture-repeat/`. Their native checkout remains clean.

These results establish faithful native capture, not TSZ parity. The records
contain native byte offsets and all-phase diagnostics, which differ from CLI
selection. Candidate comparison, baseline rendering, auxiliary compilation,
type/symbol displays and other native test drivers remain unfinished.
