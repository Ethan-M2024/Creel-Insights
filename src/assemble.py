"""Inject the data payload into the page template."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths
from paths import open_text

SITE = 'https://ethan-m2024.github.io/Creel-Insights/'


def share_description():
    """The sentence a link preview shows, written from the data rather than fixed.

    Social crawlers do not run JavaScript, so this cannot be filled in by the page.
    Deriving it here keeps the figures it quotes honest as the record grows.
    """
    with open_text(paths.PAYLOAD) as f:
        meta = json.load(f)['meta']
    first = (meta.get('first') or '')[:4]
    fish = meta.get('total_fish') or 0
    anglers = meta.get('total_anglers') or 0
    return (f'Every Washington creel report in one place: {fish:,} fish and '
            f'{anglers:,} anglers interviewed since {first}, with a map of where '
            f'catch rates are climbing and where they have fallen off.')


def main():
    tpl = open(paths.TEMPLATE, encoding='utf-8').read()
    with open_text(paths.PAYLOAD) as f:
        data = f.read()
    assert '__DATA__' in tpl, 'the template has lost its __DATA__ placeholder'
    for token, value in (('__DESC__', share_description()), ('__URL__', SITE)):
        assert token in tpl, f'the template has lost its {token} placeholder'
        tpl = tpl.replace(token, value.replace('"', '&quot;'))
    # a payload containing "</script>" would end the block early; escaping the
    # slash keeps the JSON valid and the script intact
    out = tpl.replace('__DATA__', data.replace('</', '<\\/'))
    os.makedirs(paths.DOCS, exist_ok=True)
    with open(paths.DASHBOARD, 'w', encoding='utf-8') as f:
        f.write(out)
    print(f'   dashboard written: {os.path.relpath(paths.DASHBOARD, paths.ROOT)} '
          f'({len(out) // 1024} KB)')
    return paths.DASHBOARD


if __name__ == '__main__':
    main()
