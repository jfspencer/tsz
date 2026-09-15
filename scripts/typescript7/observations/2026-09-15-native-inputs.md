# Native compiler input capture

Oracle: production TypeScript 7.0.2, native commit
`2bd066d87f5bafd315be9f40889d0a60b9e58e0b` and its locked nested corpus.

The reporting overlay now captures the native compiler harness's resolved
virtual filesystem, ordered roots, working directory, compiler/harness options,
config sources, and default library path. Files and symlink targets use raw byte
blobs with SHA-256 identities. A validated manifest records every invocation,
including repeated invocations; package identity prevents collisions between
test packages. Atomic publication prevents cross-process readers from observing
partially written shared blobs.

## Validation

- 25 Python tests pass, including two native Go capture contracts. The native
  contracts check binary bytes and concurrent publication from six processes.
  They run separately from the oracle suite and do not inflate its counts.
- The focused native observation reports **97 passing leaves, three skips, and
  62 products**. Every baseline product matches the earlier native observation
  byte-for-byte. No upstream source files or reference baselines were changed.
- It captures **27 compiler invocations and 130 deduplicated input blobs**.
  These include two invocations with symlinks, three with config sources, and
  both case-sensitive and case-insensitive filesystem settings.
- The input manifest and all blob hashes validate. The numeric-separator
  subset also independently retained its earlier 80 passes, one skip, and 50
  products.

Commands:

```sh
scripts/safe-run.sh python3 -m unittest discover -s scripts/typescript7 -p 'test_*.py'
scripts/safe-run.sh python3 scripts/typescript7/suite.py oracle \
  --package ./internal/testrunner \
  --run '^TestSubmodule$/(parser.numericSeparators|sourceMapWithNonCaseSensitiveFileNames|moduleResolutionWithSymlinks_referenceTypes|pathsValidation1[.]ts)' \
  --output artifacts/typescript7/7.0.2-input-capture-final
```

## Remaining adapter work

This is a capture boundary, not TSZ replay or a conformance gain. The adapter
still needs to interpret the pinned option representation, reproduce the
virtual filesystem and upstream baseline formats, and obtain every result from
TSZ. Native checks that compile generated declaration files must use TSZ's own
intermediate output. Build/watch, service, and internal assertion drivers need
separate ports. The full objective remains unfulfilled.
