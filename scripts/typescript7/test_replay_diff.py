"""Comparison integrity and exact projection contracts; synthetic records are not oracle passes."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from input_manifest import summarize_inputs
from replay_diff import compare_invocation, diff_replay, filesystem_changes, native_headers
from replay_manifest import summarize_replay
from replay_namespace import store_blob, SYMLINK
from result_manifest import summarize_results
from suite import lock


class ReplayDiffTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.oracle, self.candidate = self.root / 'oracle', self.root / 'candidate'
        self.inputs = self.oracle / 'inputs'
        self.results = self.oracle / 'compilations'
        for path in (self.inputs, self.results):
            (path / 'invocations').mkdir(parents=True)
            (path / 'blobs').mkdir()
        (self.candidate / 'blobs').mkdir(parents=True)
        self.source = dict(schema=1, package='test/compiler', test='TestFixture/renamed', sequence=0,
                           current_directory='/.src', roots=['/.src/a.ts'], default_library_path='/.lib',
                           native_compiler_options={}, native_harness_options={}, config_source=None,
                           files=[dict(path='/.src/a.ts', mode=0,
                                       **store_blob(self.inputs / 'blobs', b'const value = 1;\r\n'))])
        self.identity = hashlib.sha256(b'test/compiler\0TestFixture/renamed\x000').hexdigest()
        self.input_path = self.inputs / 'invocations' / (self.identity + '.json')
        self.input_path.write_text(json.dumps(self.source))
        self.native_path = self.results / 'invocations' / self.input_path.name
        self.native = dict(schema=1, input_invocation=self.identity, diagnostics=[],
                           outputs=[dict(path='/.src/a.js', mode=0,
                                         **store_blob(self.results / 'blobs', b'const value = 1;\r\n'))],
                           emit=dict(skipped=False, diagnostics=[], reported_files=None), trace='')
        self.row_dir = self.candidate / self.identity
        self.row_dir.mkdir()
        self.actual = dict(state='observed', process_exit_status=0, arguments=self.source['roots'],
                           package=self.source['package'], test=self.source['test'], sequence=0,
                           input_record_sha256=hashlib.sha256(self.input_path.read_bytes()).hexdigest(),
                           products=[dict(path='/.src/a.js', mode=0,
                                          **store_blob(self.candidate / 'blobs', b'const value = 1;\r\n'))],
                           removed_inputs=[], structured_outputs={})
        for name in ('stdout', 'stderr'):
            self.actual[name] = self.sidecar(name + '.bin', b'')
        self.actual['structured_outputs'] = {
            'diagnostics.json': self.sidecar('diagnostics.json', b'[]'),
            'completion.json': self.sidecar('completion.json', b'{"stats":{"semantic_completion":"complete"}}'),
        }
        self.save()

    def sidecar(self, name, data):
        (self.row_dir / name).write_bytes(data)
        return store_blob(self.candidate / 'blobs', data)

    def save(self):
        self.native_path.write_text(json.dumps(self.native))
        (self.row_dir / 'result.json').write_text(json.dumps(self.actual))
        input_capture = summarize_inputs(self.inputs)
        (self.oracle / 'summary.json').write_text(json.dumps(dict(
            oracle=lock(), exit_status=0, input_capture=input_capture,
            result_capture=summarize_results(self.results, self.inputs))))
        capture = summarize_replay(self.candidate, self.inputs)
        (self.candidate / 'summary.json').write_text(json.dumps(dict(
            oracle=lock(), input_capture=input_capture, candidate_capture=capture,
            candidate_sha256='a' * 64, invocations=1, counts=capture['counts'])))

    def compare(self):
        return diff_replay(self.oracle, self.candidate, self.root / 'diff')

    def test_equal_complete_projections_still_do_not_claim_native_suite_parity(self):
        summary = self.compare()
        self.assertEqual(summary['invocations'], 1)
        self.assertEqual(summary['counts']['diagnostic_headers'], {'match': 1})
        self.assertEqual(summary['counts']['filesystem_changes'], {'match': 1})
        self.assertEqual(summary['counts']['completion'], {'complete': 1})
        self.assertEqual(summary['tsz_parity'], 'unmeasured')
        shard = summary['shards'][0]
        data = (self.root / 'diff' / shard['path']).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), shard['sha256'])

    def test_newline_only_difference_and_extra_output_remain_mismatches(self):
        self.actual['products'][0].update(store_blob(self.candidate / 'blobs', b'const value = 1;\n'))
        self.actual['products'].append(dict(path='/extra.map', mode=0,
                                             **store_blob(self.candidate / 'blobs', b'\0\xff')))
        self.save()
        self.assertEqual(self.compare()['counts']['filesystem_changes'], {'mismatch': 1})

    def test_missing_output_and_deleted_input_are_not_empty_success(self):
        self.actual['products'] = []
        self.actual['removed_inputs'] = ['/.src/a.ts']
        self.save()
        self.assertEqual(self.compare()['counts']['filesystem_changes'], {'mismatch': 1})

    def test_unchanged_write_is_only_a_filesystem_projection(self):
        self.native['outputs'][0]['path'] = '/.src/a.ts'
        self.actual['products'] = []
        self.save()
        result = self.compare()
        self.assertEqual(result['counts']['filesystem_changes'], {'match': 1})
        self.assertIn('emit write events, skipped state and resolution traces', result['remaining'])
        self.assertEqual(result['tsz_parity'], 'unmeasured')

    def test_unicode_byte_spans_convert_to_utf16_without_touching_messages(self):
        data = '/*😀*/\r\nlet café = 1;'.encode()
        source = dict(path='/renamed.ts', mode=0, **store_blob(self.results / 'blobs', data))
        start = data.index('café'.encode())
        diagnostic = dict(source=source, byte_start=start, byte_length=5, code=9999,
                          category='error', text='Keep\r\nthese bytes')
        header = native_headers([diagnostic], self.results / 'blobs')[0]
        self.assertEqual(header['start'], len(data[:start].decode().encode('utf-16-le')) // 2)
        self.assertEqual(header['length'], 4)
        self.assertEqual(header['text'], 'Keep\r\nthese bytes')
        diagnostic['byte_start'] = 3  # Inside the emoji, not a valid byte boundary.
        with self.assertRaises(UnicodeError):
            native_headers([diagnostic], self.results / 'blobs')

    def test_order_and_diagnostic_duplicates_are_observable(self):
        self.native['diagnostics'] = [dict(
            source=None, byte_start=-1, byte_length=0, code=1003, category='error', text='first',
            message_chain=[], related_information=[], reports_unnecessary=False,
            reports_deprecated=False, skipped_on_no_emit=False)] * 2
        actual = [dict(file='', start=0, length=0, code=1003, category='error', message_text='first')]
        self.actual['structured_outputs']['diagnostics.json'] = self.sidecar('diagnostics.json', json.dumps(actual).encode())
        self.save()
        self.assertEqual(self.compare()['counts']['diagnostic_headers'], {'mismatch': 1})

    def test_unsupported_timeout_and_signal_keep_the_invocation_visible(self):
        for state in ('unsupported-adapter', 'timeout', 'signal'):
            actual = dict(self.actual, state=state if state != 'signal' else 'observed',
                          process_exit_status=-15, reason='needs an adapter')
            row = compare_invocation(self.native, actual, self.source,
                                     self.results / 'blobs', self.candidate / 'blobs')
            self.assertEqual(row['diagnostic_headers']['state'], 'unavailable')
            self.assertEqual(row['filesystem_changes']['state'], 'unavailable')

    def test_missing_structured_output_is_unavailable_even_with_zero_exit(self):
        self.actual['structured_outputs'] = {}
        self.save()
        summary = self.compare()
        self.assertEqual(summary['counts']['diagnostic_headers'], {'unavailable': 1})
        self.assertEqual(summary['counts']['completion'], {'unavailable': 1})

    def test_symlink_output_does_not_claim_write_event_equivalence(self):
        self.source['files'].append(dict(path='/.src/link', mode=SYMLINK))
        self.native['outputs'][0]['path'] = '/.src/link/a.js'
        self.assertEqual(filesystem_changes(self.native, self.actual, self.source)['state'], 'unavailable')

    def test_missing_and_extra_candidate_invocations_fail_integrity(self):
        path = self.row_dir / 'result.json'
        content = path.read_bytes()
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'missing candidate invocations'):
            self.compare()
        path.write_bytes(content)
        extra = self.candidate / ('b' * 64)
        extra.mkdir()
        (extra / 'result.json').write_bytes(content)
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            self.compare()

    def test_altered_record_sidecar_or_blob_cannot_be_compared(self):
        path = self.row_dir / 'result.json'
        self.actual['process_exit_status'] = 3
        path.write_text(json.dumps(self.actual))
        with self.assertRaisesRegex(ValueError, 'candidate capture changed'):
            self.compare()
        self.save()
        (self.row_dir / 'diagnostics.json').write_bytes(b'[ ]')
        with self.assertRaisesRegex(ValueError, 'sidecar/blob'):
            self.compare()
        (self.row_dir / 'diagnostics.json').write_bytes(b'[]')
        (self.candidate / 'blobs' / self.actual['products'][0]['sha256']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'blob/hash'):
            self.compare()

    def test_changed_native_result_or_different_inputs_are_rejected(self):
        self.native['trace'] = 'changed after capture'
        self.native_path.write_text(json.dumps(self.native))
        with self.assertRaisesRegex(ValueError, 'native result capture changed'):
            self.compare()
        self.save()
        self.actual['input_record_sha256'] = 'c' * 64
        (self.row_dir / 'result.json').write_text(json.dumps(self.actual))
        with self.assertRaisesRegex(ValueError, 'input record changed'):
            self.compare()


if __name__ == '__main__':
    unittest.main()
