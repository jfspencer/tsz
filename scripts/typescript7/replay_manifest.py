"""Verify candidate observations against their original native input ledger."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from replay_namespace import SYMLINK, virtual_path


def summarize_replay(directory: Path, inputs: Path) -> dict:
    manifest, blobs = [], {}
    for path in sorted((directory / 'blobs').iterdir()):
        if not path.is_file() or not re.fullmatch(r'[0-9a-f]{64}', path.name):
            raise ValueError('invalid candidate blob path')
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != path.name:
            raise ValueError('candidate blob/hash mismatch')
        blobs[path.name] = len(content)
        manifest.append([f'blobs/{path.name}', path.name, len(content)])

    def check_blob(record):
        if (not isinstance(record, dict) or not isinstance(record.get('sha256'), str)
                or type(record.get('byte_length')) is not int
                or blobs.get(record['sha256']) != record['byte_length']):
            raise ValueError('invalid candidate blob reference')

    def check_sidecar(row, name, record):
        check_blob(record)
        content = (row / name).read_bytes()
        if len(content) != record['byte_length'] or hashlib.sha256(content).hexdigest() != record['sha256']:
            raise ValueError('candidate sidecar/blob mismatch')

    expected = {p.stem: p for p in (inputs / 'invocations').glob('*.json')}
    observed, counts = set(), Counter()
    for path in sorted(directory.glob('*/result.json')):
        identity = path.parent.name
        if identity not in expected or identity in observed:
            raise ValueError('candidate/input invocation identity mismatch')
        observed.add(identity)
        source = expected[identity].read_bytes()
        native = json.loads(source)
        content = path.read_bytes()
        record = json.loads(content)
        if (record.get('input_record_sha256') != hashlib.sha256(source).hexdigest()
                or any(record.get(k) != native[k] for k in ('package', 'test', 'sequence'))):
            raise ValueError('candidate input record changed')
        state = record.get('state')
        if state in ('unsupported-adapter', 'adapter-error'):
            if not isinstance(record.get('reason'), str) or not record['reason']:
                raise ValueError('missing candidate adapter reason')
        elif state in ('observed', 'timeout'):
            if type(record.get('process_exit_status')) is not int:
                raise ValueError('missing candidate process outcome')
            args = record.get('arguments')
            if not isinstance(args, list) or any(not isinstance(a, str) for a in args):
                raise ValueError('missing candidate arguments')
            products = record.get('products')
            if not isinstance(products, list):
                raise ValueError('missing candidate filesystem changes')
            names = []
            for product in products:
                check_blob(product)
                name = product.get('path')
                if (not isinstance(name, str) or str(virtual_path(name)) != name
                        or type(product.get('mode')) is not int or product['mode'] not in (0, SYMLINK)):
                    raise ValueError('invalid candidate output path or mode')
                names.append(name)
            if names != sorted(set(names)):
                raise ValueError('duplicate or unordered candidate output paths')
            removed = record.get('removed_inputs')
            if (not isinstance(removed, list) or any(not isinstance(p, str) for p in removed)
                    or removed != sorted(set(removed))
                    or not set(removed) <= {p['path'] for p in native['files']}
                    or set(removed) & set(names)):
                raise ValueError('invalid candidate removed inputs')
            for name in ('stdout', 'stderr'):
                check_sidecar(path.parent, name + '.bin', record.get(name))
            structured = record.get('structured_outputs')
            if not isinstance(structured, dict) or not set(structured) <= {'diagnostics.json', 'completion.json'}:
                raise ValueError('invalid candidate structured outputs')
            for name, reference in structured.items():
                check_sidecar(path.parent, name, reference)
        else:
            raise ValueError('invalid candidate observation state')
        counts[state] += 1
        manifest.append([f'{identity}/result.json', hashlib.sha256(content).hexdigest(), len(content)])
    if not expected or observed != expected.keys():
        raise ValueError('missing candidate invocations')
    return {
        'scope': 'candidate process observations, not native API results',
        'invocations': len(observed), 'counts': dict(counts), 'blobs': len(blobs),
        'sha256': hashlib.sha256(json.dumps(manifest, separators=(',', ':')).encode()).hexdigest(),
    }
