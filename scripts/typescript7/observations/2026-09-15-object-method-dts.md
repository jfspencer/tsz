# Inferred object declaration output

Parent compiler: `19b4e95d6d97d90eb4d3bcf55c72780282e752c8`.
Oracle: production TypeScript 7.0.2, native commit
`2bd066d87f5bafd315be9f40889d0a60b9e58e0b`, with `--singleThreaded
--stableTypeOrdering true`.

## Rule and owner

The release's `internal/checker/emitresolver.go` requests
`FlagsMultilineObjectLiterals` for declaration types.
`internal/checker/nodebuilderimpl.go` emits callable method symbols as method
signatures, while function-valued properties retain property syntax.

TSZ's checker-owned declaration summaries now render inferred object literals
with multiline layout, authored property order, and method signatures.
The same renderer handles nested object literals, homogeneous object arrays,
and normalized object-union arrays. Method parameters use checked signature
types and retain authored type annotations with declaration indentation.
Empty objects remain `{}`. Incomplete inference still withholds declaration
products rather than manufacturing types.

The emitter consumes these summaries. Shared type layout and parameter
formatting replace duplicate implementations in the type store and diagnostic
renderer. No semantic force query, recursion identity, cache, or capability
policy was added. The display traversal retains its bounded depth.

## Evidence

- A 17-case fresh-process oracle matrix improved from **1/17 to 9/17 exact
  matches**, comparing exit, stdout, stderr, and declaration bytes.
- Exact cases cover renamed methods, required/optional/rest parameters, nested
  objects, authored property order, homogeneous and union arrays, empty objects,
  and object-typed parameters. Their production oracle bytes are checked in at
  `crates/tsz-core/rewrite-tests/fixtures/inferred_object_declarations.json`.
- Compiler/service tests repeat those cases, reverse roots, and preserve
  explicit incomplete results for unfinished inference.
- Workspace `cargo nextest run --locked --workspace`: **1,446 passing tests**.
- Strict workspace Clippy, seven seed oracle cases, architecture checks,
  60 architecture-guard tests, and the context audit pass.
- Handwritten compiler Rust decreases from **44,929 to 44,928** physical lines.

An upstream emit sample selected 164 JS rows and 19 DTS rows. Before and after
both report 16 exact JS passes and one exact DTS pass, with no recorded row
field changes except elapsed time. Those summaries do not retain complete
product payload hashes, so they do not prove byte identity of every mismatching
product. The diagnostic filter `objectLiteralMethod` selected five cases, all
still unsupported; that run supplies no passing conformance claim.

Ignored local evidence lives in `artifacts/typescript7/object-method-dts/`:
`matrix-before.json`, `matrix-after.json`, `emit-before.json`, `emit-after-final.json`,
`emit-comparison.json`, and the immutable `tsz-before` binary. Matrix artifacts
include compiler hashes and exact observed declaration bytes.

## Remaining work

Eight matrix cases remain incomplete: generic methods, constrained generic
methods, arrow/function-valued properties with inferred returns, defaulted
parameters, the combined quoted/computed-key case, object-valued returns, and
value aliases. The original `declFileEmitDeclarationOnly` case also needs class
instance/constructor checking and dependent call summaries. These changes do
not establish complete declaration conformance or a new full-corpus percentage.
