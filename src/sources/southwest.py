"""The Columbia River and tributary fishery report, written out in sentences.

WDFW's southwest region does not publish its creel summary as a table. It publishes
it as prose, one paragraph per river section, every week since 2019:

    Section 6 (Kalama) — 110 bank anglers kept eight steelhead and released four
    steelhead. 6 boats/10 rods kept one steelhead, and released three Chinook, one
    jack, and one steelhead.

Every number in that paragraph is a creel figure, and there is nowhere else to get
it, so this module reads it. The parsing is deliberately narrow: a sentence has to
match the shape WDFW actually writes before anything is taken from it, and a
paragraph that does not match contributes nothing rather than a guess. What was
read and what was skipped is counted and reported, so the coverage is visible
instead of assumed.
"""
import os
import re
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
from common import FRESH

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths
import safety

URL = 'https://wdfw.wa.gov/fishing/reports/creel/southwest'
ORIGIN = 'https://wdfw.wa.gov'
SOURCE = 'columbia-sw'
REGION = 'Columbia River'

WORDS = {'no': 0, 'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
         'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11,
         'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15,
         'sixteen': 16, 'seventeen': 17, 'eighteen': 18, 'nineteen': 19,
         'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50, 'sixty': 60,
         'seventy': 70, 'eighty': 80, 'ninety': 90}

#: the species words these reports use, and what each one means. "jack" is a
#: precocious male salmon — in a salmon paragraph it is a Chinook unless the
#: sentence says otherwise, which is how the report itself uses the word.
SPECIES_WORDS = (
    (r'chinook jacks?', 'Chinook'), (r'coho jacks?', 'Coho'),
    (r'chinook', 'Chinook'), (r'coho', 'Coho'), (r'chum', 'Chum'),
    (r'pink', 'Pink'), (r'sockeye', 'Sockeye'), (r'steelhead', 'Steelhead'),
    (r'cutthroat', 'Cutthroat'), (r'jacks?', 'Chinook'),
    (r'(?:sub-?legal|legal|oversize|over-size)?\s*sturgeon', 'Sturgeon'),
    (r'sub-?legals?', 'Sturgeon'), (r'legals?', 'Sturgeon'),
    (r'oversize[sd]?', 'Sturgeon'), (r'walleye', 'Walleye'),
    (r'shad', 'Shad'), (r'bass', 'Smallmouth bass'), (r'trout', 'Rainbow trout'),
)
SPECIES_RE = re.compile('|'.join(f'(?P<s{i}>{p})' for i, (p, _) in
                                 enumerate(SPECIES_WORDS)), re.I)
SPECIES_BY_GROUP = {f's{i}': name for i, (_, name) in enumerate(SPECIES_WORDS)}

COUNT = r'(?:\d[\d,]*|' + '|'.join(WORDS) + r')'
ITEM = re.compile(rf'\b({COUNT})\s+((?:[A-Za-z-]+\s+){{0,2}}?[A-Za-z-]+)', re.I)

#: "110 bank anglers", "Six bank anglers", "No bank effort reported"
BANK = re.compile(rf'\b({COUNT})\s+(?:bank|shore)\s+(?:anglers?|rods?)', re.I)
BANK_NONE = re.compile(r'no (?:bank|shore) (?:effort|anglers)', re.I)
#: "6 boats/10 rods"
BOAT = re.compile(rf'\b({COUNT})\s+boats?\s*/\s*({COUNT})\s+(?:rods?|anglers?)', re.I)
BOAT_NONE = re.compile(r'no boat (?:effort|anglers)', re.I)
NO_EFFORT = re.compile(r'^\s*no (?:effort|angler)', re.I)

#: WDFW have written the same water four ways across seven seasons — "Sec 6
#: (Kalama)", "Section 6 (Kalama)", even "Section 6 Section 6 (Kalama)" — and each
#: spelling was becoming a separate place with its own history. A mainstem section is
#: identified by its number and nothing else; a tributary by its river, with the reach
#: kept when the report names one, because above and below a bridge are genuinely
#: different fishing.
SECTION = re.compile(r'^Sec(?:tion)?\.?\s*(\d+)\b(?:\s*Sec(?:tion)?\.?\s*\d+\b)?'
                     r'\s*\(?([^)]*)\)?', re.I)

#: section number -> the name WDFW settled on, so a label does not change with
#: whichever wording a given week's report happened to use
SECTION_NAMES = {
    '1': 'Bonneville', '2': 'Camas/Washougal', '3': 'I-5 Area', '4': 'Vancouver',
    '5': 'Woodland', '6': 'Kalama', '7': 'Cowlitz', '8': 'Longview',
    '9': 'Cathlamet', '10': 'Cathlamet/Chinook/Deep River',
}

#: tributary spellings that mean one water
TRIBUTARY = (
    (r'cowlitz.*(?:above|upstream)', 'Cowlitz River (above I-5)'),
    (r'cowlitz.*(?:below|downstream)', 'Cowlitz River (below I-5)'),
    (r'^above the i-?5', 'Cowlitz River (above I-5)'),
    (r'^cowlitz', 'Cowlitz River'),
    (r'klickitat.*above', 'Klickitat River (above Fisher Hill)'),
    (r'klickitat.*below', 'Klickitat River (below Fisher Hill)'),
    (r'^klickitat', 'Klickitat River'),
    (r'drano|little white salmon', 'Drano Lake'),
    (r'wind river above', 'Wind River (above Shipherd Falls)'),
    (r'wind river mouth', 'Wind River (mouth)'),
    (r'^wind river', 'Wind River'),
    (r'north fork lewis', 'North Fork Lewis River'),
    (r'east fork lewis', 'East Fork Lewis River'),
    (r'^lewis river', 'Lewis River'),
    (r'washougal.*slough', 'Washougal River (Slough)'),
    (r'^washougal', 'Washougal River'),
    (r'^elochoman', 'Elochoman River'),
)


def canonical_place(name):
    """One name per water, whatever the week's report called it."""
    text = re.sub(r'\s+', ' ', str(name or '')).strip()
    m = SECTION.match(text)
    if m:
        number = m.group(1)
        return f'Section {number} ({SECTION_NAMES.get(number, m.group(2).strip())})'
    low = text.lower()
    for pattern, canonical in TRIBUTARY:
        if re.search(pattern, low):
            return canonical
    return text


VERB = re.compile(r'\b(kept|retained|harvested|released|releasing)\b', re.I)

#: a paragraph starts with a place name followed by an em dash
PLACE = re.compile(
    r'(?:(?<=\. )|(?<=\n)|^)\s*'
    r'(?P<place>(?:Section \d+ \([^)\n]{1,40}\))|'
    r'(?:[A-Z][A-Za-z\'’.]*(?:\s+[A-Za-z0-9\'’.()/-]+){0,6}?))'
    r'\s*[–—-]{1,2}\s+(?=[A-Z0-9])')

GROUP_HEADINGS = re.compile(
    r'^\W{0,3}(Salmon/Steelhead|Salmon|Steelhead|Sturgeon|Shad|Walleye|Trout|Bass|'
    r'Smelt|Mainstem Columbia River|Columbia River Tributaries)\s*:?\s*$', re.M)

#: dropped outright: these paragraphs are regulation notes, not creel
NOT_CREEL = re.compile(
    r'weir|regulation|pamphlet|hatchery program|reminder|contact|blog|'
    r'resources|webcam|forecast', re.I)

PERIOD = re.compile(
    r'(?:Report|report)?:?\s*([A-Z][a-z]{2,8})\.?\s*(\d{1,2})\s*[-–]\s*'
    r'(?:([A-Z][a-z]{2,8})\.?\s*)?(\d{1,2})')
DATED = re.compile(r'Date:\s*([A-Z][a-z]{2,8})\.?\s+(\d{1,2}),?\s+(\d{4})')


def number(token):
    t = str(token).strip().lower().replace(',', '')
    if t.isdigit():
        return int(t)
    if '-' in t:                       # twenty-five
        parts = [WORDS.get(p) for p in t.split('-')]
        if all(p is not None for p in parts):
            return sum(parts)
    return WORDS.get(t)


#: the filename is often the only place the covered week is written out:
#: "fishing_report_april_12-18_2021", "swwa-fishing-reports-june-29-july-5-2026"
FILE_PERIOD = re.compile(
    r'([a-z]{3,9})[_\- ](\d{1,2})\s*[-–]\s*(?:([a-z]{3,9})[_\- ])?(\d{1,2})'
    r'(?:[_\-, ]+(20\d{2}))?', re.I)


def report_week(text, filename=None):
    """The Monday of the week a report covers.

    Three different generations of this report say it three different ways: the
    current one prints the period on the cover, the 2021-2022 run prints only a
    publication date, and several name the period in the file and nowhere else.
    The publication date is the last resort, and is stepped back a week, because
    these reports are always published about the week just ended.
    """
    dated = DATED.search(text) or re.match(
        r'\s*([A-Z][a-z]{2,8})\.?\s+(\d{1,2}),?\s+(20\d{2})', text)
    year = dated.group(3) if dated else None
    if not year:
        m = re.search(r'\b(20\d{2})\b', text[:400])
        year = m.group(1) if m else None

    if year:
        pm = PERIOD.search(text[:300])
        if pm:
            day = common.parse_day(f'{pm.group(1)} {pm.group(2)}', year)
            if day:
                return day

    if filename:
        fm = FILE_PERIOD.search(os.path.basename(filename).replace('%20', ' '))
        if fm:
            day = common.parse_day(f'{fm.group(1)} {fm.group(2)}',
                                   fm.group(5) or year)
            if day:
                return day

    if dated:
        published = common.parse_day(f'{dated.group(1)} {dated.group(2)}', year)
        if published:
            d = date.fromisoformat(published) - timedelta(days=7)
            return (d - timedelta(days=d.weekday())).isoformat()
    return None


def _species_at(phrase, fallback):
    m = SPECIES_RE.search(phrase)
    if not m:
        return fallback
    for name, value in m.groupdict().items():
        if value:
            return SPECIES_BY_GROUP[name]
    return fallback


def catch_in(sentence, fallback_species):
    """Every '<count> <species>' the sentence attributes to kept or released."""
    out = []
    for vm in VERB.finditer(sentence):
        fate = 'kept' if vm.group(1).lower() in (
            'kept', 'retained', 'harvested') else 'released'
        nxt = VERB.search(sentence, vm.end())
        clause = sentence[vm.end():nxt.start() if nxt else len(sentence)]
        for im in ITEM.finditer(clause):
            n = number(im.group(1))
            if n is None:
                continue
            sp = _species_at(im.group(2), None)
            if sp is None:
                continue
            out.append((sp, fate, n))
    if not out and re.search(r'no catch|nothing (?:was )?(?:kept|caught)',
                             sentence, re.I) and fallback_species:
        out.append((fallback_species, 'kept', 0))
    return out


def paragraphs(text):
    """Split the report body into (place, group heading, paragraph text)."""
    flat = re.sub(r'\n(?=[a-z0-9(])', ' ', text)     # rejoin wrapped sentences
    flat = re.sub(r'Washington Department of Fish and Wildlife\s*\d*', '', flat)
    group = ''
    out = []
    for chunk in re.split(r'\n', flat):
        line = chunk.strip()
        if not line:
            continue
        gm = GROUP_HEADINGS.match(line)
        if gm:
            group = gm.group(1)
            continue
        m = PLACE.match(line)
        if not m:
            continue
        place = canonical_place(re.sub(r'\s+', ' ', m.group('place')).strip(' .'))
        body = line[m.end():].strip()
        if not place or NOT_CREEL.search(body[:120]):
            continue
        out.append((place, group, body))
    return out


def parse(text, *, filename=None, stats=None):
    day = report_week(text, filename)
    if not day:
        if stats is not None:
            stats['undated'] += 1
        return [], []
    catch_rows, effort_rows = [], []
    for place, group, body in paragraphs(text):
        fallback = {'Sturgeon': 'Sturgeon', 'Shad': 'Shad',
                    'Walleye': 'Walleye'}.get(group)
        anglers = 0
        seen_effort = False
        for m in BANK.finditer(body):
            n = number(m.group(1))
            if n is not None:
                anglers += n
                seen_effort = True
        for m in BOAT.finditer(body):
            n = number(m.group(2))
            if n is not None:
                anglers += n
                seen_effort = True
        if not seen_effort:
            if BANK_NONE.search(body) or BOAT_NONE.search(body) \
                    or NO_EFFORT.match(body):
                seen_effort = True     # a reported zero is data
            else:
                if stats is not None:
                    stats['no_effort_clause'] += 1
                continue
        effort_rows.append(common.effort(
            day, SOURCE, place, anglers=anglers, region=REGION, water=FRESH,
            catch_area=group))
        for sentence in re.split(r'(?<=[.;])\s+', body):
            for sp, fate, n in catch_in(sentence, fallback):
                catch_rows.append(common.catch(
                    day, SOURCE, place, sp, n, fate=fate,
                    region=REGION, water=FRESH, catch_area=group))
        if stats is not None:
            stats['places'] += 1
    return catch_rows, effort_rows


def discover(say=print):
    html_text = common.get_text(
        URL, cache_path=os.path.join(paths.PAGE_DIR, 'southwest.html'), max_age_h=0)
    # the page mixes relative and absolute links to the same file store
    links = sorted({m for m in re.findall(
        r'href="(?:https://wdfw\.wa\.gov)?(/sites/default/files/[^"\s]+?\.pdf)"',
        html_text, re.I)})
    say(f'   southwest: {len(links)} weekly reports listed')
    return links


def load(*, full=False, say=print):
    import pikeminnow                   # shares the PDF reader
    catch_rows, effort_rows = [], []
    stats = {'places': 0, 'undated': 0, 'no_effort_clause': 0, 'reports': 0}
    for link in discover(say=say):
        dest = common.fetch_pdf(link, 'sw', origin=ORIGIN, full=full, say=say)
        if not dest:
            continue
        try:
            c, e = parse(pikeminnow.read_pdf(dest), filename=dest, stats=stats)
        except Exception as exc:
            say(f'!! could not read {os.path.basename(dest)}: {exc}')
            continue
        if e:
            stats['reports'] += 1
        catch_rows += c
        effort_rows += e
    say(f'   southwest: {stats["reports"]} reports read, '
        f'{len(effort_rows):,} river-weeks, {stats["undated"]} undated')
    return catch_rows, effort_rows


if __name__ == '__main__':
    c, e = load()
    print(len(c), len(e))
    print(sorted({r['date'][:4] for r in e}))
    print(sorted({r['location'] for r in e})[:40])
