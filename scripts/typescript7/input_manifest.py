"""Validate captured native compiler inputs without interpreting their semantics."""

import hashlib
import json
from pathlib import Path
import re


def summarize_inputs(directory: Path) -> dict:
    blobs = {}
    manifest = []
    for path in sorted((directory / "blobs").glob("*")):
        if not re.fullmatch(r"[0-9a-f]{64}", path.name) or not path.is_file():
            raise ValueError(f"invalid compiler input blob: {path}")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != path.name:
            raise ValueError(f"compiler input blob/hash mismatch: {path}")
        blobs[path.name] = len(content)
        manifest.append([f"blobs/{path.name}", path.name, len(content)])

    def check_file(record):
        if not isinstance(record, dict) or set(record) != {"path", "mode", "byte_length", "sha256"}:
            raise ValueError("invalid compiler input file record")
        if not isinstance(record["path"], str) or not record["path"]:
            raise ValueError("invalid compiler input file path")
        if type(record["mode"]) is not int or not 0 <= record["mode"] <= 0xFFFFFFFF:
            raise ValueError("invalid native filesystem mode")
        size = record["byte_length"]
        digest = record["sha256"]
        if (type(size) is not int or not isinstance(digest, str)
                or digest not in blobs or blobs[digest] != size):
            raise ValueError("missing or invalid compiler input blob reference")

    invocations = 0
    identities = set()
    for path in sorted((directory / "invocations").glob("*.json")):
        content = path.read_bytes()
        record = json.loads(content)
        if not isinstance(record, dict) or type(record.get("schema")) is not int or record["schema"] != 1:
            raise ValueError("unsupported compiler input schema")
        package, test, sequence = record.get("package"), record.get("test"), record.get("sequence")
        if (not isinstance(package, str) or not package or not isinstance(test, str) or not test
                or type(sequence) is not int or sequence < 0):
            raise ValueError("invalid compiler invocation identity")
        identity = (package, test, sequence)
        if identity in identities:
            raise ValueError(f"duplicate compiler invocation: {identity}")
        identities.add(identity)
        key = hashlib.sha256(f"{package}\0{test}\0{sequence}".encode()).hexdigest()
        if path.name != key + ".json":
            raise ValueError("compiler invocation filename/identity mismatch")
        roots = record.get("roots")
        if roots is not None and (not isinstance(roots, list) or any(not isinstance(p, str) for p in roots)):
            raise ValueError("invalid ordered compiler root paths")
        if not isinstance(record.get("current_directory"), str):
            raise ValueError("missing compiler working directory")
        if not isinstance(record.get("default_library_path"), str):
            raise ValueError("missing native default library path")
        for field in ("native_compiler_options", "native_harness_options"):
            if not isinstance(record.get(field), dict):
                raise ValueError(f"missing compiler input field: {field}")
        files = record.get("files")
        if not isinstance(files, list):
            raise ValueError("missing native filesystem inventory")
        paths = set()
        for file in files:
            check_file(file)
            if file["path"] in paths:
                raise ValueError("duplicate native filesystem path")
            paths.add(file["path"])
        if record.get("config_source") is not None:
            check_file(record["config_source"])
        manifest.append([f"invocations/{path.name}", hashlib.sha256(content).hexdigest(), len(content)])
        invocations += 1

    return {
        "scope": "harnessutil.CompileFilesEx inputs; not TSZ replay or parity",
        "invocations": invocations,
        "blobs": len(blobs),
        "sha256": hashlib.sha256(json.dumps(manifest, separators=(",", ":")).encode()).hexdigest(),
    }
