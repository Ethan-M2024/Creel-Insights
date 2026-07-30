"""Emergency rule changes: the reason a quota table and the water can disagree.

The guideline tables say whether a quota-managed fishery has used up its allowance.
They say nothing about whether you can fish, which is set by the permanent rules in
the annual pamphlet and then changed, sometimes weekly, by emergency rule. An area
with no row in the guideline tables — Marine Area 12 all winter — is not closed; it
simply has no quota fishery to track.

So the rules WDFW publish are read too. Each one states its action, the dates it is
in force, the species and the water, in labelled fields on its own page, and those
fields are what is read; the surrounding prose is not interpreted.

Nothing here is a substitute for the regulations themselves, and the dashboard says
so and links to them. It is a pointer to what changed and when.
"""
import os
import re
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths
import safety

INDEX = 'https://wdfw.wa.gov/fishing/regulations/emergency-rules'
ORIGIN = 'https://wdfw.wa.gov'
PAMPHLET = 'https://wdfw.wa.gov/fishing/regulations/sport-fishing'

FIELDS = ('title', 'url', 'published', 'action', 'effective', 'species',
          'location', 'areas', 'ends')

#: how far back to read. A rule from three seasons ago is history, not news, and
#: each one is a page fetch.
MONTHS_BACK = 14

MONTHS = {m: i for i, m in enumerate(
    ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
     'september', 'october', 'november', 'december'], 1)}

LABEL = re.compile(
    r'(Action|Effective dates?|Species affected|Location|Salmon rules|'
    r'Reason for action)\s*:?\s*', re.I)

AREA_IN_TEXT = re.compile(r'marine area\s*(\d+(?:\.\d+)?)', re.I)


def discover(say=print):
    """Every rule listed on the index, with the month WDFW filed it under."""
    html_text = common.get_text(
        INDEX, cache_path=os.path.join(paths.PAGE_DIR, 'emergency_rules.html'),
        max_age_h=0)
    out = []
    # the index is month headings, each followed by that month's list
    parts = re.split(r'<h2[^>]*>(.*?)</h2>', html_text, flags=re.S)
    for i in range(1, len(parts) - 1, 2):
        heading = common.strip_tags(parts[i])
        m = re.match(r'([A-Za-z]+)\s+(20\d{2})', heading)
        if not m:
            continue
        month = MONTHS.get(m.group(1).lower())
        if not month:
            continue
        published = date(int(m.group(2)), month, 1)
        for link, text in re.findall(
                r'href="(/fishing/regulations/emergency-rules/[^"]+)"[^>]*>(.*?)</a>',
                parts[i + 1], re.S):
            out.append((published.isoformat(), link, common.strip_tags(text)))
    say(f'   emergency rules: {len(out)} listed')
    return out


def parse(html_text, *, title='', url='', published=''):
    """Pull the labelled fields out of one rule page."""
    body = re.sub(r'<script.*?</script>|<style.*?</style>', '', html_text, flags=re.S)
    text = common.strip_tags(body)
    # cut the page furniture off the front: the fields always start at "Action:"
    start = text.find('Action:')
    if start < 0:
        return None
    text = text[start:]
    fields, last, pos = {}, None, 0
    for m in LABEL.finditer(text):
        if last:
            fields[last] = text[pos:m.start()].strip(' .;')
        last = m.group(1).lower().replace(' dates', '').replace(' date', '')
        pos = m.end()
    if last:
        fields[last] = text[pos:pos + 600].strip(' .;')

    location = fields.get('location', '')
    areas = sorted({m.group(1) for m in AREA_IN_TEXT.finditer(
        location + ' ' + title + ' ' + fields.get('action', ''))})
    return {
        'title': title, 'url': ORIGIN + url, 'published': published,
        'action': fields.get('action', '')[:400],
        # a rule whose dates are written into a sentence rather than the field can
        # leave a stray word behind; better blank than misleading
        'effective': (fields.get('effective', '')[:160]
                      if len(fields.get('effective', '')) > 4 else ''),
        'species': fields.get('species affected', '')[:120],
        'location': location[:300],
        'areas': areas,
        'ends': _ends(fields.get('effective', '')),
    }


OPEN_ENDED = re.compile(r'further notice|indefinite|until closed|ongoing', re.I)


def _ends(effective):
    """The last day a rule is in force, when it names one.

    "Aug. 1 - Sept. 30, 2026" ends on 30 September. "July 9, 2026, until further
    notice" does not end at all, and reading its one date as an end would mark a
    rule that is still in force as expired — which is the opposite of the truth.
    """
    text = effective or ''
    if OPEN_ENDED.search(text):
        return ''
    m = re.search(r'(?:through|thru|to|until|[-–])\s*([A-Z][a-z]{2,8})\.?\s*'
                  r'(\d{1,2}),?\s*(20\d{2})', text)
    if m:
        return common.parse_day(f'{m.group(1)} {m.group(2)}', m.group(3)) or ''
    # "July 18 - 31, 2026": the end day borrows the month it started in
    m = re.search(r'([A-Z][a-z]{2,8})\.?\s*(\d{1,2})\s*[-–]\s*(\d{1,2}),?\s*'
                  r'(20\d{2})', text)
    if m:
        return common.parse_day(f'{m.group(1)} {m.group(3)}', m.group(4)) or ''
    dates = re.findall(r'([A-Z][a-z]{2,8})\.?\s*(\d{1,2}),?\s*(20\d{2})', text)
    if len(dates) >= 2:                      # a range written without a joining word
        mon, day, year = dates[-1]
        return common.parse_day(f'{mon} {day}', year) or ''
    # one date and nothing to say it is an end: it is when the rule started
    return ''


def load(*, full=False, say=print):
    cutoff = date.today().replace(day=1)
    year, month = cutoff.year, cutoff.month - MONTHS_BACK
    while month <= 0:
        month += 12
        year -= 1
    cutoff = date(year, month, 1).isoformat()

    out = []
    for published, link, title in discover(say=say):
        if published < cutoff:
            continue
        name = safety.safe_filename('rule__' + link.rsplit('/', 1)[-1] + '.html')
        cache = os.path.join(paths.PAGE_DIR, name)
        # a published rule is not edited afterwards, so it is fetched once
        try:
            html_text = common.get_text(ORIGIN + link, cache_path=cache)
        except Exception as exc:
            say(f'!! could not fetch {link}: {exc}')
            continue
        rule = parse(html_text, title=title, url=link, published=published)
        if rule:
            out.append(rule)
    out.sort(key=lambda r: (r['published'], r['title']), reverse=True)
    say(f'   emergency rules: {len(out)} read since {cutoff}')
    return out


if __name__ == '__main__':
    for r in load()[:8]:
        print(r['published'], r['areas'], r['title'][:60])
        print('   ', r['effective'], '|', r['action'][:90])
