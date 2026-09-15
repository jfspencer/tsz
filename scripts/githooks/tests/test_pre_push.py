"""A branch push must not launch a cleanup process or erase measurement evidence."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class PrePushTests(unittest.TestCase):
    def test_branch_push_preserves_ignored_artifacts_without_scheduling_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hook = root / "scripts/githooks/pre-push"
            hook.parent.mkdir(parents=True)
            shutil.copyfile(Path(__file__).resolve().parents[1] / "pre-push", hook)
            cleanup = root / "scripts/setup/clean.sh"
            cleanup.parent.mkdir()
            cleanup.write_text('#!/bin/sh\ntouch "$TEST_ROOT/cleanup-called"\nrm -rf "$TEST_ROOT/artifacts"\n')
            cleanup.chmod(0o755)
            artifact = root / "artifacts/evidence.json"
            artifact.parent.mkdir()
            artifact.write_bytes(b'{"raw":"retained"}\n')
            # Make any old deferred cleanup run immediately inside this disposable fixture.
            binaries = root / "bin"
            binaries.mkdir()
            sleeper = binaries / "sleep"
            sleeper.write_text('#!/bin/sh\ntouch "$TEST_ROOT/background-scheduled"\n')
            sleeper.chmod(0o755)
            environment = dict(os.environ, TEST_ROOT=str(root), PATH=str(binaries) + os.pathsep + os.environ["PATH"])
            for key in ("TSZ_SKIP_HOOKS", "TSZ_SKIP_PUSH_TESTS"):
                environment.pop(key, None)
            result = subprocess.run(["bash", str(hook)], input="refs/heads/work abc refs/heads/work def\n",
                                    text=True, capture_output=True, env=environment, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(artifact.read_bytes(), b'{"raw":"retained"}\n')
            self.assertFalse((root / "cleanup-called").exists())
            self.assertFalse((root / "background-scheduled").exists())


if __name__ == "__main__":
    unittest.main()
