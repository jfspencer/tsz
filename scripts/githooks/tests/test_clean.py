"""Explicit cleanup must preserve tracked dependency locks in nested oracle repos."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class CleanupTests(unittest.TestCase):
    def test_tracked_lockfiles_survive_explicit_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cleaner = root / "scripts/setup/clean.sh"
            cleaner.parent.mkdir(parents=True)
            shutil.copyfile(Path(__file__).resolve().parents[2] / "setup/clean.sh", cleaner)
            nested = root / "TypeScript7"
            nested.mkdir()
            for repository in (root, nested):
                subprocess.run(["git", "init", "-q", str(repository)], check=True)
                (repository / "package-lock.json").write_bytes(b'{"lockfileVersion":3}\n')
                subprocess.run(["git", "-C", str(repository), "add", "package-lock.json"], check=True)
            subprocess.run(["git", "-C", str(root), "add", "scripts/setup/clean.sh"], check=True)
            result = subprocess.run(["bash", str(cleaner), "--quiet"], capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            for repository in (root, nested):
                self.assertEqual((repository / "package-lock.json").read_bytes(), b'{"lockfileVersion":3}\n')
                result = subprocess.run(["git", "-C", str(repository), "diff", "--name-only"],
                                        capture_output=True, check=True)
                self.assertEqual(result.stdout, b"")


if __name__ == "__main__":
    unittest.main()
