# Complete TypeScript 7.0.2 oracle

Only the production **7.0.2** release is an oracle. `oracle-lock.json` pins its
native Git commit/tree and the exact TypeScript corpus submodule. The harness
rejects disagreement with the active diagnostic, emit, npm, and corpus pins.
Development checkouts and historical snapshot totals do not establish parity.

## Materialize the full setup

```bash
scripts/safe-run.sh python3 scripts/typescript7/suite.py setup \
  --corpus-source TypeScript
python3 scripts/typescript7/suite.py inventory \
  --output artifacts/typescript7/7.0.2-inventory
```

`TypeScript7/` is an ignored full checkout of the release, including all native
tests, upstream baselines, libraries, fixtures, tools, licenses, and package
lockfiles. Its `_submodules/TypeScript/` contains the full matching corpus.
`--source` optionally reuses a local **typescript-go** clone. Local clones share
immutable Git objects, so retain their source repositories. No checkout of a
mutable sibling is used as a test input.

The legacy `TypeScript/` and existing conformance/emit/fourslash infrastructure
remain available. This complete native suite includes products those adapters
do not yet score: type/symbol displays, source-map records, resolution traces,
native services, project/build/watch tests, and native unit tests.

## Observe the release with its own harness

```bash
# Small smoke before a full run.
scripts/safe-run.sh python3 scripts/typescript7/suite.py oracle \
  --package ./internal/testrunner --run '^TestSubmodule$/parser.numericSeparators' \
  --output artifacts/typescript7/7.0.2-smoke

# Every native Go package, including its corpus-driven subtests.
scripts/safe-run.sh python3 scripts/typescript7/suite.py oracle \
  --output artifacts/typescript7/7.0.2-native
```

Use a fresh output directory for each observation. Go 1.26 is required by the
release. Some upstream packages also need the upstream Node build/setup; a
missing prerequisite remains a failure/skip in the report.

The reporting-only Go overlay adds capture calls at the upstream baseline sink.
It preserves the original comparison and exact product bytes, including CRLF,
empty-product assertions, and explicit absent baselines. It never accepts or
updates reference baselines. The checked-out source stays unchanged. The full
Git inventory includes all fixtures even when upstream itself skips a test.

Artifacts contain raw Go JSON events, stderr, per-product content/hashes,
sharded test identities, native failure/skip/uncompleted counts, source identity,
and the invocation. Parent tests are not counted twice. **Native oracle passes
are not TSZ passes**: `tsz_parity` stays `unmeasured` until a candidate adapter
has compared the corresponding TSZ products. Porting the remaining adapters
and compiler behavior is required before claiming full-suite parity.

## Exact product comparison

`compare.py --oracle <observation> --candidate <products-dir> --output <new-dir>`
compares every `(test, path)` identity, exact content, and explicit absence.
Candidate records use the captured JSON shape plus `completion`: `complete`,
`deferred`, `cycle`, `limit`, `unsupported`, `crash`, or `timeout`. Only complete,
byte-identical products pass. Missing/extra products, duplicate keys, corrupted
hashes, empty oracle selections, and unsuccessful oracle observations fail the
gate. The report is explicitly scoped to baseline products; native internal
assertions require separate ports. Candidate adapters must produce TSZ output;
copying expected records is not a candidate implementation.

## Native compiler input capture

Oracle observations also capture the inputs to `harnessutil.CompileFilesEx`
after upstream option parsing, root selection, path resolution, test-library
insertion, and symlink construction. The Go overlay records these inputs
without altering the native compilation or baseline comparison:

- `inputs/invocations/*.json`: native package/test identity, invocation sequence,
  ordered roots, working directory, compiler and harness options, virtual
  filesystem entries, and the config source when present.
- `inputs/blobs/<sha256>`: exact source bytes or symlink targets. Shared inputs
  are stored once. No UTF-8 decoding changes binary fixtures or line endings.
- `summary.json.input_capture`: validated invocation/blob counts and a manifest
  hash covering every captured record and blob.

Options use the pinned Go compiler's native JSON representation, including its
numeric enums and distinct unset/false values. They are not a ready-to-use
`tsconfig.json`. The default library path is recorded separately; bundled
libraries remain in the pinned source inventory. Case sensitivity and symlink
modes belong to the virtual filesystem and must survive a candidate adapter.

Repeated calls are retained, including native consistency checks and compilation
of generated declaration files. **A candidate must produce its own intermediate
outputs** when replaying such checks; it must not compile captured oracle emit
as a substitute for its own emit. This is an input ledger, not a completed
replay engine. Other native drivers, such as build/watch and language-service
tests, still need their own adapters.

## Release-native limitations observed locally

The first complete 7.0.2 native run captured 66,885 products and reported
131,336 passing leaves, two failures, 2,626 skips, and six unfinished leaves.
It is an observation, not a green baseline:

- `astnav/TestFindPrecedingToken` tries to load the legacy JavaScript
  `typescript.js` API through an upstream `typescript: ^6.0.3` development
  dependency. Production 7.0.2 does not ship that API. Do not install an older
  compiler as a validation oracle; this adapter still needs a native port.
- The release's command-line help baseline differs in banner padding from its
  own compiler output. Keep the original reference and observed bytes.

The production compiler smoke (`parser.numericSeparators`) independently passes
80 leaves, has one upstream skip, and captures 50 exact products. Native checks
do not establish TSZ coverage. Run artifacts live under ignored `artifacts/`;
rerun on the current machine before making new exact-head claims.

Harness checks:

```bash
scripts/safe-run.sh python3 -m unittest discover -s scripts/typescript7 -p 'test_*.py'
```

These checks include native Go capture contracts and require the pinned checkout
from `setup`. The contract tests are injected only into their separate test run;
they do not add passing leaves to an oracle observation.
