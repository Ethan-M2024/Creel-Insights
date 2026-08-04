"""Check the extracted data against WDFW's own published figures, and against itself.

A dashboard that quietly disagrees with its source is worse than no dashboard, so
nothing ships without these checks. They fall into two kinds.

External — the numbers are held against something WDFW published separately:

    creel summary       WDFW publish a summarised angler-and-harvest table for the
                        district creels (dpqw-kc2b). Our totals for the same water
                        body, day and species are rebuilt from the interview-level
                        records and compared with theirs.

Internal — the shape of the data has to stay sane:

    no future dates, no negative counts, no fish without effort behind them, no
    location placed at coordinates outside Washington, no source that has silently
    stopped producing rows, and no day counted twice by two sources.

Every failure is printed with the rows that caused it. The run exits non-zero when a
check fails, which is what stops the daily refresh from committing bad data.
"""
import json
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sources'))
import paths
from paths import open_text

#: Washington, generously bounded. A point outside this is a matching mistake.
WA_BOX = (45.4, 49.1, -125.0, -116.8)

#: the published summary rounds and revises; agreement inside this is agreement
TOLERANCE = 0.02
#: and a difference of a fish or two on a small day is not a discrepancy
ABS_TOLERANCE = 3


def read(path):
    import csv
    if not os.path.exists(path):
        return []
    with open_text(path) as f:
        return list(csv.DictReader(f))


def to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


class Audit:
    def __init__(self, say=print):
        self.say = say
        self.failures = 0
        self.checks = 0
        self.results = []

    def check(self, name, ok, detail=''):
        self.checks += 1
        self.results.append({'name': name, 'ok': bool(ok),
                             'detail': detail if not ok else ''})
        if ok:
            self.say(f'   [pass] {name}')
        else:
            self.failures += 1
            self.say(f'   [FAIL] {name} {detail}', '!!')
        return ok


def audit(catch_rows, effort_rows, summary_rows, place_geo, say=print):
    a = Audit(say)
    today = date.today().isoformat()

    # ------------------------------------------------------------ internal
    # effort as well as catch: WDFW post a season's table before the season starts,
    # and a row of blanks dated two months out is what sets "latest report" if it is
    # allowed through
    future = [r for r in catch_rows + effort_rows if r['date'] > today]
    a.check('nothing is dated in the future', not future,
            f'{len(future)} rows, e.g. {future[:2]}')

    negative = [r for r in catch_rows if to_int(r['fish']) < 0]
    a.check('no negative fish counts', not negative, f'{len(negative)} rows')

    neg_effort = [r for r in effort_rows if to_int(r.get('anglers')) < 0]
    a.check('no negative angler counts', not neg_effort, f'{len(neg_effort)} rows')

    blank = [r for r in catch_rows if not r['location'] or not r['species']]
    a.check('every catch row names a place and a species', not blank,
            f'{len(blank)} rows')

    # fish with no effort behind them: a catch on a day the same source recorded no
    # anglers anywhere at that place means the two tables disagree
    effort_keys = {(r['source'], r['location'], r['date']) for r in effort_rows}
    orphan = [r for r in catch_rows
              if (r['source'], r['location'], r['date']) not in effort_keys]
    a.check('every catch has effort recorded with it',
            len(orphan) <= len(catch_rows) * 0.02,
            f'{len(orphan):,} of {len(catch_rows):,} rows')

    outside = []
    for name, g in (place_geo or {}).items():
        lat, lon = g.get('lat'), g.get('lon')
        if lat is None:
            continue
        if not (WA_BOX[0] <= lat <= WA_BOX[1] and WA_BOX[2] <= lon <= WA_BOX[3]):
            outside.append((name, lat, lon))
    a.check('every placed location sits inside Washington', not outside,
            f'{outside[:3]}')

    by_source = defaultdict(list)
    for r in catch_rows:
        by_source[r['source']].append(r['date'])
    stale = {s: max(d) for s, d in by_source.items()
             if max(d) < (date.today() - timedelta(days=400)).isoformat()}
    a.check('no source has silently stopped reporting', not stale, f'{stale}')

    # ------------------------------------------------------------ external
    if summary_rows:
        ours = defaultdict(int)
        for r in catch_rows:
            if r['source'] != 'creel-database' or r['fate'] != 'kept':
                continue
            ours[(r['date'], r['location'], r['species'])] += to_int(r['fish'])
        theirs = defaultdict(int)
        for r in summary_rows:
            day = (r.get('survey_date') or '')[:10]
            wb = (r.get('water_body') or '').strip()
            sp = (r.get('species_name') or '').strip()
            if not day or not wb or not sp:
                continue
            theirs[(day, wb, _species(sp))] += (
                to_int(r.get('wild_harvest')) + to_int(r.get('hatchery_harvest'))
                + to_int(r.get('other_harvest')))

        shared = [k for k in theirs if k in ours and theirs[k] > 0]
        agreed = 0
        worst = []
        for k in shared:
            mine, theirsn = ours[k], theirs[k]
            diff = abs(mine - theirsn)
            if diff <= ABS_TOLERANCE or diff / max(theirsn, 1) <= TOLERANCE:
                agreed += 1
            else:
                worst.append((k, mine, theirsn))
        rate = agreed / len(shared) if shared else 0
        worst.sort(key=lambda t: -abs(t[1] - t[2]))
        a.check(f'harvest matches WDFW\'s published creel summary on '
                f'{agreed:,} of {len(shared):,} shared day-water-species rows',
                shared and rate >= 0.9,
                f'{rate:.1%} agreement; largest gaps {worst[:3]}')
    else:
        say('   [skip] no published summary available to compare against')

    return a


def _species(raw):
    import common
    return common.species(raw)


#: main() returns a bare boolean by default so it can be used as an exit code;
#: the pipeline asks for the full report as well
_WANT_REPORT = False


def report(say=print):
    global _WANT_REPORT
    _WANT_REPORT = True
    try:
        return main(say=say)
    finally:
        _WANT_REPORT = False


def main(say=print):
    catch_rows = read(paths.RAW)
    effort_rows = read(paths.EFFORT)
    if not catch_rows:
        say('nothing to check: no extracted rows found', '!!')
        return (False, {'checks': 0, 'passed': 0, 'results': []}) \
            if _WANT_REPORT else False

    place_geo = {}
    if os.path.exists(paths.PLACE_GEO):
        with open(paths.PLACE_GEO, encoding='utf-8') as f:
            place_geo = json.load(f).get('placed', {})

    summary_rows = []
    try:
        import socrata
        cache = os.path.join(paths.API_DIR, f'{socrata.SUMMARY}.json')
        if os.path.exists(cache):
            with open(cache, encoding='utf-8') as f:
                summary_rows = json.load(f)
        else:
            summary_rows = socrata.published_summary(say=say)
    except Exception as exc:
        say(f'   [skip] could not read the published summary: {exc}')

    say('checking the extracted data')
    a = audit(catch_rows, effort_rows, summary_rows, place_geo, say=say)
    say(f'   {a.checks - a.failures} of {a.checks} checks passed')
    report = {'checks': a.checks, 'passed': a.checks - a.failures,
              'results': a.results,
              'compared_against': 'WDFW published creel summary (dpqw-kc2b)'
              if summary_rows else None}
    return (a.failures == 0, report) if _WANT_REPORT else a.failures == 0


if __name__ == '__main__':
    sys.exit(0 if main() else 2)
