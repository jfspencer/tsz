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

## Synchronize upstream tests

```bash
# First sync: all files are recorded as additions.
scripts/safe-run.sh python3 scripts/typescript7/sync.py \
  --corpus-source TypeScript --output artifacts/typescript7/sync-first

# Subsequent sync: compare with a prior sync or inventory directory.
scripts/safe-run.sh python3 scripts/typescript7/sync.py \
  --previous artifacts/typescript7/sync-first \
  --output artifacts/typescript7/sync-next
```

The sync unit is the **entire native repository plus its nested TypeScript
corpus**, including tests, references, binary fixtures, symlinks, executable
modes, libraries, tools, and setup files. There is no hand-maintained case list
to update. Existing clean managed checkouts move to the exact locked commits;
local dirty files, sparse inputs, inconsistent nested commits, and inconsistent
active oracle pins stop the sync before it can claim success. Repeating a sync
at the same release leaves checkout identities unchanged.

Each fresh output directory contains:

- `inventory/`: the complete sharded Git blob/path/mode inventory.
- `changes-*.jsonl`: every added, removed, or modified file, with both identities.
  Line-ending-only and executable-mode-only changes remain visible.
- `sync-summary.json`: release identities, inventory/delta hashes, category
  counts, and unchanged-file count.
- `adapter-check/`: generated capture overlays proving that the expected
  upstream hooks still exist. This checks anchors; run the native smoke below
  to verify compilation and capture execution.

`--previous` verifies the inventory hash, file count, ordering, duplicate paths,
and categories before calculating changes. A missing or corrupted shard cannot
produce a clean report. Sync never edits upstream reference baselines and never
reports native or TSZ test passes.

The selected release remains **7.0.2**. Sync does not select `latest`, advance a
branch tip, or accept development versions. Moving to another production release
requires an explicit, reviewed update of the active pins and their consistency
checks; run this same sync workflow afterward, review its delta, then run the
native smoke and candidate comparisons. Capture hooks that changed upstream
must be ported before the sync check succeeds.

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
- `inputs/options.json`: option kinds and enum values exported from the pinned
  native declarations. Its bytes are included in the input manifest.

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

## Native completed-result capture

Each captured `CompileFilesEx` invocation also has a matching record under
`compilations/invocations/`. The reporting overlay reads the completed native
result before returning it to the original tests; it does not query the compiler
again or change an assertion. Records retain:

- The input invocation identity, ordered native diagnostics, recursive message
  chains and related information, categories, flags, and exact diagnostic source
  bytes. Spans are explicitly **native byte offsets**, not UTF-16 positions.
- Every file in the native output recorder, including JS, declarations, maps,
  JSON, and build information. Paths and raw bytes are preserved; file records
  are sorted by path, and shared bytes live in `compilations/blobs/`.
- The native emit-skipped state, emit diagnostics, reported output paths, and
  resolution trace. A missing emit result remains distinct from an empty result.

`summary.json.result_capture` verifies blob hashes, references, invocation
identities, and ordered payloads. Missing result records are reported by input
identity and prevent an observation from succeeding. The manifest covers all
records and blobs; corruption cannot silently become an empty output set.

This is the native API result, not the CLI's diagnostic selection or exit code.
It provides a direct comparison boundary for candidate replay. Native baseline
formatting, type/symbol displays, auxiliary checks, and other test drivers still
need their own candidate adapters; captured oracle results are never candidate
outputs.

## Candidate replay

```bash
scripts/safe-run.sh python3 scripts/typescript7/replay.py \
  --oracle artifacts/typescript7/7.0.2-replay-inputs \
  --candidate .target/release/tsz \
  --output artifacts/typescript7/7.0.2-tsz-replay
```

Use a fresh oracle capture containing option metadata and native caller chains.
The initial Linux adapter uses `bubblewrap` to retain absolute virtual paths,
symlinks, root order, and original source bytes. The candidate and its runtime
libraries are mounted read-only; `/proc` belongs to an isolated process namespace.
It translates values through the captured native option declarations and never
drops an unknown option to get the candidate to compile.

Every captured invocation receives a result. Primary compiler fixtures run
through TSZ's CLI; auxiliary calls that could consume oracle-generated output
remain explicitly unsupported. Case-insensitive filesystems, parsed-config
provenance, suggestion queries, and other native drivers still require adapters.
The Linux process runtime also requires `/proc`; fixtures overlapping that mount
are unsupported. Symlinked working directories are currently unsupported.

Results retain process exit status, original stdout/stderr bytes, structured
TSZ JSON when produced, new/changed files, and removed input paths. Timeouts
terminate the process group and retain the observed partial products. A binary
hash identifies the candidate, and the input manifest is checked before replay.
`summary.json.candidate_capture` hashes every result and shared blob, verifies
sidecar bytes, and requires exactly one candidate record for every native input.

This command deliberately exits 1 and reports `tsz_parity: unmeasured`: candidate
execution is now available, but native baseline formatting and assertion replay
are unfinished. In particular, native compiler tests collect diagnostic phases
that the CLI may suppress; CLI observations cannot substitute for those native
API products. A zero candidate exit is not a passing native test.

## Compare captured observations

```bash
python3 scripts/typescript7/replay_diff.py \
  --oracle artifacts/typescript7/7.0.2-replay-inputs \
  --candidate artifacts/typescript7/7.0.2-tsz-replay \
  --output artifacts/typescript7/7.0.2-replay-diff
```

The oracle observation must contain completed native results, and the replay
must contain its candidate manifest. Older replay directories must be rerun.
Both input identities and all three manifests are verified before comparison;
missing/extra invocations, duplicate output paths, changed records, corrupt
blobs, and altered sidecars are errors. Fresh output directories retain every
invocation in hashed JSONL shards, including unsupported and unavailable rows.

Two explicit projections are compared:

- Ordered diagnostic headers: path, position, length, code, category and text.
  Native byte spans are converted to UTF-16 using their captured source bytes.
  Messages, order and duplicate diagnostics are unchanged. Missing candidate
  diagnostics are unavailable, never an implicit empty list. Chains, related
  information, diagnostic flags and native phase selection remain outside this
  projection.
- Filesystem changes: exact bytes, paths and modes of new/changed files, plus
  candidate input removals. The equivalent delta is derived from native output
  records and original input files. Same-byte writes are not visible as write
  events in this projection. Native output through a symlink remains explicitly
  unavailable until write-event capture is implemented.

Candidate completion is recorded separately. A matching projection can coexist
with incomplete compiler work and **never counts as a passing native test**.
The command exits 1 with `tsz_parity: unmeasured`, even when both projections
match; malformed or inconsistent evidence exits 2. Full result APIs, emit
events, traces, baseline rendering and other native test drivers still need
ports. The comparison works with either compiler foundation and does not read
compiler internals or feed expected outputs into the candidate.

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
