"""Validate native completed-result capture independently of CLI replay."""

import hashlib
import json
from pathlib import Path
import re


def summarize_results(directory: Path, inputs: Path) -> dict:
    blobs, manifest = {}, []
    for path in sorted((directory / 'blobs').glob('*')):
        if not path.is_file() or not re.fullmatch(r'[0-9a-f]{64}', path.name):
            raise ValueError('invalid native result blob path')
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != path.name:
            raise ValueError('native result blob/hash mismatch')
        blobs[path.name] = len(content)
        manifest.append([f'blobs/{path.name}', path.name, len(content)])

    def check_file(record):
        if not isinstance(record, dict) or set(record) != {'path', 'mode', 'byte_length', 'sha256'}:
            raise ValueError('invalid native result file')
        if not isinstance(record['path'], str) or not record['path']:
            raise ValueError('invalid native result filename')
        if type(record['mode']) is not int or record['mode'] != 0:
            raise ValueError('native result files do not carry filesystem modes')
        if (type(record['byte_length']) is not int or not isinstance(record['sha256'], str)
                or blobs.get(record['sha256']) != record['byte_length']):
            raise ValueError('missing or invalid native result blob reference')

    def check_diagnostics(records):
        if not isinstance(records, list):
            raise ValueError('missing ordered native diagnostics')
        for record in records:
            if not isinstance(record, dict):
                raise ValueError('invalid native diagnostic')
            for field in ('code', 'byte_start', 'byte_length'):
                if type(record.get(field)) is not int:
                    raise ValueError('invalid native diagnostic number')
            if record.get('category') not in ('error', 'warning', 'suggestion', 'message'):
                raise ValueError('invalid native diagnostic category')
            if not isinstance(record.get('text'), str):
                raise ValueError('missing native diagnostic text')
            for field in ('reports_unnecessary', 'reports_deprecated', 'skipped_on_no_emit'):
                if type(record.get(field)) is not bool:
                    raise ValueError('invalid native diagnostic flag')
            if 'source' not in record:
                raise ValueError('missing native diagnostic source')
            if record['source'] is not None:
                check_file(record['source'])
            check_diagnostics(record.get('message_chain'))
            check_diagnostics(record.get('related_information'))

    expected = {path.stem for path in (inputs / 'invocations').glob('*.json')}
    observed, diagnostics, products = set(), 0, 0
    for path in sorted((directory / 'invocations').glob('*.json')):
        content = path.read_bytes()
        record = json.loads(content)
        if not isinstance(record, dict) or type(record.get('schema')) is not int or record['schema'] != 1:
            raise ValueError('invalid native result schema')
        identity = record.get('input_invocation')
        if identity not in expected or path.stem != identity or identity in observed:
            raise ValueError('native result/input identity mismatch')
        observed.add(identity)
        check_diagnostics(record.get('diagnostics'))
        diagnostics += len(record['diagnostics'])
        outputs = record.get('outputs')
        if not isinstance(outputs, list):
            raise ValueError('missing native output inventory')
        for output in outputs:
            check_file(output)
        names = [output['path'] for output in outputs]
        if names != sorted(set(names)):
            raise ValueError('duplicate or unordered native output paths')
        products += len(outputs)
        if 'emit' not in record:
            raise ValueError('missing native emit result')
        if record['emit'] is not None:
            emit = record['emit']
            if not isinstance(emit, dict) or type(emit.get('skipped')) is not bool:
                raise ValueError('invalid native emit result')
            check_diagnostics(emit.get('diagnostics'))
            files = emit.get('reported_files')
            if files is not None and (not isinstance(files, list) or any(not isinstance(p, str) for p in files)):
                raise ValueError('invalid native reported files')
        if not isinstance(record.get('trace'), str):
            raise ValueError('missing native resolution trace')
        manifest.append([f'invocations/{path.name}', hashlib.sha256(content).hexdigest(), len(content)])
    return {
        'scope': 'native CompileFilesEx completed results; not CLI outcomes or TSZ parity',
        'invocations': len(observed), 'missing_invocations': sorted(expected - observed),
        'diagnostics': diagnostics, 'output_files': products, 'blobs': len(blobs),
        'sha256': hashlib.sha256(json.dumps(manifest, separators=(',', ':')).encode()).hexdigest(),
    }
