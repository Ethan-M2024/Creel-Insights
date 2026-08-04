#!/usr/bin/env python3
"""WDFW creel reports — fetch every source, rebuild the dashboard, check the result.

    python src/pipeline.py             # normal update
    python src/pipeline.py --full      # ignore every cache, re-read everything
    python src/pipeline.py --check     # validate what is already built, no network
    python src/pipeline.py --no-open   # do not launch a browser at the end

Seven sources, published in four different formats, are read into two tables:
creel_rows.csv.gz (a species line) and creel_effort.csv.gz (the fishing behind it).
Everything downstream — the dashboard, the map, the audit — is built from those two
files, so a source can be added or fixed without anything else changing.
"""
import argparse
import csv
import hashlib
import json
import os
import sys
import time
import webbrowser
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sources'))
import paths
from paths import open_text
import common
import socrata
import puget
import buoy10
import willapa
import ocean
import pikeminnow
import southwest
import halibut
import quotas

LOG = []


def say(msg, tag='  '):
    line = f'{tag} {msg}'
    LOG.append(line)
    print(line, flush=True)


#: every source, in the order they are read: the key used in the data, the label the
#: dashboard shows, and the exact page or dataset it was read from. The address is
#: carried into the manifest and printed on the page, so a reader can open the same
#: document and check any number against it.
SOURCES = (
    ('creel-database', 'WDFW creel database (statewide)',
     'https://data.wa.gov/resource/rpax-ahqm.json (interviews), '
     'https://data.wa.gov/resource/6y4e-8ftk.json (catch)'),
    ('puget-ramp', 'Puget Sound ramp creel',
     'https://wdfw.wa.gov/fishing/reports/creel/puget-annual'),
    ('buoy10', 'Buoy 10',
     'https://wdfw.wa.gov/fishing/reports/creel/buoy10'),
    ('willapa', 'Willapa Bay',
     'https://wdfw.wa.gov/fishing/reports/creel/willapa-bay'),
    ('ocean-quota', 'Ocean sport salmon quota report',
     'https://wdfw.wa.gov/fishing/reports/creel/ocean and its archives page'),
    ('columbia-sw', 'Columbia River and tributary report',
     'https://wdfw.wa.gov/fishing/reports/creel/southwest (weekly PDFs)'),
    ('pikeminnow', 'Northern pikeminnow sport reward',
     'https://wdfw.wa.gov/fishing/reports/creel/pikeminnow (weekly PDFs)'),
    ('halibut', 'Pacific halibut landings summary',
     'https://wdfw.wa.gov/fishing/regulations/halibut/seasons-quotas'),
)


def gather(full=False):
    """Run every parser and return the two tables, plus what each source produced."""
    this_year = date.today().year
    catch_rows, effort_rows, summary = [], [], {}

    def add(name, pair):
        c, e = pair
        catch_rows.extend(c)
        effort_rows.extend(e)
        days = {r['date'] for r in e} | {r['date'] for r in c}
        summary[name] = {
            'catch_rows': len(c), 'effort_rows': len(e),
            'first': min(days) if days else None, 'last': max(days) if days else None,
            'locations': len({r['location'] for r in e} | {r['location'] for r in c}),
        }

    say('reading the WDFW creel database')
    add('creel-database', socrata.load(refresh=full, say=say))
    say('reading the Puget Sound ramp creel')
    add('puget-ramp', puget.load(this_year, full=full, say=say))
    say('reading Buoy 10')
    add('buoy10', buoy10.load(full=full, say=say))
    say('reading Willapa Bay')
    add('willapa', willapa.load(full=full, say=say))
    say('reading the ocean quota report')
    add('ocean-quota', ocean.load(this_year, full=full, say=say))
    say('reading the Columbia River and tributary reports')
    add('columbia-sw', southwest.load(full=full, say=say))
    say('reading the pikeminnow sport-reward reports')
    add('pikeminnow', pikeminnow.load(full=full, say=say))
    say('reading the halibut landings summary')
    add('halibut', halibut.load(full=full, say=say))
    say('reading the quota trackers')
    quota_rows = quotas.load(full=full, say=say)
    return catch_rows, effort_rows, summary, quota_rows


def write_table(path, rows, fields):
    """Write one table, sorted, so an unchanged run produces byte-identical output."""
    rows = sorted(rows, key=lambda r: tuple(str(r.get(f, '')) for f in fields))
    with open_text(path, 'w') as f:
        w = csv.DictWriter(f, fieldnames=list(fields), lineterminator='\n')
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def read_table(path, fields):
    if not os.path.exists(path):
        return []
    with open_text(path) as f:
        return list(csv.DictReader(f))


def update(full=False, no_open=False):
    paths.ensure_dirs()
    started = time.time()
    catch_rows, effort_rows, summary, quota_rows = gather(full=full)
    if not catch_rows:
        say('no data was read from any source; refusing to overwrite what is here', '!!')
        return 1

    n_catch = write_table(paths.RAW, catch_rows, common.CATCH_FIELDS)
    n_effort = write_table(paths.EFFORT, effort_rows, common.EFFORT_FIELDS)
    say(f'wrote {n_catch:,} species rows and {n_effort:,} effort rows')

    with open(paths.QUOTAS, 'w', encoding='utf-8') as f:
        json.dump(quota_rows, f, indent=1)
    say(f'   {len(quota_rows)} quota and guideline records')

    manifest = {
        'built': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'sources': {name: dict(summary.get(name, {}), label=label, read_from=where)
                    for name, label, where in SOURCES},
        'quota_records': len(quota_rows),
        'sha256': {
            'creel_rows': _sha(paths.RAW), 'creel_effort': _sha(paths.EFFORT)},
    }
    with open(paths.MANIFEST, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=1, sort_keys=True)

    import build_data
    payload = build_data.main(say=say)
    import validate
    ok, report = validate.report(say=say)
    build_data.write_payload(payload, audit=report, say=say)
    import assemble
    assemble.main()

    say(f'done in {time.time() - started:.0f}s')
    with open(paths.RUN_LOG, 'w', encoding='utf-8') as f:
        f.write('\n'.join(LOG))
    if not no_open:
        webbrowser.open(_file_url(paths.DASHBOARD))
    return 0 if ok else 2


def _sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _file_url(path):
    import pathlib
    return pathlib.Path(path).resolve().as_uri()


def check():
    import validate
    return 0 if validate.main(say=say) else 2


def main():
    ap = argparse.ArgumentParser(prog='pipeline.py', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--full', action='store_true')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--no-open', action='store_true')
    a = ap.parse_args()
    if a.check:
        return check()
    return update(full=a.full, no_open=a.no_open)


if __name__ == '__main__':
    sys.exit(main())
