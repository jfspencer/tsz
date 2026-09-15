#!/usr/bin/env python3
"""Compare candidate baseline products byte-for-byte with a release observation.

This gate covers baseline products, not upstream internal unit-test assertions.
Candidate adapters must emit their own content and an explicit completion state.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

from suite import lock


def read_products(directory: Path, candidate: bool = False) -> dict:
    if not directory.is_dir():
        raise ValueError(f"product directory is missing: {directory}")
    result = {}
    for path in sorted(directory.glob("*.json")):
        record = json.loads(path.read_text())
        key = (record["test"], record["path"])
        if not all(isinstance(part, str) and part for part in key):
            raise ValueError(f"invalid product identity: {path}")
        if key in result:
            raise ValueError(f"duplicate product identity: {key}")
        content = record["content"]
        if not isinstance(content, str) or type(record["absent"]) is not bool:
            raise ValueError(f"invalid product payload: {path}")
        if record["absent"] != (content == "<no content>"):
            raise ValueError(f"invalid absence assertion: {path}")
        if record["sha256"] != hashlib.sha256(content.encode()).hexdigest():
            raise ValueError(f"product content/hash mismatch: {path}")
        if candidate and record.get("completion") not in ("complete", "deferred", "cycle", "limit", "unsupported", "crash", "timeout"):
            raise ValueError(f"candidate completion state is missing/invalid: {path}")
        result[key] = record
    return result


def compare(expected: dict, actual: dict) -> list[dict]:
    if not expected:
        raise ValueError("an empty oracle product set cannot establish parity")
    rows = []
    for key in sorted(expected.keys() | actual.keys()):
        oracle, candidate = expected.get(key), actual.get(key)
        if oracle is None:
            status = "extra"
        elif candidate is None:
            status = "missing"
        elif candidate["completion"] != "complete":
            status = candidate["completion"]
        elif (oracle["absent"], oracle["content"]) != (candidate["absent"], candidate["content"]):
            status = "mismatch"
        else:
            status = "pass"
        rows.append({"test": key[0], "path": key[1], "status": status})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("use a new comparison output directory")
    summary = json.loads((args.oracle / "summary.json").read_text())
    if summary["oracle"] != lock():
        raise ValueError("oracle observation does not use the pinned production release")
    if summary["exit_status"] != 0 or summary.get("observation_error"):
        raise ValueError("native oracle validation failed or did not capture products")
    expected = read_products(args.oracle / "products")
    if len(expected) != summary["products"]:
        raise ValueError("oracle product inventory changed after observation")
    actual = read_products(args.candidate, candidate=True)
    rows = compare(expected, actual)
    counts = dict(sorted(Counter(row["status"] for row in rows).items()))
    result = {
        "schema": 1, "oracle": lock(), "scope": "baseline-products",
        "oracle_scope": summary["scope"], "counts": counts,
        "expected": len(expected), "actual": len(actual),
        "exact": counts.get("pass", 0) == len(rows),
        "native_internal_assertions": "not-covered-by-product-comparison",
    }
    args.output.mkdir(parents=True)
    for start in range(0, len(rows), 1000):
        (args.output / f"products-{start // 1000:04}.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows[start:start + 1000])
        )
    (args.output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["exact"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"TypeScript 7 comparison: {error}", file=sys.stderr)
        sys.exit(2)
