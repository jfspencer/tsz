"""Run a candidate in an isolated Linux mount namespace with native paths."""

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import tempfile
import uuid

from replay_options import UnsupportedReplay

SYMLINK = 0x08000000  # Go io/fs.ModeSymlink, retained in the native input ledger.


def virtual_path(name):
    path = PurePosixPath(name)
    if not name.startswith("/") or name.startswith("//") or ".." in path.parts or "\0" in name:
        raise UnsupportedReplay(f"virtual path cannot be represented faithfully: {name!r}")
    return path


def runtime_files(binary):
    """Resolve this trusted local ELF binary's loader and shared libraries."""
    result = subprocess.run(["ldd", str(binary)], capture_output=True, text=True)
    lines = result.stdout.splitlines()
    if result.returncode and "not a dynamic executable" not in result.stderr + result.stdout:
        raise UnsupportedReplay("cannot resolve candidate runtime: " + result.stderr.strip())
    loader, libraries = None, []
    for line in lines:
        if "not found" in line:
            raise UnsupportedReplay("candidate runtime dependency is missing: " + line.strip())
        match = re.search(r"(?:=>\s*)?(/\S+)\s+\(0x[0-9a-f]+\)", line)
        if match:
            path = Path(match.group(1)).resolve()
            if "=>" in line:
                libraries.append((Path(match.group(1)).name, path))
            else:
                loader = path
    return loader, libraries


def store_blob(directory, content):
    digest = hashlib.sha256(content).hexdigest()
    target = directory / digest
    if not target.exists():
        target.write_bytes(content)
    elif target.read_bytes() != content:
        raise ValueError("candidate blob hash collision")
    return {"sha256": digest, "byte_length": len(content)}


def stage_files(stage, record, blobs):
    entries = record["files"]
    names = {str(virtual_path(file["path"])) for file in entries}
    if any(name == "/proc" or name.startswith("/proc/") for name in names):
        raise UnsupportedReplay("fixture conflicts with the process runtime's /proc mount")
    if len(names) != len(entries):
        raise UnsupportedReplay("native paths collapse on the Linux filesystem")
    links = []
    for file in entries:
        name = virtual_path(file["path"])
        target = stage.joinpath(*name.parts[1:])
        if file["mode"] not in (0, SYMLINK):
            raise UnsupportedReplay(f"unimplemented native filesystem mode: {file['mode']}")
        if any(str(parent) in names for parent in name.parents if str(parent) != "/"):
            raise UnsupportedReplay("native filesystem entries overlap files or symlink ancestors")
        target.parent.mkdir(parents=True, exist_ok=True)
        content = (blobs / file["sha256"]).read_bytes()
        if file["mode"] == SYMLINK:
            links.append((target, content))
        else:
            target.write_bytes(content)
    for target, link in links:
        os.symlink(link, os.fsencode(target))


def prepare_working_directory(stage, record):
    cwd = virtual_path(record["current_directory"])
    for entry in record["files"]:
        name = virtual_path(entry["path"])
        if entry["mode"] == SYMLINK and (name == cwd or name in cwd.parents):
            # Creating a directory through this link on the host would resolve
            # its absolute target outside the staged root. Leave this adapter
            # gap explicit until directory creation uses a virtual resolver.
            raise UnsupportedReplay("working directory through a symlink requires the virtual host adapter")
    stage.joinpath(*cwd.parts[1:]).mkdir(parents=True, exist_ok=True)
    return cwd


def run_candidate(binary, runtime, record, args, input_blobs, output, timeout, *, structured=True):
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        raise UnsupportedReplay("Linux bubblewrap is required for exact absolute paths")
    with tempfile.TemporaryDirectory(prefix="tsz-native-replay-") as temporary:
        stage = Path(temporary)
        stage_files(stage, record, input_blobs)
        cwd = prepare_working_directory(stage, record)
        control = "/.tsz-replay-" + uuid.uuid4().hex
        control_dir = stage / control[1:]
        control_dir.mkdir()
        command = [bwrap, "--die-with-parent", "--unshare-pid", "--bind", str(stage), "/", "--proc", "/proc",
                   "--clearenv", "--setenv", "LANG", "C.UTF-8",
                   "--setenv", "RAYON_NUM_THREADS", "1", "--chdir", str(cwd),
                   "--ro-bind", str(binary), control + "/candidate"]
        loader, libraries = runtime
        if loader is not None:
            command += ["--ro-bind", str(loader), control + "/loader"]
            for name, path in libraries:
                command += ["--ro-bind", str(path), control + "/lib/" + name]
            launch = [control + "/loader", "--library-path", control + "/lib", control + "/candidate"]
        else:
            launch = [control + "/candidate"]
        structured_args = [
            "--diagnostics-json", control + "/diagnostics.json",
            "--perf-counters-json", control + "/completion.json",
        ] if structured else []
        command += ["--"] + launch + structured_args + args
        with (output / "stdout.bin").open("wb") as stdout, (output / "stderr.bin").open("wb") as stderr:
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)
            state = "observed"
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                state = "timeout"
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        before = {file["path"]: file for file in record["files"]}
        products, removed = [], []
        for root, dirs, files in os.walk(stage, followlinks=False):
            if Path(root) == stage and control[1:] in dirs:
                dirs.remove(control[1:])
            for name in sorted(files + [d for d in dirs if (Path(root) / d).is_symlink()]):
                path = Path(root) / name
                logical = "/" + path.relative_to(stage).as_posix()
                mode = SYMLINK if path.is_symlink() else 0
                content = os.readlink(os.fsencode(path)) if mode == SYMLINK else path.read_bytes()
                digest = hashlib.sha256(content).hexdigest()
                original = before.pop(logical, None)
                if original is None or original["sha256"] != digest or original["mode"] != mode:
                    products.append({"path": logical, "mode": mode,
                                     **store_blob(output.parent / "blobs", content)})
        removed = sorted(before)
        observations = {}
        for name in ("diagnostics.json", "completion.json"):
            path = control_dir / name
            if path.is_file():
                content = path.read_bytes()
                (output / name).write_bytes(content)
                observations[name] = store_blob(output.parent / "blobs", content)
        return {
            "state": state, "process_exit_status": process.returncode,
            "arguments": args, "products": sorted(products, key=lambda p: p["path"]),
            "removed_inputs": removed, "structured_outputs": observations,
            "stdout": store_blob(output.parent / "blobs", (output / "stdout.bin").read_bytes()),
            "stderr": store_blob(output.parent / "blobs", (output / "stderr.bin").read_bytes()),
        }
