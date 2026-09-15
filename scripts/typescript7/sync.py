#!/usr/bin/env python3
"""Synchronize the full locked upstream setup and report its exact inventory delta."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import suite


def read_inventory(directory: Path) -> tuple[dict, dict[str, dict]]:
    if (directory / "inventory").is_dir():
        directory /= "inventory"
    summary = json.loads((directory / "inventory-summary.json").read_text())
    if summary.get("schema") != 1:
        raise ValueError("unsupported inventory schema")
    records = {}
    digest = hashlib.sha256()
    categories: Counter = Counter()
    previous = None
    for index, shard in enumerate(sorted(directory.glob("inventory-*.jsonl"))):
        if shard.name != f"inventory-{index:04}.jsonl":
            raise ValueError("inventory shards are missing or misnumbered")
        data = shard.read_bytes()
        digest.update(data)
        for line in data.splitlines():
            record = json.loads(line)
            path = record["path"]
            if previous is not None and path <= previous:
                raise ValueError("inventory paths must be unique and sorted")
            if record["category"] != suite.classify(path):
                raise ValueError(f"inventory category disagrees with path: {path}")
            if record["mode"] not in ("100644", "100755", "120000"):
                raise ValueError(f"unsupported inventory file mode: {path}")
            oid = record["blob"]
            if len(oid) != 40 or any(character not in "0123456789abcdef" for character in oid):
                raise ValueError(f"invalid Git blob identity: {path}")
            records[path] = record
            categories[record["category"]] += 1
            previous = path
    if (not records or len(records) != summary["files"]
            or digest.hexdigest() != summary["inventory_sha256"]
            or dict(categories) != summary["categories"]):
        raise ValueError("inventory content, count, category totals, or hash is inconsistent")
    return summary, records


def changes(previous: dict[str, dict], current: dict[str, dict]):
    for path in sorted(previous.keys() | current.keys()):
        before, after = previous.get(path), current.get(path)
        if before == after:
            continue
        yield {
            "path": path,
            "change": "added" if before is None else "removed" if after is None else "modified",
            "category": (after or before)["category"],
            "before": before,
            "after": after,
        }


def refresh(checkout: Path, source: Path | None, corpus_source: Path | None) -> None:
    """Move only clean managed checkouts to the agreed release commits."""
    pin = suite.lock()
    if not (checkout / ".git").exists():
        suite.setup(checkout, source, corpus_source)
        return
    corpus = checkout / pin["corpus"]["path"]
    if not (corpus / ".git").exists():
        # A partial materialization may be resumed, but never migrate an
        # unrelated checkout with unknown nested inputs.
        suite.setup(checkout, source, corpus_source)
        return
    targets = [(checkout, pin), (corpus, pin["corpus"])]
    old = []
    for repository, target in targets:
        identity = {"commit": suite.git(repository, "rev-parse", "HEAD"),
                    "tree": suite.git(repository, "rev-parse", "HEAD^{tree}")}
        suite.verify_tree(repository, identity)
        old.append(identity)
    # Validate/fetch every object before changing either working tree.
    for repository, target in targets:
        available = subprocess.run(
            ["git", "-C", str(repository), "cat-file", "-e", target["commit"]],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
        if not available:
            suite.git(repository, "fetch", "--depth=1", target["repository"], target["commit"])
        if suite.git(repository, "rev-parse", target["commit"] + "^{tree}") != target["tree"]:
            raise ValueError("release commit and tree pins disagree")
    nested = suite.git(checkout, "ls-tree", pin["commit"], "--", pin["corpus"]["path"])
    if nested.split("\t", 1)[0] != "160000 commit " + pin["corpus"]["commit"]:
        raise ValueError("release corpus pin disagrees with the native Git submodule")
    # No reset/clean/stash: a failed checkout preserves local state for review.
    # Current-release sync is a read-only verification, including branch identity.
    for (repository, target), previous in reversed(list(zip(targets, old))):
        if previous["commit"] != target["commit"]:
            suite.git(repository, "checkout", "--quiet", "--no-overwrite-ignore", "--detach", target["commit"])
    suite.verify(checkout)


def sync(checkout: Path, output: Path, previous: Path | None = None,
         source: Path | None = None, corpus_source: Path | None = None) -> dict:
    pin = suite.lock()
    if output.exists():
        raise ValueError("sync requires a fresh output directory")
    before_summary, before = read_inventory(previous) if previous else (None, {})
    if before_summary:
        for key in (None, "corpus"):
            old = before_summary["oracle"] if key is None else before_summary["oracle"][key]
            new = pin if key is None else pin[key]
            if old["repository"] != new["repository"]:
                raise ValueError("previous inventory belongs to a different upstream repository")
    refresh(checkout, source, corpus_source)
    output.mkdir(parents=True)
    suite.inventory(checkout, output / "inventory")
    current_summary, current = read_inventory(output / "inventory")
    overlay_directory = output / "adapter-check"
    overlay_directory.mkdir()
    suite.make_overlay(checkout, overlay_directory)
    counts: Counter = Counter()
    categories: dict[str, Counter] = {}
    digest = hashlib.sha256()
    batch = []
    shard = 0

    def write_batch():
        nonlocal shard
        data = "".join(json.dumps(row, sort_keys=True) + "\n" for row in batch).encode()
        (output / f"changes-{shard:04}.jsonl").write_bytes(data)
        digest.update(data)
        shard += 1
        batch.clear()

    for row in changes(before, current):
        counts[row["change"]] += 1
        categories.setdefault(row["category"], Counter())[row["change"]] += 1
        batch.append(row)
        if len(batch) == 1000:
            write_batch()
    if batch:
        write_batch()
    # Recheck both checkouts after inventory/overlay generation; never rewrite upstream files.
    suite.verify(checkout)
    summary = {
        "schema": 1, "oracle": pin,
        "previous_oracle": before_summary["oracle"] if before_summary else None,
        "previous_inventory_sha256": before_summary["inventory_sha256"] if before_summary else None,
        "inventory_sha256": current_summary["inventory_sha256"],
        "files": len(current), "changes": dict(sorted(counts.items())),
        "unchanged": len(before.keys() & current.keys()) - counts["modified"],
        "categories": {category: dict(sorted(counts.items())) for category, counts in sorted(categories.items())},
        "changes_sha256": digest.hexdigest(),
        "adapter_check": "capture overlay anchors verified; compilation and test execution not run",
        "tsz_parity": "unmeasured",
    }
    (output / "sync-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, default=suite.ROOT / "TypeScript7")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous", type=Path, help="previous sync or inventory directory")
    parser.add_argument("--source", type=Path, help="reuse native Git objects when materializing")
    parser.add_argument("--corpus-source", type=Path, help="reuse corpus Git objects when materializing")
    args = parser.parse_args()
    print(json.dumps(sync(args.checkout.resolve(), args.output.resolve(), args.previous,
                          args.source, args.corpus_source), indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyError, ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"TypeScript suite sync: {error}", file=sys.stderr)
        sys.exit(2)
