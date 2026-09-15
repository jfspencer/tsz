#!/usr/bin/env python3
"""Observe TSZ on captured native compiler fixtures, without claiming suite parity."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

from input_manifest import summarize_inputs
from replay_namespace import run_candidate, runtime_files
from replay_options import UnsupportedReplay, command_line
from suite import ROOT, lock, verify


def replay(oracle, binary, output, timeout):
    summary = json.loads((oracle / "summary.json").read_text())
    if summary["oracle"] != lock() or summary["exit_status"] != 0 or summary.get("observation_error"):
        raise ValueError("replay requires a successful pinned production oracle observation")
    verify(ROOT / "TypeScript7")
    inputs = oracle / "inputs"
    if summary.get("input_capture") != summarize_inputs(inputs):
        raise ValueError("native input manifest changed after observation")
    schema = json.loads((inputs / "options.json").read_text())
    records = sorted((inputs / "invocations").glob("*.json"))
    if not records:
        raise ValueError("no captured compiler invocations")
    if output.exists():
        raise ValueError("use a new replay output directory")
    binary = binary.resolve(strict=True)
    binary_hash = hashlib.sha256(binary.read_bytes()).hexdigest()
    runtime = runtime_files(binary)
    output.mkdir(parents=True)
    (output / "blobs").mkdir()
    counts = Counter()
    for source in records:
        record = json.loads(source.read_text())
        destination = output / source.stem
        destination.mkdir()
        try:
            args = command_line(record, schema)
            result = run_candidate(binary, runtime, record, args, inputs / "blobs", destination, timeout)
        except UnsupportedReplay as error:
            result = {"state": "unsupported-adapter", "reason": str(error)}
        except (OSError, UnicodeError) as error:
            result = {"state": "adapter-error", "reason": str(error)}
        result.update({"package": record["package"], "test": record["test"], "sequence": record["sequence"],
                       "input_record_sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
        (destination / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        counts[result["state"]] += 1
    if hashlib.sha256(binary.read_bytes()).hexdigest() != binary_hash:
        raise ValueError("candidate binary changed during observation")
    result = {
        "schema": 1, "oracle": summary["oracle"], "input_capture": summary["input_capture"],
        "candidate_sha256": binary_hash, "counts": dict(counts), "invocations": len(records),
        "scope": "candidate CLI observations of original native fixtures",
        "tsz_parity": "unmeasured",
        "remaining": "native all-phase diagnostics, baseline formatting, auxiliary compilation and other drivers",
    }
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, default=ROOT / ".target/release/tsz")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args()
    try:
        if args.timeout <= 0:
            raise ValueError("timeout must be positive")
        print(json.dumps(replay(args.oracle.resolve(), args.candidate, args.output.resolve(), args.timeout), indent=2))
        # A successful observation is not a passing test suite.
        sys.exit(1)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"TypeScript 7 replay: {error}", file=sys.stderr)
        sys.exit(2)
