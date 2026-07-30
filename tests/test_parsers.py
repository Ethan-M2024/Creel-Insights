"""Unit tests for the parsers, run against the shapes WDFW actually publishes.

Each test feeds a parser a fragment copied from a real report and checks the rows
that come back. They need no network and no downloaded reports, so they run in a
second and catch the failure that matters most here: WDFW changing a layout and the
parser silently returning nothing.

    python3 tests/test_parsers.py
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'sources'))

import common          # noqa: E402
import puget           # noqa: E402
import buoy10         # noqa: E402
import willapa        # noqa: E402
import ocean          # noqa: E402
import pikeminnow     # noqa: E402
import southwest      # noqa: E402
import halibut       # noqa: E402
import quotas        # noqa: E402
import build_data     # noqa: E402


class TestCommon(unittest.TestCase):
    def test_species_names_collapse(self):
        self.assertEqual(common.species('Chinook salmon'), 'Chinook')
        self.assertEqual(common.species('Coastal Cutthroat'), 'Cutthroat')
        self.assertEqual(common.species('SOCKEYE'), 'Sockeye')

    def test_unknown_species_survives(self):
        # a species nobody has mapped must reach the dashboard, not vanish
        self.assertEqual(common.species('lamprey'), 'Lamprey')

    def test_origin_from_fin_mark(self):
        self.assertEqual(common.origin('AD'), 'hatchery')
        self.assertEqual(common.origin('UM'), 'wild')
        self.assertEqual(common.origin(''), 'unknown')

    def test_blank_is_not_zero(self):
        self.assertEqual(common.num(''), '')
        self.assertEqual(common.num('N/A'), '')
        self.assertEqual(common.num('1,234'), 1234)

    def test_day_forms(self):
        self.assertEqual(common.parse_day('Aug. 1', 2025), '2025-08-01')
        self.assertEqual(common.parse_day('August 1', '2025'), '2025-08-01')
        self.assertIsNone(common.parse_day('see note', 2025))


PUGET_PAGE = """
<table><caption>Jul 30, 2026</caption>
<thead><tr><th>Ramp/site</th><th>Catch area</th><th># Interviews (Boat or Shore)</th>
<th>Anglers</th><th>Chinook (per angler)</th><th>Chinook</th><th>Coho</th>
<th>Halibut</th></tr></thead>
<tbody>
<tr><td>Mason's East Docks (*1159)*</td><td>Area 5, Sekiu and Pillar Point</td>
<td>24</td><td>52</td><td>0.67</td><td>35</td><td>12</td><td>0</td></tr>
<tr><td>Camano Island State Park Public Ramp</td><td>N/A</td>
<td>4</td><td>6</td><td>0.25</td><td>1</td><td>0</td><td>0</td></tr>
</tbody></table>
"""


class TestPuget(unittest.TestCase):
    def setUp(self):
        self.catch, self.effort = puget.parse_page(PUGET_PAGE)

    def test_effort_rows(self):
        self.assertEqual(len(self.effort), 2)
        self.assertEqual(self.effort[0]['anglers'], 52)
        self.assertEqual(self.effort[0]['date'], '2026-07-30')

    def test_site_number_is_stripped(self):
        self.assertEqual(self.effort[0]['location'], "Mason's East Docks")

    def test_na_catch_area_is_blank(self):
        self.assertEqual(self.effort[1]['catch_area'], '')

    def test_per_angler_column_is_not_a_species(self):
        species = {r['species'] for r in self.catch}
        self.assertEqual(species, {'Chinook', 'Coho', 'Halibut'})

    def test_counts(self):
        chinook = [r for r in self.catch if r['species'] == 'Chinook'
                   and r['location'] == "Mason's East Docks"][0]
        self.assertEqual(chinook['fish'], 35)
        self.assertEqual(chinook['fate'], 'kept')


BUOY10_PAGE = """
<h3>2025</h3>
<table><tr><th>Date</th><th>Boats</th><th>Anglers</th><th>Chinook Kept</th>
<th>Coho Kept</th><th>Comments</th></tr>
<tr><td>Aug. 1</td><td>47</td><td>118</td><td>29</td><td>15</td><td>Any Chinook</td></tr>
<tr><td>Aug. 2</td><td>0</td><td>0</td><td>0</td><td>0</td><td>Closed</td></tr>
</table>
"""


class TestBuoy10(unittest.TestCase):
    def setUp(self):
        self.catch, self.effort = buoy10.parse(BUOY10_PAGE)

    def test_year_comes_from_the_heading(self):
        self.assertEqual(self.effort[0]['date'], '2025-08-01')

    def test_closed_days_are_not_recorded_as_slow_days(self):
        self.assertEqual(len(self.effort), 1)

    def test_both_species(self):
        self.assertEqual({r['species']: r['fish'] for r in self.catch},
                         {'Chinook': 29, 'Coho': 15})


WILLAPA_PAGE = """
<h3>2025 Willapa Bay Marine Area 2.1 Recreational Salmon Fishery</h3>
<table><tr><th>Mgmt Wk</th><th>Dates</th><th># of Interview</th><th># of Anglers</th>
<th># AD Clipped Chinook Retained</th><th># Unmarked Chinook Retained</th>
<th># Coho Retained (AD clipped + unmarked)</th><th># Unmarked Chinook Released</th></tr>
<tr><td>32</td><td>8/5-8/11</td><td>105</td><td>219</td><td>29</td><td>0</td><td>3</td><td>6</td></tr>
</table>
"""


class TestWillapa(unittest.TestCase):
    def setUp(self):
        self.catch, self.effort = willapa.parse(WILLAPA_PAGE)

    def test_week_start_date(self):
        self.assertEqual(self.effort[0]['date'], '2025-08-05')

    def test_origin_is_kept_apart(self):
        kept = {(r['species'], r['origin'], r['fate']): r['fish'] for r in self.catch}
        self.assertEqual(kept[('Chinook', 'hatchery', 'kept')], 29)
        self.assertEqual(kept[('Chinook', 'wild', 'kept')], 0)
        self.assertEqual(kept[('Chinook', 'wild', 'released')], 6)


OCEAN_PAGE = """
<h2>Coastwide Ocean Totals</h2>
<table><tr><th>Stat Week</th><th>Dates</th><th>Number of anglers</th>
<th>Number of Chinook</th></tr>
<tr><td>26</td><td>Jun 22-28</td><td>4955</td><td>1951</td></tr></table>
<h2>Westport</h2>
<table><tr><th>Stat Week</th><th>Dates</th><th>Number of anglers</th>
<th>Number of Chinook</th><th>Cumulative Chinook</th></tr>
<tr><td>26</td><td>Jun 22-28</td><td>921</td><td>334</td><td>574</td></tr></table>
"""


class TestOcean(unittest.TestCase):
    def setUp(self):
        self.catch, self.effort = ocean.parse(OCEAN_PAGE, default_year='2026')

    def test_coastwide_total_is_skipped(self):
        # it is the sum of the four ports; counting it would double every fish
        self.assertEqual({r['location'] for r in self.effort},
                         {'Westport (Marine Area 2)'})

    def test_cumulative_column_is_not_catch(self):
        self.assertEqual([r['fish'] for r in self.catch], [334])

    def test_week_start(self):
        self.assertEqual(self.effort[0]['date'], '2026-06-22')


PIKEMINNOW_TEXT = """Northern Pikeminnow Sport-Reward Fishery 2019
Week 29
July 15 - July 21, 2019
Weekly Year-to-Date
Station Effort Tags Total NPM CPUE Effort Tags Total NPM CPUE
Cathlamet 139 1 1,832 1,833 13.2 1,495 7 12,882 12,889 8.6
Boyer Park 154 2 1,173 1,175 7.6 1,423 12 13,434 13,446 9.4
Totals 903 7 7,381 7,388 8.2 13,816 109 83,145 83,254 6.0
"""


class TestPikeminnow(unittest.TestCase):
    def setUp(self):
        self.catch, self.effort = pikeminnow.parse(PIKEMINNOW_TEXT)

    def test_stations_only(self):
        self.assertEqual([r['location'] for r in self.effort],
                         ['Cathlamet', 'Boyer Park'])

    def test_weekly_not_year_to_date(self):
        self.assertEqual(self.catch[0]['fish'], 1833)
        self.assertEqual(self.effort[0]['anglers'], 139)

    def test_totals_row_is_dropped(self):
        self.assertNotIn('Totals', [r['location'] for r in self.effort])


SOUTHWEST_TEXT = """Date: July 13, 2026
Columbia River and Tributary Fishery Report:
July 6-12
Mainstem Columbia River
Salmon/Steelhead
Section 6 (Kalama) — 110 bank anglers kept eight steelhead and released four steelhead. 6
boats/10 rods kept one steelhead, and released three Chinook, one jack, and one steelhead.
Section 7 (Cowlitz) — No bank effort reported. 1 boat/2 rods had no catch.
Sturgeon
Section 6 (Kalama) — 4 boats/11 rods released four sublegal, one legal, and one oversize sturgeon.
"""


class TestSouthwest(unittest.TestCase):
    def setUp(self):
        self.catch, self.effort = southwest.parse(SOUTHWEST_TEXT)

    def test_report_week(self):
        self.assertEqual(southwest.report_week(SOUTHWEST_TEXT), '2026-07-06')

    def test_bank_and_boat_effort_are_added(self):
        kalama = [r for r in self.effort
                  if r['location'] == 'Section 6 (Kalama)'
                  and r['catch_area'] == 'Salmon/Steelhead'][0]
        self.assertEqual(kalama['anglers'], 120)      # 110 bank + 10 rods

    def test_spelled_out_numbers(self):
        kept = sum(r['fish'] for r in self.catch
                   if r['species'] == 'Steelhead' and r['fate'] == 'kept')
        self.assertEqual(kept, 9)                     # eight plus one

    def test_a_bare_jack_is_a_chinook(self):
        released = sum(r['fish'] for r in self.catch
                       if r['species'] == 'Chinook' and r['fate'] == 'released')
        self.assertEqual(released, 4)                 # three Chinook plus one jack

    def test_sturgeon_size_words_are_one_species(self):
        sturgeon = sum(r['fish'] for r in self.catch if r['species'] == 'Sturgeon')
        self.assertEqual(sturgeon, 6)

    def test_reported_zero_effort_is_kept(self):
        cowlitz = [r for r in self.effort if r['location'] == 'Section 7 (Cowlitz)']
        self.assertEqual(len(cowlitz), 1)
        self.assertEqual(cowlitz[0]['anglers'], 2)


HALIBUT_PAGE = """
<h2>2026 Pacific halibut landings summary</h2>
<h3>Puget Sound - Quota 80,512 lbs</h3>
<table>
<tr><th>Week</th><th>Dates open</th><th>Weekly</th><th>Cumulative</th></tr>
<tr><th>Halibut (number)</th><th>Anglers (number)</th><th>Average weight (pounds)</th>
<th>Total Pounds</th><th>Pounds</th><th>Quota taken</th><th>Pounds remaining</th></tr>
<tr><td>14</td><td>Apr 2-5</td><td>177</td><td>1,047</td><td>19.6</td><td>3,470</td>
<td>3,470</td><td>4.3%</td></tr>
<tr><td>15</td><td>Apr 30; May 1-2</td><td>164</td><td>1,373</td><td>19.5</td>
<td>3,191</td><td>6,661</td><td>8.3%</td></tr>
</table>
"""


class TestHalibut(unittest.TestCase):
    def setUp(self):
        self.catch, self.effort = halibut.parse(HALIBUT_PAGE)

    def test_subarea_from_heading(self):
        self.assertEqual({r['location'] for r in self.effort}, {'Puget Sound halibut'})

    def test_year_from_the_summary_heading(self):
        self.assertEqual(self.effort[0]['date'], '2026-04-02')

    def test_a_split_week_starts_on_its_first_open_day(self):
        self.assertEqual(self.effort[1]['date'], '2026-04-30')

    def test_fish_and_anglers_are_not_swapped(self):
        self.assertEqual(self.catch[0]['fish'], 177)
        self.assertEqual(self.effort[0]['anglers'], 1047)


MERGED_TABLE = """
<table>
<tr><th>Area</th><th>Opening Date</th><th>Criteria</th><th>Guideline</th></tr>
<tr><td rowspan="2">11</td><td>June 1</td><td>Harvest Quota</td><td>1,423</td></tr>
<tr><td>July 23</td><td>Harvest Quota</td><td>3,379</td></tr>
</table>
"""


class TestMergedCells(unittest.TestCase):
    """A merged cell is data: WDFW's rowspan is what says the second season is
    also Area 11, and dropping it drops an open fishery from the page."""

    def test_a_rowspan_fills_the_rows_it_covers(self):
        grid = common.table_grid(MERGED_TABLE)
        self.assertEqual([r[0] for r in grid], ['Area', '11', '11'])
        self.assertEqual(grid[2], ['11', 'July 23', 'Harvest Quota', '3,379'])

    def test_every_row_is_the_same_width(self):
        grid = common.table_grid(MERGED_TABLE)
        self.assertEqual({len(r) for r in grid}, {4})


SEASONAL_PAGE = """
<h2>Summer Chinook fishery guidelines</h2>
<table>
<tr><th>Area</th><th>Opening Date</th><th>Management Criteria</th>
<th>Encounters Guideline /Harvest Quota</th><th>Encounters /Harvest</th>
<th>Estimate Valid Through:</th><th>Percentage of Criteria</th><th>Current Status</th></tr>
<tr><td>5</td><td>July 1</td><td>Legal Size Encounters</td><td>4,323</td><td>3,477</td>
<td>July 26, 2026</td><td>80%</td><td>Open</td></tr>
<tr><td>Total Sublegal Encounters</td><td>914</td><td>38</td></tr>
<tr><td>9</td><td>July 1</td><td>Harvest Quota</td><td>2,650</td><td>3,479</td>
<td>July 18, 2026</td><td>131%</td><td>Closed</td></tr>
<tr><td rowspan="2">11</td><td>June 1</td><td>Harvest Quota</td><td>1,423</td>
<td>769</td><td>June 30, 2026</td><td>54%</td><td>Closed</td></tr>
<tr><td>July 23</td><td>Harvest Quota</td><td>3,379</td><td>499</td>
<td>July 26, 2026</td><td>15%</td><td>Open</td></tr>
</table>
"""


class TestQuotas(unittest.TestCase):
    def setUp(self):
        self.rows = quotas.parse_seasonal(SEASONAL_PAGE)

    def test_guideline_and_running_total_are_different_columns(self):
        area5 = [r for r in self.rows if r['area'] == 'Marine Area 5'][0]
        self.assertEqual(area5['limit'], 4323)
        self.assertEqual(area5['taken'], 3477)

    def test_over_the_guideline_is_reported_as_over(self):
        area9 = [r for r in self.rows if r['area'] == 'Marine Area 9'][0]
        self.assertEqual(area9['percent'], 1.31)
        self.assertEqual(area9['status'], 'Closed')

    def test_subtotal_rows_are_not_fisheries(self):
        self.assertEqual({r['area'] for r in self.rows if r['kind'] == 'fishery'},
                         {'Marine Area 5', 'Marine Area 9', 'Marine Area 11'})

    def test_an_area_can_run_two_seasons_at_once(self):
        # Area 11's June season closed on its end date at 54%; its July season is
        # open. Reporting only the first would call an open fishery closed.
        eleven = [r for r in self.rows
                  if r['area'] == 'Marine Area 11' and r['kind'] == 'fishery']
        self.assertEqual(len(eleven), 2)
        by_open = {r['opening']: r for r in eleven}
        self.assertEqual(by_open['June 1']['status'], 'Closed')
        self.assertEqual(by_open['July 23']['status'], 'Open')
        self.assertEqual(by_open['July 23']['percent'], 0.15)

    def test_the_date_is_the_estimate_not_the_fetch(self):
        area5 = [r for r in self.rows if r['area'] == 'Marine Area 5'][0]
        self.assertEqual(area5['valid_through'], '2026-07-26')

    def test_numeric_dates_parse_too(self):
        self.assertEqual(quotas._valid_through('04/11/26'), '2026-04-11')


class TestTrendArithmetic(unittest.TestCase):
    """The comparison the whole dashboard turns on, on figures worked by hand."""

    def setUp(self):
        from datetime import date, timedelta
        self.today = date(2026, 7, 30)
        self.catch, self.effort = {}, {}
        # this year: 100 anglers, 50 Chinook in the recent fortnight
        for i in range(14):
            d = (self.today - timedelta(days=i)).isoformat()
            self.effort[(0, d)] = [10, 0.0, 5]
            self.catch[(0, 'Chinook', d)] = [5, 1]
        # a year ago, same fortnight: the same effort but half the fish
        for i in range(24):
            d = (self.today.replace(year=2025) - timedelta(days=i)).isoformat()
            self.effort[(0, d)] = [10, 0.0, 5]
            self.catch[(0, 'Chinook', d)] = [2, 0]

    def test_rate_against_the_same_weeks_last_year(self):
        rows = build_data.trends(self.catch, self.effort, {},
                                 {'Chinook': 0}, self.today, say=lambda *a, **k: None)
        row = [r for r in rows if r['w'] == 14][0]
        self.assertEqual(row['cpue'], 0.5)            # 70 fish from 140 anglers
        self.assertEqual(row['season'], 0.2)          # 2 fish per 10 anglers
        self.assertEqual(row['anglers'], 140)

    def test_a_thin_window_is_marked_rather_than_hidden(self):
        # every place that reported fishing belongs on the map; the ones resting on
        # a handful of anglers are flagged so nothing ranks them
        thin_effort = {k: [1, 0.0, 1] for k in self.effort}
        rows = build_data.trends(self.catch, thin_effort, {}, {'Chinook': 0},
                                 self.today, say=lambda *a, **k: None)
        self.assertTrue(rows)
        self.assertTrue(all(r['thin'] == 1 for r in rows))

    def test_a_solid_window_is_not_marked_thin(self):
        rows = build_data.trends(self.catch, self.effort, {}, {'Chinook': 0},
                                 self.today, say=lambda *a, **k: None)
        self.assertTrue(all(r['thin'] == 0 for r in rows))


if __name__ == '__main__':
    unittest.main(verbosity=2)
