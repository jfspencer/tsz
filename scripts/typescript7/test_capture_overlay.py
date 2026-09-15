"""Run capture contracts against the pinned native Go types and toolchain."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import suite


class NativeCaptureTests(unittest.TestCase):
    def test_go_capture_contracts(self):
        checkout = suite.ROOT / "TypeScript7"
        suite.verify(checkout)
        with tempfile.TemporaryDirectory(prefix="tsz-capture-contracts-") as temp:
            overlay = suite.make_overlay(checkout, Path(temp))
            content = json.loads(overlay.read_text())
            content["Replace"][str(checkout / "internal/testutil/harnessutil/tsz_capture_inputs_test.go")] = str(
                suite.HERE / "capture_inputs_test.go")
            overlay.write_text(json.dumps(content))
            run = subprocess.run([
                "go", "test", f"-overlay={overlay}", "-count=1", "-timeout=60s",
                "-run=^TestTszCapture", "./internal/testutil/harnessutil",
            ], cwd=checkout, env=dict(os.environ, CGO_ENABLED="0"), capture_output=True, text=True, timeout=90)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        suite.verify(checkout)


if __name__ == "__main__":
    unittest.main()
