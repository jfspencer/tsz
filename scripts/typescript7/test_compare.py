import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from compare import compare, read_products


def product(content="let value = 1;\r\n", **fields):
    return {"test": "TestSubmodule/example.ts/output", "path": "submodule/compiler/example.js",
            "content": content, "absent": content == "<no content>",
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
            "completion": "complete", **fields}


def keyed(record):
    return {(record["test"], record["path"]): record}


class ComparisonTests(unittest.TestCase):
    def test_newlines_and_whitespace_are_observable(self):
        expected = keyed(product())
        self.assertEqual(compare(expected, expected)[0]["status"], "pass")
        self.assertEqual(compare(expected, keyed(product("let value = 1;\n")))[0]["status"], "mismatch")

    def test_incomplete_equal_content_is_not_a_pass(self):
        for state in ("deferred", "cycle", "limit", "unsupported", "crash", "timeout"):
            with self.subTest(state=state):
                actual = keyed(product(completion=state))
                self.assertEqual(compare(keyed(product()), actual)[0]["status"], state)

    def test_absence_is_a_required_product(self):
        expected = keyed(product("<no content>"))
        self.assertEqual(compare(expected, {})[0]["status"], "missing")
        self.assertEqual(compare(expected, keyed(product("")))[0]["status"], "mismatch")

    def test_extra_products_remain_failures(self):
        actual = keyed(product()) | keyed(product(path="unexpected.js"))
        self.assertEqual(sorted(r["status"] for r in compare(keyed(product()), actual)), ["extra", "pass"])

    def test_empty_oracle_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "empty oracle"):
            compare({}, {})

    def test_payload_reader_rejects_duplicate_keys_corruption_and_unclaimed_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            first, second = directory / "1.json", directory / "2.json"
            first.write_text(json.dumps(product()))
            self.assertEqual(len(read_products(directory, candidate=True)), 1)
            second.write_text(first.read_text())
            with self.assertRaisesRegex(ValueError, "duplicate"):
                read_products(directory)
            second.unlink()
            first.write_text(json.dumps(product(sha256="0" * 64)))
            with self.assertRaisesRegex(ValueError, "content/hash"):
                read_products(directory)
            record = product()
            del record["completion"]
            first.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "completion"):
                read_products(directory, candidate=True)


if __name__ == "__main__":
    unittest.main()
