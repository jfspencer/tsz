"""Protect full-domain accounting and release pin verification."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import suite


class AccountingTests(unittest.TestCase):
    def test_leaf_counts_do_not_promote_skips_or_count_parent_passes(self):
        def event(name, action):
            return {"Package": "oracle", "Test": name, "Action": action}

        result = suite.summarize_events([
            event("TestSuite", "run"),
            event("TestSuite/valid", "run"), event("TestSuite/valid", "pass"),
            event("TestSuite/unavailable", "skip"),
            event("TestSuite/interrupted", "run"),
            event("TestSuite", "fail"),
            {"Package": "oracle", "Action": "fail"},
        ])
        self.assertEqual(result["leaf_counts"], {"pass": 1, "skip": 1, "uncompleted": 1})
        self.assertEqual(result["packages"], {"oracle": "fail"})
        self.assertEqual(result["failed_parents"], [{"package": "oracle", "test": "TestSuite"}])

    def test_same_test_name_in_different_packages_is_not_merged(self):
        result = suite.summarize_events([
            {"Package": package, "Test": "TestExample", "Action": action}
            for package, action in (("first", "pass"), ("second", "fail"))
        ])
        self.assertEqual(result["leaf_counts"], {"fail": 1, "pass": 1})

    def test_empty_run_never_reports_parity(self):
        result = suite.summarize_events([])
        self.assertEqual(result["leaf_counts"], {})
        self.assertNotIn("tsz_parity", result)

    def test_current_release_pins_agree(self):
        self.assertEqual(suite.lock()["version"], "7.0.2")

    def test_development_npm_pin_is_rejected(self):
        original_read = Path.read_text

        def changed_read(path, *args, **kwargs):
            if path == suite.ROOT / "scripts/package.json":
                return json.dumps({"devDependencies": {"typescript": "7.1.0-dev"}})
            return original_read(path, *args, **kwargs)

        with patch.object(Path, "read_text", changed_read):
            with self.assertRaisesRegex(ValueError, "production 7.0.2"):
                suite.lock()


class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "fixture.ts").write_bytes(b"const value = 1;\r\n")
        suite.git(self.root, "add", ".")
        suite.git(self.root, "-c", "user.name=Harness Test", "-c", "user.email=harness@example.invalid",
                  "commit", "-qm", "fixture")
        self.pin = {"commit": suite.git(self.root, "rev-parse", "HEAD"),
                    "tree": suite.git(self.root, "rev-parse", "HEAD^{tree}")}

    def test_tracked_modification_invalidates_oracle(self):
        suite.verify_tree(self.root, self.pin)
        (self.root / "fixture.ts").write_text("const value = 2;\n")
        with self.assertRaisesRegex(ValueError, "modified/untracked"):
            suite.verify_tree(self.root, self.pin)

    def test_missing_nested_checkout_cannot_resolve_parent_git_head(self):
        missing = self.root / "empty-submodule"
        missing.mkdir()
        with self.assertRaisesRegex(ValueError, "independent oracle checkout"):
            suite.verify_tree(missing, self.pin)

    def test_sparse_inputs_are_rejected(self):
        suite.git(self.root, "update-index", "--skip-worktree", "fixture.ts")
        with self.assertRaisesRegex(ValueError, "sparse"):
            suite.verify_tree(self.root, self.pin)

    def test_assume_unchanged_cannot_hide_mutated_oracle_input(self):
        suite.git(self.root, "update-index", "--assume-unchanged", "fixture.ts")
        (self.root / "fixture.ts").write_text("const value = false;\n")
        with self.assertRaisesRegex(ValueError, "assume-unchanged"):
            suite.verify_tree(self.root, self.pin)

    def test_inventory_includes_non_source_fixtures_and_nested_corpus(self):
        pin = dict(self.pin, corpus={"path": "nested", "commit": "b" * 40})
        native = "100644 blob " + "a" * 40 + "\tfixture.bin\0" + "160000 commit " + "b" * 40 + "\tnested\0"
        child = "100644 blob " + "c" * 40 + "\tdata.json"
        with patch.object(suite, "verify", return_value=pin), patch.object(
            suite, "git", side_effect=[native, child]
        ):
            report = suite.inventory(self.root, self.root / "inventory")
        records = [json.loads(line) for line in (self.root / "inventory/inventory-0000.jsonl").read_text().splitlines()]
        self.assertEqual([r["path"] for r in records], ["fixture.bin", "nested/data.json"])
        self.assertEqual(report["files"], 2)
        self.assertEqual(report["tsz_parity"], "unmeasured")


if __name__ == "__main__":
    unittest.main()
