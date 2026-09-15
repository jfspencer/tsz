"""Native output integrity and input/result accounting witnesses."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from result_manifest import summarize_results


class ResultManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / 'inputs'
        self.results = self.root / 'results'
        (self.inputs / 'invocations').mkdir(parents=True)
        (self.results / 'invocations').mkdir(parents=True)
        (self.results / 'blobs').mkdir()
        self.identity = '1' * 64
        (self.inputs / 'invocations' / (self.identity + '.json')).write_text('{}')
        content = b'\x00\xff\r\n'
        self.digest = hashlib.sha256(content).hexdigest()
        (self.results / 'blobs' / self.digest).write_bytes(content)
        self.file = dict(path='/out.js', mode=0, byte_length=4, sha256=self.digest)
        self.record = dict(schema=1, input_invocation=self.identity, diagnostics=[],
                           outputs=[self.file], emit=dict(skipped=False, diagnostics=[], reported_files=None), trace='')
        self.path = self.results / 'invocations' / (self.identity + '.json')
        self.write()

    def write(self):
        self.path.write_text(json.dumps(self.record))

    def summary(self):
        return summarize_results(self.results, self.inputs)

    def test_exact_bytes_and_missing_invocations(self):
        summary = self.summary()
        self.assertEqual(summary['output_files'], 1)
        self.assertEqual(summary['missing_invocations'], [])
        self.assertEqual(summary, self.summary())
        self.path.unlink()
        summary = self.summary()
        self.assertEqual(summary['invocations'], 0)
        self.assertEqual(summary['missing_invocations'], [self.identity])

    def test_corrupt_blob_and_invalid_reference_are_rejected(self):
        (self.results / 'blobs' / self.digest).write_bytes(b'\x00\xff\n')
        with self.assertRaisesRegex(ValueError, 'blob/hash'):
            self.summary()
        (self.results / 'blobs' / self.digest).write_bytes(b'\x00\xff\r\n')
        self.file['byte_length'] = 3
        self.write()
        with self.assertRaisesRegex(ValueError, 'blob reference'):
            self.summary()

    def test_extra_and_duplicate_output_identities_are_rejected(self):
        self.record['input_invocation'] = '2' * 64
        self.write()
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            self.summary()
        self.record['input_invocation'] = self.identity
        self.record['outputs'].append(self.file)
        self.write()
        with self.assertRaisesRegex(ValueError, 'duplicate or unordered'):
            self.summary()

    def test_diagnostic_payload_order_and_null_emit_are_distinct(self):
        diagnostic = dict(source=self.file, byte_start=0, byte_length=1, code=1003, category='error',
                          text='Identifier expected.', message_chain=[], related_information=[],
                          reports_unnecessary=False, reports_deprecated=False, skipped_on_no_emit=False)
        self.record['diagnostics'] = [diagnostic, dict(diagnostic, code=1005, text="';' expected.")]
        self.write()
        first = self.summary()['sha256']
        self.record['diagnostics'].reverse()
        self.write()
        self.assertNotEqual(first, self.summary()['sha256'])
        first = self.summary()['sha256']
        self.record['emit'] = None
        self.write()
        self.assertNotEqual(first, self.summary()['sha256'])
        self.record['diagnostics'][0]['message_chain'] = None
        self.write()
        with self.assertRaisesRegex(ValueError, 'ordered native diagnostics'):
            self.summary()


if __name__ == '__main__':
    unittest.main()
