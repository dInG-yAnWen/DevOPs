"""Check committed artifact bytes and run the contract suite from Git archives.

Usage: python validator/verify_git_export.py [--ref HEAD]
Requires Git and the same Python version as validate.py. Does not modify the
repository or execute builds. Temporary exports are removed automatically.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def verify(ref):
    for autocrlf in ('true', 'false', 'input'):
        data = subprocess.check_output(
            ['git', '-c', f'core.autocrlf={autocrlf}', 'archive',
             '--format=zip', ref], cwd=ROOT)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            manifest = json.loads(archive.read('contracts/artifact-manifest.json'))['artifacts']
            mismatches = [item['path'] for item in manifest.values()
                          if hashlib.sha256(archive.read(item['path'])).hexdigest()
                          != item['artifact']['sha256']]
            if mismatches:
                raise ValueError(f'core.autocrlf={autocrlf}: '
                                 f'{len(mismatches)} artifact hash mismatches: '
                                 + ', '.join(mismatches))
            with tempfile.TemporaryDirectory(prefix='b14-git-export-') as folder:
                destination = Path(folder).resolve()
                for entry in archive.infolist():
                    target = (destination / entry.filename).resolve()
                    if not target.is_relative_to(destination):
                        raise ValueError('Archive entry escapes export directory')
                archive.extractall(destination)
                result = subprocess.run(
                    [sys.executable, '-B', 'validator/validate.py', '--suite'],
                    cwd=destination, capture_output=True, text=True,
                    encoding='utf-8', errors='replace')
                if result.returncode:
                    raise ValueError(f'core.autocrlf={autocrlf}: exported suite failed\n'
                                     + result.stdout + result.stderr)
                summary = result.stdout.strip().splitlines()[-1]
                print(f'PASS core.autocrlf={autocrlf}: '
                      f'{len(manifest)}/{len(manifest)} artifact hashes; {summary}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', default='HEAD', help='Local commit or tree to export')
    args = parser.parse_args()
    try:
        verify(args.ref)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError,
            zipfile.BadZipFile) as error:
        print('FAIL: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
