#!/usr/bin/env python3
"""Regenerate requirements.lock.txt with SHA-256 hashes for every platform.

Resolves the real dependency tree in a throwaway virtual environment, then asks
PyPI for the digest of every distribution of each resolved version — wheels for
every OS plus the sdist — so the lock installs on Windows, macOS and Linux alike.

    python src/lock_requirements.py

Run this only when you intend to move a pin, and read the release notes first.
"""
import json, os, re, subprocess, sys, tempfile, urllib.request, venv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOP = os.path.join(ROOT, 'requirements.txt')
LOCK = os.path.join(ROOT, 'requirements.lock.txt')

HEADER = """# Cryptographically pinned dependency lock — generated, do not hand-edit.
#
# Every artifact pip may install is listed by SHA-256, for every platform. Used
# with --require-hashes, pip refuses anything whose bytes do not match, so a
# hijacked PyPI account or a poisoned mirror cannot substitute code on your
# machine. Transitive dependencies are pinned too, not just the direct one.
#
# Regenerate with:  python src/lock_requirements.py
"""


def resolve(spec_lines):
    """Install the top-level requirements in a clean venv and report what landed."""
    with tempfile.TemporaryDirectory() as tmp:
        env = os.path.join(tmp, 'v')
        venv.create(env, with_pip=True)
        py = os.path.join(env, 'Scripts' if os.name == 'nt' else 'bin',
                          'python.exe' if os.name == 'nt' else 'python')
        req = os.path.join(tmp, 'top.txt')
        with open(req, 'w', encoding='utf-8') as f:
            f.write('\n'.join(spec_lines) + '\n')
        subprocess.run([py, '-m', 'pip', 'install', '-q', '--upgrade', 'pip'],
                       check=True)
        subprocess.run([py, '-m', 'pip', 'install', '-q', '-r', req], check=True)
        out = subprocess.run([py, '-m', 'pip', 'freeze', '--all'],
                             check=True, capture_output=True, text=True).stdout
    pinned = {}
    for line in out.splitlines():
        if '==' not in line:
            continue
        name, ver = line.split('==', 1)
        if name.lower() in {'pip', 'setuptools', 'wheel'}:
            continue
        pinned[name.strip()] = ver.strip()
    return dict(sorted(pinned.items(), key=lambda kv: kv[0].lower()))


def hashes_for(name, version):
    url = f'https://pypi.org/pypi/{name}/{version}/json'
    with urllib.request.urlopen(url, timeout=60) as r:
        data = json.load(r)
    return sorted({f['digests']['sha256'] for f in data['urls']
                   if f['packagetype'] in ('bdist_wheel', 'sdist')})


def main():
    top = [l.strip() for l in open(TOP, encoding='utf-8')
           if l.strip() and not l.lstrip().startswith('#')]
    print(f'resolving {len(top)} top-level requirement(s)...')
    resolved = resolve(top)

    blocks = []
    for name, ver in resolved.items():
        digests = hashes_for(name, ver)
        if not digests:
            print(f'  !! no artifacts published for {name}=={ver}', file=sys.stderr)
            return 1
        lines = [f'{name}=={ver} \\']
        for i, h in enumerate(digests):
            lines.append(f'    --hash=sha256:{h}' + (' \\' if i < len(digests) - 1 else ''))
        blocks.append('\n'.join(lines))
        print(f'  {name}=={ver}  ({len(digests)} artifacts)')

    with open(LOCK, 'w', encoding='utf-8') as f:
        f.write(HEADER + '\n' + '\n\n'.join(blocks) + '\n')
    print(f'\nwrote {os.path.relpath(LOCK, ROOT)} '
          f'({len(resolved)} packages)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
