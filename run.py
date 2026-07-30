#!/usr/bin/env python3
"""One command to open, update or check the dashboard, on macOS and Windows alike.

    python3 run.py              open the dashboard        (macOS / Linux)
    py run.py                   open the dashboard        (Windows)

    python3 run.py --update     fetch the newest WDFW reports, rebuild, then open
    python3 run.py --check      re-run the accuracy audit against the shipped data
    python3 run.py --help       every option

Opening needs nothing but Python: the built page ships in this repository and carries
its own data, so it works with no install and no internet. Only --update needs the PDF
library, and this script sets it up by itself the first time you ask for it.

Deliberately standard-library only. It has to run *before* anything is installed, so
importing a third-party package here would be a chicken-and-egg problem.
"""
import argparse
import os
import pathlib
import subprocess
import sys
import webbrowser

ROOT = pathlib.Path(__file__).resolve().parent
VENV = ROOT / '.venv'
LOCK = ROOT / 'requirements.lock.txt'
DASHBOARD = ROOT / 'docs' / 'index.html'
#: records the lock file this .venv was built from, so pip is re-run when it changes
#: and skipped — several seconds every launch — when it has not
STAMP = VENV / '.installed-from'

MIN_PYTHON = (3, 9)


def die(msg, *hints):
    print(f'\n  {msg}\n')
    for h in hints:
        print(f'  {h}')
    print()
    sys.exit(1)


def venv_python():
    """Path to the interpreter inside .venv, on either platform's layout."""
    exe = VENV / ('Scripts' if os.name == 'nt' else 'bin') / \
        ('python.exe' if os.name == 'nt' else 'python')
    return exe if exe.exists() else None


def ensure_venv():
    """Create .venv and install the hash-locked dependencies into it.

    Returns the interpreter to run the pipeline with. A private environment is used
    rather than the system Python so that nothing this project needs can collide with
    anything else on the machine, and so removing the folder removes it completely.
    """
    if sys.version_info < MIN_PYTHON:
        die(f'Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer is required; '
            f'this is {sys.version.split()[0]}.',
            'Install a current version from https://www.python.org/downloads/',
            'and run this command again.')

    py = venv_python()
    if py is None:
        print('  First run: building a private Python environment (about a minute)...')
        try:
            subprocess.run([sys.executable, '-m', 'venv', str(VENV)], check=True)
        except subprocess.CalledProcessError:
            die('Could not create the .venv folder.',
                'If this repository is inside a synced folder (OneDrive, Dropbox,',
                'iCloud), try moving it somewhere local and running again.')
        py = venv_python()
        if py is None:
            die('The .venv folder was created but has no interpreter in it.',
                'Delete the .venv folder and try again.')

    want = LOCK.read_bytes()
    if STAMP.exists() and STAMP.read_bytes() == want:
        return py                       # already installed from this exact lock file

    print('  Installing verified dependencies...')
    subprocess.run([str(py), '-m', 'pip', 'install', '--quiet', '--upgrade', 'pip'],
                   check=False)
    # --require-hashes makes pip verify the SHA-256 of every package and refuse
    # anything that does not match, so a tampered release cannot be installed. There
    # is deliberately no fallback: if this fails the right outcome is to stop.
    r = subprocess.run([str(py), '-m', 'pip', 'install', '--quiet',
                        '--require-hashes', '-r', str(LOCK)])
    if r.returncode != 0:
        die('Could not install the verified dependencies.',
            'Check your internet connection and try again.',
            'Do NOT work around the hash check — it is what protects you from a',
            'tampered package.')
    STAMP.write_bytes(want)
    return py


def open_dashboard():
    if not DASHBOARD.exists():
        die('docs/index.html is missing from this copy of the repository.',
            'Run:  python3 run.py --update    to build it.')
    # as_uri() percent-encodes spaces and '#'; a hand-built file:/// string does not,
    # and a download sitting in "C:\\Users\\Jo Smith\\Downloads" contains both
    url = DASHBOARD.as_uri()
    print(f'  Opening {DASHBOARD}')
    if not webbrowser.open(url):
        print(f'  Could not launch a browser. Open this file by hand:\n    {DASHBOARD}')


def main():
    ap = argparse.ArgumentParser(
        prog='run.py', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--update', action='store_true',
                    help='fetch the newest WDFW reports and rebuild the dashboard')
    ap.add_argument('--check', action='store_true',
                    help='re-run the accuracy audit against the data already here')
    ap.add_argument('--full', action='store_true',
                    help='with --update: ignore every cache and re-read every report')
    ap.add_argument('--no-open', action='store_true',
                    help='with --update: rebuild but do not launch a browser')
    a = ap.parse_args()

    if not a.update and not a.check:
        open_dashboard()
        print('  To pull in the newest WDFW reports:  '
              f'{"py" if os.name == "nt" else "python3"} run.py --update')
        return 0

    py = ensure_venv()
    argv = [str(py), str(ROOT / 'src' / 'pipeline.py')]
    if a.check:
        argv.append('--check')
    else:
        if a.full:
            argv.append('--full')
        if a.no_open:
            argv.append('--no-open')
    return subprocess.run(argv, cwd=str(ROOT)).returncode


if __name__ == '__main__':
    sys.exit(main())
