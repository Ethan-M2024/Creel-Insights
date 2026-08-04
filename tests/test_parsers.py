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
import socrata       # noqa: E402
import geo           # noqa: E402
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

    def test_a_closed_week_is_the_same_station(self):
        # "Bingen Closed" was becoming a second station, splitting one history
        # between the weeks it was open and the weeks it was not
        self.assertEqual(pikeminnow.clean_station('Bingen Closed'), 'Bingen')
        self.assertEqual(pikeminnow.clean_station('Cascade Locks-closed'),
                         'Cascade Locks')
        self.assertEqual(pikeminnow.clean_station('Stevenson'), 'Stevenson')

    def test_totals_row_is_dropped(self):
        self.assertNotIn('Totals', [r['location'] for r in self.effort])


#: the 2015 layout: four weekly columns instead of five, and the incidental catch
#: printed beside the pikeminnow. WDFW cut the rate short here rather than rounding
#: it — 60 fish to 41 anglers is printed 1.4, not 1.5.
PIKEMINNOW_2015 = """Northern Pikeminnow Sport-Reward Fishery 2015
DRAFT WEEKLY FIELD ACTIVITY REPORT
May 1 - May 3, 2015 Weekly Year-to-Date Weekly Incidental Catch
Station Effort Tags Total Fish CPUE Effort Tags Total Fish CPUE SMB WAL CC/CF/BH AMS WS YP
Willow Grove 41 0 60 1.4 41 0 60 1.4 1 0 1 0 0 7
Rainier 20 0 15 0.8 20 0 15 0.8 0 0 0 0 0 2
"""

#: 2024 rounds the same figure up, prints a stray space before the comma, and adds a
#: column of opening dates
PIKEMINNOW_2024 = """Northern Pikeminnow Sport-Reward Fishery 2024
June 24 - June 30 , 2024 Week 26
Station Opens Effort Tags Total NPM CPUE Effort Tags Total NPM CPUE
Cathlamet 96 0 1,004 1,004 10.5 581 0 5,361 5,361 9.2
"""


class TestAnglerHours(unittest.TestCase):
    """The interview times, which are the only clock in any of these reports."""

    def test_a_time_without_a_date_is_still_a_time(self):
        # read as timestamps they all failed, and every angler-hour came out zero
        self.assertAlmostEqual(socrata._clock('07:53:00'), 7 + 53 / 60, places=4)
        self.assertIsNone(socrata._clock('not a time'))
        self.assertIsNone(socrata._clock(''))

    def test_hours_are_multiplied_by_the_anglers_on_the_trip(self):
        row = {'fishing_start_time': '06:00:00', 'fishing_end_time': '09:00:00',
               'angler_count': '2'}
        self.assertEqual(socrata._hours(row), 6.0)

    def test_a_trip_past_midnight(self):
        row = {'fishing_start_time': '22:00:00', 'fishing_end_time': '01:00:00',
               'angler_count': '1'}
        self.assertEqual(socrata._hours(row), 3.0)

    def test_a_keying_slip_is_left_blank(self):
        row = {'fishing_start_time': '13:00:00', 'fishing_end_time': '02:00:00',
               'angler_count': '1'}
        self.assertEqual(socrata._hours(row), '')


class TestFieldNotes(unittest.TestCase):
    """Size, gear and bank-or-boat, aggregated out of the interviews."""

    INTERVIEWS = [{'interview_id': str(i), 'event_date': '2026-07-01',
                   'water_body': 'Ash Lake', 'project_name': 'R5 Inland Fish',
                   'angler_count': '1',
                   'angler_type': 'Bank' if i % 2 else 'Boat'} for i in range(40)]

    @property
    def catch(self):
        rows = []
        for i in range(40):
            rows.append({'interview_id': str(i), 'event_date': '2026-07-01',
                         'water_body': 'Ash Lake', 'species': 'Rainbow Trout',
                         'fate': 'Kept', 'fish_count': '1',
                         'fork_length_cm': str(30 + i % 10),
                         'gear_type': 'Bait' if i % 3 else 'Lure'})
        return rows

    def notes(self):
        real = socrata.fetch_all
        socrata.fetch_all = lambda dataset, **kw: (
            self.INTERVIEWS if dataset == socrata.INTERVIEWS else self.catch)
        try:
            return socrata.load(say=lambda *a: None)[3]
        finally:
            socrata.fetch_all = real

    def test_lengths_are_summarised_not_averaged_away(self):
        size = self.notes()['size']['Ash Lake|Rainbow trout']
        self.assertEqual(size['n'], 40)
        self.assertLessEqual(size['p25'], size['p50'])
        self.assertLessEqual(size['p50'], size['p75'])
        self.assertEqual(size['max'], 39.0)

    def test_gear_is_counted_per_species(self):
        gear = self.notes()['gear']['Ash Lake|Rainbow trout']
        self.assertEqual(gear['Bait'] + gear['Lure'], 40)

    def test_bank_and_boat_are_kept_apart(self):
        seat = self.notes()['seat']['Ash Lake']
        self.assertEqual(seat['Bank']['parties'], 20)
        self.assertEqual(seat['Boat']['parties'], 20)

    def test_a_keyed_length_in_millimetres_is_dropped(self):
        rows = self.catch
        rows[0]['fork_length_cm'] = '650'
        real = socrata.fetch_all
        socrata.fetch_all = lambda dataset, **kw: (
            self.INTERVIEWS if dataset == socrata.INTERVIEWS else rows)
        try:
            size = socrata.load(say=lambda *a: None)[3]['size']['Ash Lake|Rainbow trout']
        finally:
            socrata.fetch_all = real
        self.assertEqual(size['n'], 39)


class TestLocalityMatching(unittest.TestCase):
    """A dock borrows a neighbour's position, not a namesake's across the state."""

    def build(self, regions):
        sites = [{'name': 'Hood Park', 'lat': 46.214, 'lon': -119.02},
                 {'name': 'Blaine Ramp', 'lat': 48.99, 'lon': -122.76}]
        return geo.build(['Hood Canal Marina (Union)', 'Blaine Marina',
                          'Hood Park', 'Blaine Ramp'],
                         water_bodies={}, sites=sites, lakes=[], regions=regions,
                         say=lambda *a: None)[0]

    def test_a_namesake_in_another_region_is_refused(self):
        placed = self.build({'Hood Canal Marina (Union)': 'Puget Sound',
                             'Hood Park': 'Columbia River'})
        self.assertNotIn('Hood Canal Marina (Union)', placed)

    def test_a_neighbour_in_the_same_region_is_used(self):
        placed = self.build({'Blaine Marina': 'Puget Sound',
                             'Blaine Ramp': 'Puget Sound'})
        self.assertEqual(placed['Blaine Marina']['matched_to'], 'Blaine Ramp')
        self.assertEqual(placed['Blaine Marina']['lat'], 48.99)


class TestInterviewOutcomes(unittest.TestCase):
    """Counting the parties that caught one, rather than modelling them."""

    INTERVIEWS = [
        {'interview_id': 'a', 'event_date': '2026-07-01', 'water_body': 'Ash Lake',
         'project_name': 'R5 Inland Fish', 'angler_count': '2'},
        {'interview_id': 'b', 'event_date': '2026-07-01', 'water_body': 'Ash Lake',
         'project_name': 'R5 Inland Fish', 'angler_count': '1'},
        {'interview_id': 'c', 'event_date': '2026-07-01', 'water_body': 'Ash Lake',
         'project_name': 'R5 Inland Fish', 'angler_count': '3'},
    ]
    CATCH = [
        {'interview_id': 'a', 'event_date': '2026-07-01', 'water_body': 'Ash Lake',
         'species': 'Rainbow Trout', 'fate': 'Kept', 'fish_count': '2'},
        {'interview_id': 'a', 'event_date': '2026-07-01', 'water_body': 'Ash Lake',
         'species': 'Rainbow Trout', 'fate': 'Released', 'fish_count': '1'},
        {'interview_id': 'b', 'event_date': '2026-07-01', 'water_body': 'Ash Lake',
         'species': 'Rainbow Trout', 'fate': 'Kept', 'fish_count': '1'},
    ]

    def rows(self):
        real = socrata.fetch_all
        socrata.fetch_all = lambda dataset, **kw: (
            self.INTERVIEWS if dataset == socrata.INTERVIEWS else self.CATCH)
        try:
            return socrata.load(say=lambda *a: None)
        finally:
            socrata.fetch_all = real

    def test_one_row_per_place_species_day(self):
        _catch, _effort, success, _detail = self.rows()
        self.assertEqual(len(success), 1)
        row = success[0]
        self.assertEqual((row['location'], row['species']), ('Ash Lake', 'Rainbow trout'))

    def test_parties_are_counted_once_however_many_fish(self):
        # interview a has two catch records; it is one party, not two
        _catch, _effort, success, _detail = self.rows()
        self.assertEqual(success[0]['with_fish'], 2)
        self.assertEqual(success[0]['interviews'], 3)


class TestBuoy10Schedule(unittest.TestCase):
    """The season table is published before the season is fished."""

    TABLE = """<h2>2026</h2><table>
      <tr><th>Date</th><th>Boats</th><th>Anglers</th><th>Chinook Kept</th>
          <th>Coho Kept</th><th>Comments</th></tr>
      <tr><td>Aug 1</td><td>120</td><td>310</td><td>44</td><td>2</td><td></td></tr>
      <tr><td>Aug 2</td><td></td><td></td><td></td><td></td><td></td></tr>
    </table>"""

    def test_a_day_nobody_has_fished_is_not_a_day_of_no_fish(self):
        _catch, effort = buoy10.parse(self.TABLE)
        self.assertEqual([r['date'] for r in effort], ['2026-08-01'])

    def test_the_fished_day_is_read_whole(self):
        catch, effort = buoy10.parse(self.TABLE)
        self.assertEqual(effort[0]['anglers'], 310)
        self.assertEqual({r['species']: r['fish'] for r in catch},
                         {'Chinook': 44, 'Coho': 2})


class TestPikeminnowLayouts(unittest.TestCase):
    """Eleven seasons, seventeen column layouts, one arithmetic check."""

    def test_a_four_column_week_is_read(self):
        catch, effort = pikeminnow.parse(PIKEMINNOW_2015)
        self.assertEqual(effort[0]['anglers'], 41)
        npm = [r for r in catch if r['species'] == 'Northern pikeminnow']
        self.assertEqual(npm[0]['fish'], 60)

    def test_incidental_catch_is_kept_as_its_own_species(self):
        catch, _ = pikeminnow.parse(PIKEMINNOW_2015)
        got = {(r['location'], r['species']): r['fish'] for r in catch}
        self.assertEqual(got[('Willow Grove', 'Yellow perch')], 7)
        self.assertEqual(got[('Willow Grove', 'Smallmouth bass')], 1)
        self.assertEqual(got[('Willow Grove', 'Catfish')], 1)
        self.assertNotIn(('Willow Grove', 'Walleye'), got)    # a zero is not a catch

    def test_a_truncated_rate_still_matches(self):
        # 60 / 41 is 1.46, printed 1.4; demanding a rounded match dropped the row
        self.assertTrue(pikeminnow.matches_rate(60 / 41, 1.4, 1))
        self.assertTrue(pikeminnow.matches_rate(1004 / 96, 10.5, 1))
        self.assertFalse(pikeminnow.matches_rate(0 / 41, 1.4, 1))

    def test_a_stray_space_before_the_comma(self):
        _catch, effort = pikeminnow.parse(PIKEMINNOW_2024)
        self.assertEqual(effort[0]['date'], '2024-06-24')
        self.assertEqual(effort[0]['anglers'], 96)

    def test_a_single_day_report_has_a_date(self):
        text = PIKEMINNOW_2015.replace('May 1 - May 3, 2015', 'May 1, 2016')
        _catch, effort = pikeminnow.parse(text)
        self.assertEqual(effort[0]['date'], '2016-05-01')


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

    def test_one_name_per_water(self):
        # WDFW have written the same section four ways across seven seasons; each
        # spelling was becoming a separate place with its own split history
        for written in ('Sec 6 (Kalama)', 'Section 6 (Kalama)',
                        'Section 6 Section 6 (Kalama)', 'Sec. 6 (Kalama)'):
            self.assertEqual(southwest.canonical_place(written), 'Section 6 (Kalama)')

    def test_a_reach_is_not_merged_away(self):
        # above and below a bridge are genuinely different fishing, so they stay apart
        above = southwest.canonical_place('Cowlitz River Above the I-5 Br')
        below = southwest.canonical_place('Cowlitz River I-5 Br downstream')
        self.assertEqual(above, 'Cowlitz River (above I-5)')
        self.assertEqual(below, 'Cowlitz River (below I-5)')
        self.assertNotEqual(above, below)

    def test_an_alias_for_one_water(self):
        self.assertEqual(southwest.canonical_place('Little White Salmon (Drano Lake)'),
                         'Drano Lake')

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
        self.assertEqual(area9['taken'], 3479)

    def test_subtotal_rows_are_not_fisheries(self):
        self.assertEqual({r['area'] for r in self.rows if r['kind'] == 'fishery'},
                         {'Marine Area 5', 'Marine Area 9', 'Marine Area 11'})

    def test_an_area_can_run_two_seasons_at_once(self):
        # Area 11 runs two summer Chinook fisheries: one that opened 1 June and used
        # 54% of its quota, and one that opened 23 July at 15%. Reporting only the
        # first would show the wrong quota entirely.
        eleven = [r for r in self.rows
                  if r['area'] == 'Marine Area 11' and r['kind'] == 'fishery']
        self.assertEqual(len(eleven), 2)
        by_open = {r['opening']: r for r in eleven}
        self.assertEqual(by_open['June 1']['percent'], 0.54)
        self.assertEqual(by_open['July 23']['percent'], 0.15)

    def test_the_date_is_the_estimate_not_the_fetch(self):
        area5 = [r for r in self.rows if r['area'] == 'Marine Area 5'][0]
        self.assertEqual(area5['valid_through'], '2026-07-26')

    def test_numeric_dates_parse_too(self):
        self.assertEqual(quotas._valid_through('04/11/26'), '2026-04-11')

    def test_a_missing_percentage_is_worked_out(self):
        # WDFW leave the percentage off some rows; a quota table with no percentage
        # on it is the one thing this panel exists to show
        self.assertEqual(quotas._percent('', taken=99, limit=105), 0.9429)
        self.assertEqual(quotas._percent('80%', taken=99, limit=105), 0.8)
        self.assertEqual(quotas._percent('', taken='', limit=''), '')


OCEAN_QUOTA_PAGE = """
<h2>Westport</h2>
<table>
<tr><th>Stat Week</th><th>Dates</th><th>Number of anglers</th><th>Number of Chinook</th>
<th>Cumulative Chinook</th><th>Cumulative Coho</th><th>Percent of coho quota</th>
<th>Percent of Chinook guideline</th></tr>
<tr><td>29</td><td>Jul 13-19</td><td>3,000</td><td>2,000</td><td>9,000</td>
<td>5,000</td><td>13%</td><td>41%</td></tr>
<tr><td>30</td><td>Jul 20-26</td><td>3,555</td><td>2,347</td><td>11,494</td>
<td>7,634</td><td>20%</td><td>52%</td></tr>
</table>
"""

HALIBUT_QUOTA_PAGE = """
<h2>2026 Pacific halibut landings summary</h2>
<h3>Puget Sound - Quota 80,512 lbs</h3>
<table>
<tr><th>Week</th><th>Dates open</th><th>Weekly</th><th>Cumulative</th></tr>
<tr><th>Week</th><th>Dates open</th><th>Halibut (number)</th><th>Anglers (number)</th>
<th>Average weight (pounds)</th><th>Total Pounds</th><th>Pounds</th>
<th>Quota taken</th><th>Pounds remaining</th></tr>
<tr><td>27</td><td>Jun 29-30</td><td>62</td><td>472</td><td>15.7</td><td>978</td>
<td>46,792</td><td>58.1%</td><td>33,720</td></tr>
</table>
"""


class TestOtherQuotas(unittest.TestCase):
    """Chinook is not the only fishery run against a ceiling."""

    def test_ocean_tracks_chinook_and_coho_separately(self):
        rows = quotas.parse_ocean(OCEAN_QUOTA_PAGE, year=2026)
        by_species = {r['species']: r for r in rows}
        self.assertEqual(set(by_species), {'Chinook', 'Coho'})
        self.assertEqual(by_species['Chinook']['taken'], 11494)
        self.assertEqual(by_species['Chinook']['percent'], 0.52)
        self.assertEqual(by_species['Coho']['percent'], 0.2)

    def test_the_running_total_is_the_latest_week_not_the_first(self):
        rows = quotas.parse_ocean(OCEAN_QUOTA_PAGE, year=2026)
        self.assertEqual([r['taken'] for r in rows if r['species'] == 'Coho'], [7634])

    def test_an_unpublished_ceiling_is_implied_from_the_share_used(self):
        # 11,494 fish at 52% implies a guideline near 22,100
        rows = quotas.parse_ocean(OCEAN_QUOTA_PAGE, year=2026)
        chinook = [r for r in rows if r['species'] == 'Chinook'][0]
        self.assertEqual(chinook['limit'], 22100)

    def test_halibut_is_counted_in_pounds(self):
        rows = quotas.parse_halibut(HALIBUT_QUOTA_PAGE)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['unit'], 'pounds')
        self.assertEqual(row['limit'], 80512)     # published in the heading
        self.assertEqual(row['taken'], 46792)
        self.assertEqual(row['percent'], 0.581)


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
