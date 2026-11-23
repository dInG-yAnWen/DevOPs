"""Stage only this CI run's safe evidence, retaining manifest-bound .gitignore."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

from scan_runtime_logs import PATTERNS, PLACEHOLDER

EVIDENCE_DIRS = frozenset({
    'base-project', 'baseline-full', 'draft-build', 'final-full', 'incremental',
    'logs', 'repair-work', 'target-full', 'target-project',
})
EVIDENCE_FILES = frozenset({
    'request.json', 'result.json', 'baseline-response.json', 'draft-response.json',
    'draft.json', 'full-check.json', 'incremental-response.json',
    'incremental-check.json', 'repair-response.json', 'repair.json',
    'recheck-response.json', 'recheck.json', 'target-response.json',
})
SENSITIVE_NAME = re.compile(
    r'(?i)^(?:credentials?(?:\..*)?|secrets?(?:\..*)?|tokens?(?:\..*)?|id_rsa(?:\..*)?|'
    r'id_ed25519(?:\..*)?|.*\.(?:pem|key|p12|pfx))$'
)
JSON_SECRET = re.compile(r'(?i)"[^"\n]*(?:api[_-]?key|secret|token|passw(?:or)?d)"\s*:\s*"([^"\n]{12,})"')


def safe_relative(uri):
    if not isinstance(uri, str) or not uri or '\\' in uri or ':' in uri or any(ord(c) < 32 for c in uri):
        return False
    path = PurePosixPath(uri)
    return not path.is_absolute() and all(p not in ('', '.', '..') for p in path.parts) and path.as_posix() == uri


def allowed(uri, declared):
    if not safe_relative(uri):
        return False
    parts = PurePosixPath(uri).parts
    if len(parts) == 1:
        return uri in EVIDENCE_FILES
    if parts[0] not in EVIDENCE_DIRS:
        return False
    for index, part in enumerate(parts):
        if SENSITIVE_NAME.fullmatch(part):
            return False
        if part.startswith('.'):
            if not (index == len(parts) - 1 and part == '.gitignore' and uri in declared):
                return False
    return True


def has_secret(content):
    text = content.decode('utf-8', errors='replace')
    if any(not PLACEHOLDER.search(match.group(1)) for match in JSON_SECRET.finditer(text)):
        return True
    for name, pattern in PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(match.lastindex or 0)
            if name == 'secret assignment' and (
                PLACEHOLDER.search(value) or value.startswith('&') or '(' in value or '[' in value
            ):
                continue
            return True
    return False


def read_safe(path, root):
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError('symlink')
        current = current.parent
    if root.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('outside evidence root')
    return path.read_bytes()


def prepare(work, output):
    work = Path(work).resolve()
    output = Path(output).resolve()
    source = work / 'ci-e14'
    if output == source or output.is_relative_to(source) or output == work:
        raise ValueError('Upload staging must be separate from the evidence source')
    output.mkdir(parents=True, exist_ok=False)
    errors, excluded, copied = [], [], []
    manifest = []
    if (source / 'result.json').exists():
        try:
            result = json.loads(read_safe(source / 'result.json', work))
            manifest = result['artifacts']
            if not isinstance(manifest, list):
                raise ValueError('artifacts must be a list')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append({'path': 'ci-e14/result.json', 'reason': type(exc).__name__})
            manifest = []
    declared = {item.get('uri') for item in manifest if isinstance(item, dict) and isinstance(item.get('uri'), str)}
    for item in manifest:
        uri = item.get('uri') if isinstance(item, dict) else None
        if not allowed(uri, declared):
            errors.append({'path': str(uri), 'reason': 'disallowed manifest path'})
            continue
        try:
            content = read_safe(source / uri, work)
            if hashlib.sha256(content).hexdigest() != item.get('sha256') or len(content) != item.get('bytes'):
                errors.append({'path': uri, 'reason': 'manifest hash or size mismatch'})
        except (OSError, ValueError):
            errors.append({'path': uri, 'reason': 'missing or unsafe manifest file'})
    candidates = []
    if source.is_dir() and not source.is_symlink():
        candidates.extend((p, 'ci-e14/' + p.relative_to(source).as_posix())
                          for p in sorted(source.rglob('*')) if p.is_file())
    service_log = work / 'ci-e14-services.log'
    if service_log.is_file():
        candidates.append((service_log, 'ci-e14-services.log'))
    for path, target in candidates:
        uri = path.relative_to(source).as_posix() if target.startswith('ci-e14/') else None
        if uri is not None and not allowed(uri, declared):
            excluded.append(target)
            continue
        try:
            content = read_safe(path, work)
            if has_secret(content):
                errors.append({'path': target, 'reason': 'secret pattern; content excluded'})
                continue
        except (OSError, ValueError):
            excluded.append(target)
            continue
        destination = output / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        copied.append(target)
    result_present = (source / 'result.json').is_file()
    complete = result_present and not errors
    audit = {'copied': copied, 'excluded': excluded, 'errors': errors,
             'manifest_files': len(manifest), 'complete': complete,
             'state': 'complete' if complete else 'partial',
             'result_present': result_present,
             'scope': 'ci-e14 allowlist plus ci-e14-services.log only'}
    (output / 'upload-audit.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
    return audit


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--github-output', type=Path)
    args = parser.parse_args(argv)
    audit = prepare(args.work, args.output)
    # Publish the staging path only after it was created and fully filtered.
    # Controlled manifest errors still retain safe partial failure evidence.
    if args.github_output:
        with args.github_output.open('a', encoding='utf-8') as stream:
            stream.write('path=' + str(args.output.resolve()) + '\n')
    print(json.dumps({'copied': len(audit['copied']), 'excluded': len(audit['excluded']),
                      'errors': len(audit['errors']), 'manifest_files': audit['manifest_files']}))
    return 0 if audit['complete'] else 1


if __name__ == '__main__':
    sys.exit(main())
