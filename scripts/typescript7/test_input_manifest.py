import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from input_manifest import summarize_inputs
from suite import make_overlay


class InputManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "blobs").mkdir()
        (self.root / "invocations").mkdir()
        self.content = b"\x00\x80\xff\r\n"
        self.digest = hashlib.sha256(self.content).hexdigest()
        (self.root / "blobs" / self.digest).write_bytes(self.content)
        self.record = {
            "schema": 1, "package": "native/testrunner", "test": "TestSuite/variant", "sequence": 0,
            "current_directory": "/.src", "roots": ["/.src/a.ts", "/.src/b.ts"],
            "default_library_path": "bundled:///libs",
            "files": [{"path": "/.src/a.ts", "mode": 0, "byte_length": 5, "sha256": self.digest}],
            "native_compiler_options": {"target": 9, "strict": False},
            "native_harness_options": {"UseCaseSensitiveFileNames": False},
            "config_source": None, "extended_config_paths": None,
        }
        self.write_record()

    def write_record(self):
        r = self.record
        key = hashlib.sha256(f'{r["package"]}\0{r["test"]}\0{r["sequence"]}'.encode()).hexdigest()
        path = self.root / "invocations" / (key + ".json")
        path.write_text(json.dumps(r))
        return path

    def test_binary_bytes_and_native_options_are_preserved(self):
        report = summarize_inputs(self.root)
        self.assertEqual(report["invocations"], 1)
        self.assertEqual(report["blobs"], 1)
        self.assertEqual((self.root / "blobs" / self.digest).read_bytes(), self.content)
        original = report["sha256"]
        self.record["native_compiler_options"].pop("strict")
        self.write_record()
        self.assertNotEqual(summarize_inputs(self.root)["sha256"], original, "false and unset are distinct")

    def test_ordered_roots_and_case_sensitivity_change_manifest(self):
        original = summarize_inputs(self.root)["sha256"]
        self.record["roots"].reverse()
        self.write_record()
        self.assertNotEqual(summarize_inputs(self.root)["sha256"], original)
        self.record["roots"].reverse()
        self.record["native_harness_options"]["UseCaseSensitiveFileNames"] = True
        self.write_record()
        self.assertNotEqual(summarize_inputs(self.root)["sha256"], original)

    def test_repeated_invocations_and_package_identity_are_not_collapsed(self):
        self.record["sequence"] = 1
        self.write_record()
        self.record["package"] = "native/another_package"
        self.write_record()
        self.assertEqual(summarize_inputs(self.root)["invocations"], 3)

    def test_symlink_target_bytes_and_mode_are_inputs(self):
        original = summarize_inputs(self.root)["sha256"]
        target = b"/.src/a.ts"
        digest = hashlib.sha256(target).hexdigest()
        (self.root / "blobs" / digest).write_bytes(target)
        self.record["files"].append({"path": "/.src/link.ts", "mode": 0x08000000,
                                     "byte_length": len(target), "sha256": digest})
        self.write_record()
        self.assertNotEqual(summarize_inputs(self.root)["sha256"], original)

    def test_corruption_and_missing_blob_fail_closed(self):
        blob = self.root / "blobs" / self.digest
        blob.write_bytes(b"different")
        with self.assertRaisesRegex(ValueError, "blob/hash"):
            summarize_inputs(self.root)
        blob.unlink()
        with self.assertRaisesRegex(ValueError, "blob reference"):
            summarize_inputs(self.root)

    def test_duplicate_paths_or_invocations_fail_closed(self):
        self.record["files"] *= 2
        self.write_record()
        with self.assertRaisesRegex(ValueError, "duplicate native filesystem"):
            summarize_inputs(self.root)
        self.record["files"] = self.record["files"][:1]
        path = self.write_record()
        path.with_name("z.json").write_bytes(path.read_bytes())
        with self.assertRaisesRegex(ValueError, "duplicate compiler invocation"):
            summarize_inputs(self.root)

    def test_identity_and_size_are_checked(self):
        self.record["files"][0]["byte_length"] = 6
        self.write_record()
        with self.assertRaisesRegex(ValueError, "blob reference"):
            summarize_inputs(self.root)
        self.record["files"][0]["byte_length"] = 5
        path = self.write_record()
        path.rename(path.with_name("wrong.json"))
        with self.assertRaisesRegex(ValueError, "filename/identity"):
            summarize_inputs(self.root)


class OverlayTests(unittest.TestCase):
    def test_reporting_hooks_preserve_native_sources_and_reject_changed_anchor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            baseline = root / "internal/testutil/baseline/baseline.go"
            harness = root / "internal/testutil/harnessutil/harnessutil.go"
            baseline.parent.mkdir(parents=True)
            harness.parent.mkdir(parents=True)
            baseline.write_text('\t\trecordBaseline(t, filepath.Join(subfolder, fileName))\n'
                                '\trecordBaseline(t, filepath.Join(opts.Subfolder, fileName))\n')
            source = '\tfs := vfstest.FromMap(testfs, harnessOptions.UseCaseSensitiveFileNames)\n'
            harness.write_text(source)
            output = root / "output"
            output.mkdir()
            overlay = json.loads(make_overlay(root, output).read_text())["Replace"]
            self.assertEqual(harness.read_text(), source)
            patched = Path(overlay[str(harness)]).read_text()
            self.assertEqual(patched.count("tszCaptureCompilation("), 1)
            self.assertTrue(patched.endswith(source))
            self.assertTrue(Path(overlay[str(harness.with_name("tsz_capture_inputs.go"))]).is_file())
            harness.write_text(source * 2)
            with self.assertRaisesRegex(ValueError, "input capture anchor"):
                make_overlay(root, output)


if __name__ == "__main__":
    unittest.main()
