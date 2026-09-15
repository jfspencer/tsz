#!/usr/bin/env python3
"""Diff native results against candidate observations without claiming native-test passes."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

from input_manifest import summarize_inputs
from replay_manifest import summarize_replay
from replay_namespace import SYMLINK
from result_manifest import summarize_results
from suite import lock


def unavailable(reason):
    return {'state': 'unavailable', 'reason': reason}


def compare_ordered(expected, actual):
    differences = []
    for index in range(max(len(expected), len(actual))):
        left = expected[index] if index < len(expected) else None
        right = actual[index] if index < len(actual) else None
        if left != right:
            differences.append({'index': index, 'expected': left, 'actual': right})
    digest = lambda rows: hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'state': 'mismatch' if differences else 'match',
            'expected_count': len(expected), 'actual_count': len(actual),
            'expected_sha256': digest(expected), 'actual_sha256': digest(actual),
            'differences': differences}


def native_headers(diagnostics, blobs):
    """Convert byte positions only; retain diagnostic order and original text."""
    headers = []
    for diagnostic in diagnostics:
        source = diagnostic['source']
        start, length, path = None, None, None
        if source is not None:
            data = (blobs / source['sha256']).read_bytes()
            begin, size = diagnostic['byte_start'], diagnostic['byte_length']
            if begin < 0 or size < 0 or begin + size > len(data):
                raise ValueError('native diagnostic span is outside its source')
            # Strict decoding rejects an offset within a UTF-8 code point.
            start = len(data[:begin].decode('utf-8').encode('utf-16-le')) // 2
            length = len(data[begin:begin + size].decode('utf-8').encode('utf-16-le')) // 2
            path = source['path']
        headers.append(dict(file=path, start=start, length=length, code=diagnostic['code'],
                            category=diagnostic['category'], text=diagnostic['text']))
    return headers


def candidate_headers(diagnostics):
    if not isinstance(diagnostics, list):
        raise ValueError('candidate diagnostics are not an ordered list')
    headers = []
    for d in diagnostics:
        if (not isinstance(d, dict) or not isinstance(d.get('file'), str)
                or not isinstance(d.get('message_text'), str)
                or d.get('category') not in ('error', 'warning', 'suggestion', 'message')
                or any(type(d.get(k)) is not int or d[k] < 0 for k in ('start', 'length', 'code'))):
            raise ValueError('invalid candidate diagnostic header')
        headers.append(dict(file=d['file'] or None, start=d['start'] if d['file'] else None,
                            length=d['length'] if d['file'] else None, code=d['code'],
                            category=d['category'], text=d['message_text']))
    return headers


def filesystem_changes(native, candidate, inputs):
    # The process adapter observes a filesystem delta, not the emitter's write
    # events. Compare the same projection of native outputs. Same-byte writes
    # remain unmeasured as emit events, even if this projection matches.
    original = {f['path']: f for f in inputs['files']}
    links = [PurePosixPath(f['path']) for f in inputs['files'] if f['mode'] == SYMLINK]
    expected = []
    for output in native['outputs']:
        path = PurePosixPath(output['path'])
        if any(link == path or link in path.parents for link in links):
            return unavailable('native output through a symlink needs write-event capture')
        if original.get(output['path']) != output:
            expected.append(output)
    result = compare_ordered(expected, candidate['products'])
    result['removed_inputs'] = candidate['removed_inputs']
    if candidate['removed_inputs']:
        result['state'] = 'mismatch'
    return result


def compare_invocation(native, candidate, inputs, native_blobs, candidate_blobs):
    state = candidate['state']
    if state != 'observed' or candidate['process_exit_status'] < 0:
        reason = candidate.get('reason', state if state != 'observed' else 'candidate signal')
        return dict(diagnostic_headers=unavailable(reason), filesystem_changes=unavailable(reason),
                    completion=unavailable(reason))
    structured = candidate['structured_outputs']
    headers = unavailable('candidate did not produce structured CLI diagnostics')
    completion = unavailable('candidate did not produce completion metadata')
    if 'diagnostics.json' in structured:
        actual = json.loads((candidate_blobs / structured['diagnostics.json']['sha256']).read_bytes())
        # Candidate schema errors are broken observations, not missing compiler
        # diagnostics. Unrepresentable native text remains an explicit gap.
        actual = candidate_headers(actual)
        try:
            expected = native_headers(native['diagnostics'], native_blobs)
        except (ValueError, UnicodeError) as error:
            headers = unavailable(str(error))
        else:
            headers = compare_ordered(expected, actual)
    if 'completion.json' in structured:
        stats = json.loads((candidate_blobs / structured['completion.json']['sha256']).read_bytes())
        value = stats.get('stats', {}).get('semantic_completion')
        if value not in ('complete', 'deferred', 'cycle', 'limit'):
            raise ValueError('invalid candidate completion metadata')
        completion = {'state': value}
    return dict(diagnostic_headers=headers, filesystem_changes=filesystem_changes(native, candidate, inputs),
                completion=completion)


def diff_replay(oracle, candidate, output):
    oracle_summary = json.loads((oracle / 'summary.json').read_text())
    candidate_summary = json.loads((candidate / 'summary.json').read_text())
    if (oracle_summary.get('oracle') != lock() or oracle_summary.get('exit_status') != 0
            or oracle_summary.get('observation_error')):
        raise ValueError('comparison requires a successful pinned production oracle observation')
    inputs = oracle / 'inputs'
    input_capture = summarize_inputs(inputs)
    if oracle_summary.get('input_capture') != input_capture:
        raise ValueError('native input capture changed')
    result_capture = summarize_results(oracle / 'compilations', inputs)
    if oracle_summary.get('result_capture') != result_capture or result_capture['missing_invocations']:
        raise ValueError('native result capture changed or is incomplete')
    if (candidate_summary.get('oracle') != oracle_summary['oracle']
            or candidate_summary.get('input_capture') != input_capture):
        raise ValueError('candidate was run against different native inputs')
    capture = summarize_replay(candidate, inputs)
    if (candidate_summary.get('candidate_capture') != capture
            or candidate_summary.get('invocations') != capture['invocations']
            or candidate_summary.get('counts') != capture['counts']):
        raise ValueError('candidate capture changed or lacks its manifest; rerun replay')
    binary_hash = candidate_summary.get('candidate_sha256')
    if not isinstance(binary_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', binary_hash):
        raise ValueError('missing candidate binary identity')
    if output.exists():
        raise ValueError('use a new comparison output directory')
    output.mkdir(parents=True)
    counts = {key: Counter() for key in ('diagnostic_headers', 'filesystem_changes', 'completion')}
    rows, shards = [], []
    for path in sorted((inputs / 'invocations').glob('*.json')):
        source = json.loads(path.read_text())
        native = json.loads((oracle / 'compilations/invocations' / path.name).read_text())
        actual = json.loads((candidate / path.stem / 'result.json').read_text())
        row = dict(input_invocation=path.stem, package=source['package'], test=source['test'],
                   sequence=source['sequence'], candidate_state=actual['state'],
                   process_exit_status=actual.get('process_exit_status'))
        row.update(compare_invocation(native, actual, source, oracle / 'compilations/blobs', candidate / 'blobs'))
        for field, counter in counts.items():
            counter[row[field]['state']] += 1
        rows.append(row)
        if len(rows) == 1000:
            shards.append(write_shard(output, len(shards), rows))
            rows = []
    if rows:
        shards.append(write_shard(output, len(shards), rows))
    summary = dict(schema=1, oracle=oracle_summary['oracle'], candidate_sha256=binary_hash,
                   input_capture=input_capture, result_capture=result_capture, candidate_capture=capture,
                   invocations=capture['invocations'], counts={k: dict(v) for k, v in counts.items()},
                   shards=shards, tsz_parity='unmeasured',
                   scope='ordered diagnostic headers and filesystem changes of captured compiler invocations',
                   remaining=['native all-phase diagnostic API, chains, related information and flags',
                              'emit write events, skipped state and resolution traces',
                              'baseline formatting, auxiliary compilation and other native drivers'])
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


def write_shard(output, index, rows):
    data = ''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows).encode()
    path = output / f'differences-{index:04}.jsonl'
    path.write_bytes(data)
    return dict(path=path.name, rows=len(rows), sha256=hashlib.sha256(data).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('oracle', 'candidate', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(diff_replay(args.oracle, args.candidate, args.output), indent=2))
        sys.exit(1)  # Matching projections never establish full native-suite parity.
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f'TypeScript 7 replay comparison: {error}', file=sys.stderr)
        sys.exit(2)
