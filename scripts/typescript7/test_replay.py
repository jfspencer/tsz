import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from replay_namespace import run_candidate, runtime_files, stage_files, prepare_working_directory, SYMLINK
from replay_options import command_line, option_value, UnsupportedReplay


def fixture():
    return {
        "callers": ["github.com/microsoft/typescript-go/internal/testrunner.newCompilerTest"],
        "config_source": None, "roots": ["/.src/first.ts", "/second.ts"],
        "current_directory": "/.src", "files": [],
        "native_harness_options": {"UseCaseSensitiveFileNames": True},
        "native_compiler_options": {"strict": False, "target": 9},
    }


class OptionTests(unittest.TestCase):
    def test_native_enum_values_and_explicit_false_are_not_reinterpreted(self):
        schema = {
            "strict": {"name": "strict", "kind": "boolean", "config_only": False},
            "target": {"name": "target", "kind": "enum", "config_only": False,
                       "enum": {"es2022": 9, "es2025": 12}},
        }
        self.assertEqual(command_line(fixture(), schema), [
            "--ignoreConfig", "--strict", "false", "--target", "es2022", "/.src/first.ts", "/second.ts"])
        with self.assertRaises(UnsupportedReplay):
            option_value(True, schema["target"])
        with self.assertRaises(UnsupportedReplay):
            command_line(fixture(), {})

    def test_lists_use_upstream_element_enum_and_do_not_drop_unknown_items(self):
        schema = {"kind": "list", "name": "lib", "element": {
            "kind": "enum", "name": "lib", "enum": {"es2022": "lib.es2022.d.ts", "dom": "lib.dom.d.ts"}}}
        self.assertEqual(option_value(["lib.es2022.d.ts", "lib.dom.d.ts"], schema), "es2022,dom")
        with self.assertRaises(UnsupportedReplay):
            option_value(["unknown"], schema)

    def test_auxiliary_oracle_output_is_never_replayed_as_source(self):
        record = fixture()
        record["callers"] = ["github.com/microsoft/typescript-go/internal/testutil/tsbaseline.compileDeclarationFiles"]
        with self.assertRaisesRegex(UnsupportedReplay, "auxiliary"):
            command_line(record, {})

    def test_unimplemented_host_and_config_semantics_remain_visible(self):
        for edit in (lambda r: r.update(config_source={}),
                     lambda r: r["native_harness_options"].update(UseCaseSensitiveFileNames=False),
                     lambda r: r["native_harness_options"].update(CaptureSuggestions=True),
                     lambda r: r.update(roots=[])):
            record = fixture()
            edit(record)
            with self.assertRaises(UnsupportedReplay):
                command_line(record, {})

    def test_staging_never_follows_a_fixture_link_into_the_host(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage, blobs = root / "stage", root / "blobs"
            stage.mkdir()
            blobs.mkdir()
            target = str(root / "outside").encode()
            digest = hashlib.sha256(target).hexdigest()
            (blobs / digest).write_bytes(target)
            record = fixture()
            record.update(current_directory="/link/new", files=[{
                "path": "/link", "mode": SYMLINK, "sha256": digest}])
            stage_files(stage, record, blobs)
            with self.assertRaises(UnsupportedReplay):
                prepare_working_directory(stage, record)
            self.assertFalse((root / "outside").exists())


@unittest.skipUnless(sys.platform == "linux" and shutil.which("bwrap"), "Linux namespace adapter requires bubblewrap")
class NamespaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.binary = cls.root / "candidate"
        source = cls.root / "candidate.c"
        source.write_text('''#include <stdio.h>
#include <string.h>
#include <unistd.h>
int main(int argc, char **argv) {
  for (int i=1; i<argc; i++) if (!strcmp(argv[i], "--sleep")) sleep(60);
  FILE *in=fopen(argv[argc-1], "rb"), *out=fopen("/generated.bin", "wb");
  if (!in || !out) return 7;
  char cwd[4096]; puts(getcwd(cwd, sizeof(cwd)));
  int c; while ((c=fgetc(in)) != EOF) fputc(c,out);
  fclose(in); fclose(out); return 3;
}''')
        subprocess.run(["cc", str(source), "-o", str(cls.binary)], check=True, capture_output=True)
        cls.runtime = runtime_files(cls.binary)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_fixture(self, sleep=False):
        directory = self.root / ("timeout" if sleep else "bytes")
        directory.mkdir()
        blobs, destination = directory / "blobs", directory / "row"
        blobs.mkdir()
        destination.mkdir()
        content = b"\x00\xff\r\n"
        digest = hashlib.sha256(content).hexdigest()
        (blobs / digest).write_bytes(content)
        target = b"/original.bin"
        target_digest = hashlib.sha256(target).hexdigest()
        (blobs / target_digest).write_bytes(target)
        record = fixture()
        record["files"] = [
            {"path": "/original.bin", "mode": 0, "sha256": digest},
            {"path": "/.src/link.bin", "mode": SYMLINK, "sha256": target_digest},
        ]
        result = run_candidate(self.binary, self.runtime, record,
                               (["--sleep"] if sleep else []) + ["/.src/link.bin"],
                               blobs, destination, .1 if sleep else 5)
        return result, directory, content

    def test_absolute_paths_symlinks_and_binary_outputs_survive(self):
        result, directory, content = self.run_fixture()
        self.assertEqual(result["state"], "observed")
        self.assertEqual(result["process_exit_status"], 3)
        self.assertEqual((directory / "row/stdout.bin").read_bytes(), b"/.src\n")
        self.assertEqual(result["removed_inputs"], [])
        self.assertEqual(len(result["products"]), 1)
        product = result["products"][0]
        self.assertEqual(product["path"], "/generated.bin")
        self.assertEqual((directory / "blobs" / product["sha256"]).read_bytes(), content)

    def test_timeout_is_retained_without_a_parity_claim(self):
        result, _, _ = self.run_fixture(sleep=True)
        self.assertEqual(result["state"], "timeout")
        self.assertNotEqual(result["process_exit_status"], 0)
        self.assertNotIn("pass", result)


if __name__ == "__main__":
    unittest.main()
