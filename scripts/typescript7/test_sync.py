"""Full-tree sync, repeatability, and rejection contracts using real Git histories."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import suite
import sync


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.native = self.root / "native"
        self.corpus = self.native / "nested"
        self.corpus.mkdir(parents=True)
        for repository in (self.native, self.corpus):
            suite.git(repository, "init", "-q")
            (repository / "fixture.bin").write_bytes(b"\x00\xff\r\n")
            suite.git(repository, "add", "fixture.bin")
            self.commit(repository)
        suite.git(self.native, "update-index", "--add", "--cacheinfo",
                  "160000," + suite.git(self.corpus, "rev-parse", "HEAD") + ",nested")
        self.commit(self.native)
        self.old = self.pin()
        self.pin_patch = patch.object(suite, "lock", side_effect=lambda: self.active)
        self.pin_patch.start()
        self.addCleanup(self.pin_patch.stop)
        self.overlay_patch = patch.object(suite, "make_overlay", return_value=None)
        self.overlay_patch.start()
        self.addCleanup(self.overlay_patch.stop)
        self.active = self.old

    def commit(self, repository):
        suite.git(repository, "-c", "user.name=Harness Test", "-c", "user.email=harness@example.invalid",
                  "commit", "-qm", "fixture")

    def pin(self):
        def identity(repository):
            return {"repository": str(repository), "commit": suite.git(repository, "rev-parse", "HEAD"),
                    "tree": suite.git(repository, "rev-parse", "HEAD^{tree}")}
        return dict(identity(self.native), version="7.0.2", corpus=dict(identity(self.corpus), path="nested"))

    def next_release(self):
        (self.native / "fixture.bin").write_bytes(b"\x00\xff\n")
        (self.native / "new-test.go").write_bytes(b"new\n")
        suite.git(self.native, "add", "fixture.bin", "new-test.go")
        suite.git(self.corpus, "rm", "fixture.bin")
        (self.corpus / "case.ts").write_bytes(b"const value = 1;\r\n")
        suite.git(self.corpus, "add", "case.ts")
        self.commit(self.corpus)
        suite.git(self.native, "update-index", "--cacheinfo",
                  "160000," + suite.git(self.corpus, "rev-parse", "HEAD") + ",nested")
        self.commit(self.native)
        self.active = self.pin()
        suite.git(self.native, "checkout", "-q", "--detach", self.old["commit"])
        suite.git(self.corpus, "checkout", "-q", "--detach", self.old["corpus"]["commit"])

    def test_initial_and_repeated_sync_retain_every_native_and_nested_file(self):
        first = sync.sync(self.native, self.root / "first")
        self.assertEqual(first["files"], 2)
        self.assertEqual(first["changes"], {"added": 2})
        second = sync.sync(self.native, self.root / "second", self.root / "first")
        self.assertEqual(second["changes"], {})
        self.assertEqual(second["unchanged"], 2)
        self.assertEqual(first["inventory_sha256"], second["inventory_sha256"])
        self.assertEqual(second["tsz_parity"], "unmeasured")
        self.assertFalse(list((self.root / "second").glob("changes-*.jsonl")))

    def test_release_transition_reports_added_removed_and_exact_byte_changes(self):
        sync.sync(self.native, self.root / "before")
        self.next_release()
        result = sync.sync(self.native, self.root / "after", self.root / "before")
        self.assertEqual(result["changes"], {"added": 2, "modified": 1, "removed": 1})
        self.assertEqual(result["files"], 3)
        suite.verify(self.native)
        records = [json.loads(line) for line in (self.root / "after/changes-0000.jsonl").read_text().splitlines()]
        row = next(row for row in records if row["path"] == "fixture.bin")
        self.assertNotEqual(row["before"]["blob"], row["after"]["blob"])
        self.assertEqual((self.native / "fixture.bin").read_bytes(), b"\x00\xff\n")

    def test_file_mode_changes_are_not_hidden_by_identical_blob_hashes(self):
        sync.sync(self.native, self.root / "before")
        (self.corpus / "fixture.bin").chmod(0o755)
        suite.git(self.corpus, "add", "fixture.bin")
        self.commit(self.corpus)
        suite.git(self.native, "add", "nested")
        self.commit(self.native)
        self.active = self.pin()
        result = sync.sync(self.native, self.root / "after", self.root / "before")
        self.assertEqual(result["changes"], {"modified": 1})
        row = json.loads((self.root / "after/changes-0000.jsonl").read_text())
        self.assertEqual(row["before"]["blob"], row["after"]["blob"])
        self.assertNotEqual(row["before"]["mode"], row["after"]["mode"])

    def test_dirty_nested_inputs_are_preserved_before_any_checkout(self):
        self.next_release()
        (self.corpus / "fixture.bin").write_bytes(b"local changes")
        with self.assertRaisesRegex(ValueError, "modified/untracked"):
            sync.sync(self.native, self.root / "rejected")
        self.assertEqual(suite.git(self.native, "rev-parse", "HEAD"), self.old["commit"])
        self.assertEqual((self.corpus / "fixture.bin").read_bytes(), b"local changes")
        self.assertFalse((self.root / "rejected").exists())

    def test_inconsistent_nested_pin_is_rejected_before_any_checkout(self):
        self.next_release()
        self.active["corpus"] = self.old["corpus"]
        with self.assertRaisesRegex(ValueError, "submodule"):
            sync.sync(self.native, self.root / "rejected")
        self.assertEqual(suite.git(self.native, "rev-parse", "HEAD"), self.old["commit"])

    def test_corrupt_previous_inventory_cannot_report_a_clean_delta(self):
        sync.sync(self.native, self.root / "before")
        shard = self.root / "before/inventory/inventory-0000.jsonl"
        shard.write_bytes(shard.read_bytes().replace(b"100644", b"100755", 1))
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            sync.sync(self.native, self.root / "rejected", self.root / "before")
        self.assertFalse((self.root / "rejected").exists())

    def test_duplicate_inventory_paths_are_rejected_even_with_updated_hash(self):
        sync.sync(self.native, self.root / "before")
        shard = self.root / "before/inventory/inventory-0000.jsonl"
        shard.write_bytes(shard.read_bytes() * 2)
        with self.assertRaisesRegex(ValueError, "unique and sorted"):
            sync.read_inventory(self.root / "before")

    def test_changed_capture_anchor_does_not_publish_sync_success(self):
        with patch.object(suite, "make_overlay", side_effect=ValueError("anchor changed")):
            with self.assertRaisesRegex(ValueError, "anchor changed"):
                sync.sync(self.native, self.root / "rejected")
        self.assertFalse((self.root / "rejected/sync-summary.json").exists())
        suite.verify(self.native)


if __name__ == "__main__":
    unittest.main()
