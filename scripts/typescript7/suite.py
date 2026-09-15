#!/usr/bin/env python3
"""Materialize and observe the complete pinned native TypeScript test setup.

Native oracle success is never reported as TSZ success. No cases are selected
by the old diagnostic cache, old skip lists, or TSZ's current capabilities.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from input_manifest import summarize_inputs
from result_manifest import summarize_results

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def git(root: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    return subprocess.check_output(
        ["git", "-C", str(root), *args], env=env, text=True
    ).strip()


def lock() -> dict:
    pin = json.loads((HERE / "oracle-lock.json").read_text())
    versions = json.loads((ROOT / "scripts/conformance/typescript-versions.json").read_text())
    current = versions["mappings"][versions["current"]]
    emit = json.loads((ROOT / "scripts/emit/oracle-manifest.json").read_text())
    npm = json.loads((ROOT / "scripts/package.json").read_text())["devDependencies"]["typescript"]
    seed = json.loads((ROOT / "tests/rewrite-seed/matrix.json").read_text())["pinned_typescript"]
    vendor = json.loads((ROOT / "vendor/typescript-go/artifacts.json").read_text())
    corpus = (ROOT / "scripts/ci/typescript-submodule-ref").read_text().strip()
    if not (
        pin["version"] == current["npm"] == versions["default"]["npm"] == emit["version"] == npm == seed == vendor["typescriptVersion"] == "7.0.2"
        and pin["commit"] == current["native_sha"] == emit["gitHead"] == vendor["commit"]
        and pin["tag"] == current["native_tag"]
        and pin["corpus"]["commit"] == versions["current"] == corpus
    ):
        raise ValueError("all active TypeScript oracle pins must agree on production 7.0.2")
    return pin


def verify_tree(checkout: Path, pin: dict) -> None:
    if Path(git(checkout, "rev-parse", "--show-toplevel")).resolve() != checkout.resolve():
        raise ValueError(f"missing independent oracle checkout: {checkout}")
    for expression, field in (("HEAD", "commit"), ("HEAD^{tree}", "tree")):
        actual = git(checkout, "rev-parse", expression)
        if actual != pin[field]:
            raise ValueError(f"oracle {field}: expected {pin[field]}, got {actual}")
    dirty = git(checkout, "status", "--porcelain", "--untracked-files=all")
    if dirty:
        raise ValueError(f"oracle checkout has modified/untracked inputs:\n{dirty}")
    # A sparse checkout or deleted file must not silently reduce the domain.
    flags = git(checkout, "ls-files", "-v").splitlines()
    if any(line.startswith("S ") for line in flags):
        raise ValueError("oracle must contain the full checkout, not sparse paths")
    if any(line and line[0].islower() for line in flags):
        raise ValueError("oracle files may not be marked assume-unchanged")
    ignored = git(checkout, "status", "--porcelain", "--untracked-files=all", "--ignored=matching", "--",
                  "tests/cases", "tests/lib", "testdata/tests", "testdata/fixtures", "internal/bundled/libs")
    if ignored:
        raise ValueError(f"oracle semantic inputs contain untracked/ignored files:\n{ignored}")


def verify(checkout: Path) -> dict:
    pin = lock()
    verify_tree(checkout, pin)
    verify_tree(checkout / pin["corpus"]["path"], pin["corpus"])
    installed = checkout / "node_modules/typescript/package.json"
    if installed.exists() and json.loads(installed.read_text()).get("version") != pin["version"]:
        raise ValueError("native tests may only load production typescript@7.0.2; the upstream legacy JS-API adapter needs porting")
    return pin


def clone_pin(checkout: Path, pin: dict, source: Path | None) -> None:
    if checkout.exists() and (checkout / ".git").exists():
        verify_tree(checkout, pin)
        return
    checkout.parent.mkdir(parents=True, exist_ok=True)
    checkout.mkdir(exist_ok=True)
    git(checkout, "init", "-q")
    git(checkout, "remote", "add", "origin", pin["repository"])
    if source:
        # Local clone's upload-pack cannot serve absent promisor blobs, and
        # --shared falls back to that path for shallow repos. Bind immutable
        # objects directly; lazy-fetch missing blobs from the real upstream.
        objects = git(source.resolve(), "rev-parse", "--path-format=absolute", "--git-path", "objects")
        (checkout / ".git/objects/info/alternates").write_text(objects + "\n")
        shallow = Path(git(source.resolve(), "rev-parse", "--path-format=absolute", "--git-path", "shallow"))
        if shallow.exists():
            (checkout / ".git/shallow").write_bytes(shallow.read_bytes())
        git(checkout, "config", "remote.origin.promisor", "true")
        git(checkout, "config", "remote.origin.partialclonefilter", "blob:none")
        present = subprocess.run(
            ["git", "-C", str(source.resolve()), "cat-file", "-e", pin["commit"]],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
        if not present:
            git(checkout, "fetch", "--depth=1", "origin", pin["commit"])
    else:
        git(checkout, "fetch", "--depth=1", "origin", pin["commit"])
    git(checkout, "checkout", "--detach", pin["commit"])
    verify_tree(checkout, pin)


def setup(checkout: Path, source: Path | None, corpus_source: Path | None) -> None:
    pin = lock()
    # A full checkout retains all source, fixtures, baselines, tools, licenses
    # and package lockfiles. Only immutable Git objects may be shared.
    clone_pin(checkout, pin, source)
    clone_pin(checkout / pin["corpus"]["path"], pin["corpus"], corpus_source)
    verify(checkout)
    print(f"Materialized complete oracle at {pin['commit']}: {checkout}")


def classify(path: str) -> str:
    if path.startswith("_submodules/TypeScript/"):
        return "release-corpus/" + path.removeprefix("_submodules/TypeScript/").split("/", 1)[0]
    if path.startswith("testdata/"):
        return "native/" + path.removeprefix("testdata/").split("/", 1)[0]
    if path.endswith("_test.go"):
        return "go-tests"
    if path.startswith("internal/bundled/"):
        return "bundled-libraries"
    return "source-and-setup"


def inventory(checkout: Path, output: Path) -> dict:
    pin = verify(checkout)
    output.mkdir(parents=True, exist_ok=False)
    counts: Counter = Counter()
    groups: Counter = Counter()
    records = []
    # Git blob identities bind bytes and paths, including non-TS fixture files.
    entries = git(checkout, "ls-tree", "-rz", "HEAD").rstrip("\0").split("\0")
    for entry in entries:
        metadata, path = entry.split("\t", 1)
        mode, kind, oid = metadata.split()
        if kind == "commit" and path == pin["corpus"]["path"] and oid == pin["corpus"]["commit"]:
            entries.extend(
                metadata + "\t" + path + "/" + child
                for metadata, child in (
                    row.split("\t", 1) for row in git(checkout / path, "ls-tree", "-rz", "HEAD").rstrip("\0").split("\0")
                )
            )
            continue
        if kind != "blob":
            raise ValueError(f"unmaterialized nested object: {kind} {path}")
        category = classify(path)
        counts[category] += 1
        if path.startswith("testdata/baselines/reference/"):
            groups[path.split("/")[3]] += 1
        records.append({"path": path, "mode": mode, "blob": oid, "category": category})
    # Shard generated inventories to preserve the repository's size contract.
    digest = hashlib.sha256()
    records.sort(key=lambda record: record["path"])
    for start in range(0, len(records), 1000):
        data = "".join(json.dumps(r, sort_keys=True) + "\n" for r in records[start:start + 1000])
        digest.update(data.encode())
        (output / f"inventory-{start // 1000:04}.jsonl").write_text(data)
    summary = {
        "schema": 1, "oracle": pin, "files": len(records),
        "categories": dict(sorted(counts.items())),
        "reference_groups": dict(sorted(groups.items())),
        "inventory_sha256": digest.hexdigest(),
        "tsz_parity": "unmeasured",
    }
    (output / "inventory-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def summarize_events(events: list[dict]) -> dict:
    """Count leaf tests, retain skipped/uncompleted rows and package failures."""
    rows = {}
    packages = {}
    parents = set()
    for event in events:
        package, name, action = event.get("Package"), event.get("Test"), event.get("Action")
        if not package:
            continue
        if name:
            key = (package, name)
            if action == "run":
                rows[key] = "uncompleted"
            elif action in ("pass", "fail", "skip"):
                rows[key] = action
            parts = name.split("/")
            parents.update((package, "/".join(parts[:i])) for i in range(1, len(parts)))
        elif action in ("pass", "fail", "skip"):
            packages[package] = action
    leaves = [
        {"package": p, "test": n, "status": s}
        for (p, n), s in sorted(rows.items()) if (p, n) not in parents
    ]
    return {
        "leaf_counts": dict(sorted(Counter(r["status"] for r in leaves).items())),
        "leaves": leaves,
        "packages": dict(sorted(packages.items())),
        "failed_parents": [
            {"package": p, "test": n} for (p, n), s in sorted(rows.items())
            if (p, n) in parents and s == "fail"
        ],
    }


def make_overlay(checkout: Path, output: Path) -> Path:
    baseline = checkout / "internal/testutil/baseline/baseline.go"
    original = baseline.read_text()
    marker = "\t\trecordBaseline(t, filepath.Join(subfolder, fileName))\n"
    if original.count(marker) != 1:
        raise ValueError("pinned baseline capture anchor changed")
    patched = output / "baseline.go"
    modified = original.replace(
        marker, marker + "\t\ttszCaptureBaseline(t, filepath.Join(subfolder, fileName), actual)\n"
    )
    direct = "\trecordBaseline(t, filepath.Join(opts.Subfolder, fileName))\n"
    if original.count(direct) != 1:
        raise ValueError("pinned direct baseline capture anchor changed")
    modified = modified.replace(direct, direct +
        '\ttszCaptureBaseline(t, filepath.Join("direct", opts.Subfolder, fileName), actual)\n')
    patched.write_text(modified)
    harness = checkout / "internal/testutil/harnessutil/harnessutil.go"
    source = harness.read_text()
    boundary = "\tfs := vfstest.FromMap(testfs, harnessOptions.UseCaseSensitiveFileNames)\n"
    if source.count(boundary) != 1:
        raise ValueError("pinned compiler input capture anchor changed")
    patched_harness = output / "harnessutil.go"
    modified_harness = source.replace(boundary,
        "\ttszInvocation := tszCaptureCompilation(t, testfs, programFileNames, compilerOptions, harnessOptions, currentDirectory, tsconfig)\n"
        + boundary)
    result_boundary = "\tresult.Trace = host.tracer.String()\n"
    if source.count(result_boundary) != 1:
        raise ValueError("pinned compiler result capture anchor changed")
    patched_harness.write_text(modified_harness.replace(result_boundary,
        result_boundary + "\ttszCaptureCompilationResult(t, tszInvocation, result)\n"))
    overlay = output / "overlay.json"
    overlay.write_text(json.dumps({"Replace": {
        str(baseline): str(patched),
        str(baseline.with_name("tsz_capture.go")): str(HERE / "capture.go"),
        str(harness): str(patched_harness),
        str(harness.with_name("tsz_capture_inputs.go")): str(HERE / "capture_inputs.go"),
        str(harness.with_name("tsz_capture_options.go")): str(HERE / "capture_options.go"),
        str(harness.with_name("tsz_capture_results.go")): str(HERE / "capture_results.go"),
    }}, indent=2) + "\n")
    return overlay


def oracle(checkout: Path, output: Path, packages: list[str], pattern: str, workers: int) -> int:
    if output.exists():
        raise ValueError(f"use a new output directory to preserve observations: {output}")
    pin = verify(checkout)
    output.mkdir(parents=True)
    inventory(checkout, output / "inventory")
    products = output / "products"
    products.mkdir()
    overlay = make_overlay(checkout, output)
    command = [
        "go", "test", f"-overlay={overlay}", "-json", "-count=1",
        "-p=2", f"-parallel={workers}", "-timeout=45m",
    ]
    if pattern:
        command += ["-run", pattern]
    command += packages or ["./..."]
    inputs = output / "inputs"
    env = dict(os.environ, TSZ_ORACLE_CAPTURE_DIR=str(products), TSZ_ORACLE_INPUT_DIR=str(inputs),
               CGO_ENABLED="0", TS_TEST_PROGRAM_SINGLE_THREADED="true",
               TSZ_ORACLE_RESULT_DIR=str(output / "compilations"))
    with (output / "events.jsonl").open("w") as stdout, (output / "stderr.txt").open("w") as stderr:
        result = subprocess.run(command, cwd=checkout / pin["module"], env=env, stdout=stdout, stderr=stderr)
    with (output / "events.jsonl").open() as events:
        summary = summarize_events(json.loads(line) for line in events)
    leaves = summary.pop("leaves")
    for start in range(0, len(leaves), 1000):
        (output / f"tests-{start // 1000:04}.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in leaves[start:start + 1000])
        )
    input_capture = summarize_inputs(inputs)
    result_capture = summarize_results(output / "compilations", inputs)
    summary.update({
        "schema": 1, "oracle": pin, "command": command,
        "exit_status": result.returncode, "products": len(list(products.glob("*.json"))),
        "compiler_invocations": input_capture["invocations"], "input_capture": input_capture,
        "result_capture": result_capture,
        "scope": "filtered" if pattern or packages else "all-native-go-tests",
        "tsz_parity": "unmeasured",
        "capture": "reporting-only Go overlay; upstream comparisons unchanged",
    })
    if result_capture["missing_invocations"]:
        summary["observation_error"] = "native compiler invocations are missing completed-result records"
    if not summary["products"]:
        summary["observation_error"] = "no baseline products captured; a passing parent may have matched no cases"
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    verify(checkout)
    return result.returncode or (2 if "observation_error" in summary else 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, default=ROOT / "TypeScript7")
    sub = parser.add_subparsers(dest="command", required=True)
    setup_parser = sub.add_parser("setup")
    setup_parser.add_argument("--source", type=Path, help="reuse the user's local TypeScript Git objects")
    setup_parser.add_argument("--corpus-source", type=Path, help="reuse the pinned legacy corpus Git objects")
    inventory_parser = sub.add_parser("inventory")
    inventory_parser.add_argument("--output", type=Path, required=True)
    oracle_parser = sub.add_parser("oracle")
    oracle_parser.add_argument("--output", type=Path, required=True)
    oracle_parser.add_argument("--package", action="append", default=[])
    oracle_parser.add_argument("--run", default="")
    oracle_parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    checkout = args.checkout.resolve()
    if args.command == "setup":
        setup(checkout, args.source, args.corpus_source)
    elif args.command == "inventory":
        print(json.dumps(inventory(checkout, args.output.resolve()), indent=2))
    else:
        return oracle(checkout, args.output.resolve(), args.package, args.run, args.workers)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"TypeScript 7 harness: {error}", file=sys.stderr)
        sys.exit(2)
