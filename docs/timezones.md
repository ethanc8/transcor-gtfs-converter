# Timezones in the maps.tds.ai data

This is the full story of how times and timezones work in the TDS data, what we verified, what the
converter does about it, and what is still open. Per-operator evidence is in
[timezone-evidence.md](timezone-evidence.md).

All findings are from the snapshot `SOURCE-DATE: 2026-11-01` (captured 2026-11-14) and booking-portal
lookups made in November 2026 (plus a few portal dates up to 2027-03).

## 1. The problem

GTFS `stop_times` are in the *agency timezone* (`agency_timezone`), and stops carry an informational
`stop_timezone`. The TDS data has:

* per-stop `stop_timezone` (often wrong or missing, see section 4),
* **no agency timezone anywhere** (no field in `get-agency-routes` or in any `geo.json` feature),
* times such as `"9:35:00"` or `"26:25:00"` with no zone information.

So the question for every operator is: *which clock are the raw times written in?*

## 2. What the web client does (it is misleading)

`https://maps.tds.ai/build/assets/gtfs-73426f01.js` does **no timezone conversion**:

* `Ie()` (time formatting) turns the raw time into 12-hour form, appends `(+N d)` for hours >= 24, and appends a
  label from the *stop's* `stop_timezone` (`New_York` to "Eastern", `Chicago` to "Central", `Denver` and
  `Phoenix` both to "Mountain", `Los_Angeles` and `Tijuana` to "Pacific"). Unmapped zones (for example
  `America/Indiana/Indianapolis`) get no label.
* `Zn()` (trip duration) subtracts the first arrival from the last arrival and adds the difference of a
  hard-coded "hours west of Eastern" table between the first and last stop's zone.

So the client behaves as if every raw time were *stop-local*. For most operators that is **not true** (section 3),
so the labels it shows (for example "04:55 AM Mountain") can be wrong by whole hours.

## 3. The raw-time model

### 3.1 One continuous clock per operator, not stop-local

If raw times were stop-local, legs that cross a timezone boundary would show jumps. Over all legs
(>= 40 miles, using tzdb zones from the coordinates), median straight-line speed:

| Legs | One continuous clock | Treated as stop-local |
|---|---|---|
| same-offset legs (7,311) | 64.4 mph | n/a |
| crossing, westbound (-1h), 173 legs | 61.8 mph | 44.0 mph |
| crossing, eastbound (+1h), 176 legs | 61.0 mph | 107.7 mph |

Only the one-clock reading gives plausible speeds in both directions. Symmetry checks agree (for example Express
Arrow Denver to Omaha is 10h40 raw and Omaha to Denver 10h45 raw). The test is inconclusive for Amtrak alone
(54 vs 52 mph), and it is violated by the OurBus Lafayette/St. Louis route (section 5.5).

### 3.2 The clock is a property of the operator

For booking-portal operators the clock is the operator's own ("home") timezone, even for routes that never
enter that zone. The canonical example is **Express Arrow**: its Denver to Buffalo, Buffalo to Denver and
Billings to Cheyenne routes are entirely in Mountain time, yet every raw time is exactly 1 hour later than the
operator's own website timetable, because the clock is Central. See the table in
[timezone-evidence.md](timezone-evidence.md#express-arrow-203).

Consequences:

* The clock cannot be inferred from the stops. Our original heuristic (most common stop zone) picked Mountain for
  Express Arrow and would have put every time one hour late.
* A single-zone operator is **not** automatically safe: its clock can be a different zone than its stops.

### 3.3 Exceptions to "one clock per operator"

* **FlixBus / Greyhound**: raw times are the official feed's UTC times converted to **America/New_York wall-clock
  time, date-aware** (UTC-5 in winter, UTC-4 in summer). The official feed has `agency_timezone = UTC`.
* **OurBus**: an aggregator of many small operators. Times are **stop-local** (the portal shows the raw numbers
  verbatim and computes durations from the stops' zone offsets). It needs a per-stop rule (section 5.5).
* **Amtrak**: TDS times are identical to the official Amtrak GTFS and to the catenary "fixed" feed. The official
  feed claims `America/New_York`, while the California Zephyr times form one continuous series (Emeryville 11:25 to
  Chicago 63:39) whose zone we could not determine (the leg-speed test is inconclusive). Unresolved; the plan is to keep using the official feeds for Amtrak, FlixBus and Greyhound.

### 3.4 Output convention

The converter keeps the raw times and writes the verified clock as `agency_timezone`, which is correct GTFS: a
consumer reads each time in the agency zone and converts to the stop's zone. Hence "Brush CO 12:00 with agency
tz America/Chicago" displays as 11:00 AM Mountain, matching the operator's website.

## 4. Stop timezones

`stop_timezone` in the source is unreliable:

| Source label | Reality |
|---|---|
| Arizona stops labelled `America/Denver` (Limousine Express, Amtrak, Salt Lake Express, one FlixBus stop) | `America/Phoenix`. Same offset in winter, different in summer. |
| Blythe CA labelled `America/Tijuana` | `America/Los_Angeles` |
| Arizona stops labelled `America/Hermosillo` (Greyhound/FlixBus) | equivalent offset to Phoenix, wrong name |
| Indiana stops often missing / `America/Indiana/Indianapolis` | fine, but the client shows no label |
| All OurBus stops | `null` |

The converter therefore **derives `stop_timezone` from the coordinates** with `timezonefinder` (tzdb) and uses the
source label only as a fallback.

Arizona and the Navajo Nation: tzdb (and `timezonefinder`) put the Navajo Nation (Window Rock, Tuba City,
Kayenta) in `America/Denver`, and the Hopi area and the rest of Arizona in `America/Phoenix`. The data contains
**no stops in the Navajo Nation** (51 Arizona-area stops checked), so the Navajo/Hopi DST split does not matter
here. Routes (for example Greyhound/Amtrak on I-40) do cross it, but GTFS only needs correct times at stops.

## 5. Per-operator status and special handling

25 of 54 operators are verified (config: `src/tds_gtfs/agency_timezones.json`). Evidence is in
[timezone-evidence.md](timezone-evidence.md).

| Clock | Operators |
|---|---|
| `America/New_York` | FlixBus, Greyhound, Barons Bus Lines, Peter Pan, Peter Pan (BZ), C&J, Adirondack Trailways; the 8 Coach USA / Trillium operators (ShortLine Hudson, Suburban Transit, Rockland Coaches, Community Coach, Orange Westchester Link, Newark Airport Express, **Van Galder and Wisconsin Coach Lines, which are Chicago-area**) |
| `America/Detroit` | Indian Trails |
| `America/Indiana/Indianapolis` | Miller Transportation |
| `America/Chicago` | Jefferson Lines, Express Arrow |
| `America/Denver` | Salt Lake Express |
| `America/Los_Angeles` | Northwestern Stage Lines, MTR Western, Limousine Express, Limousine de Mexico |
| `America/New_York` + `stop_local` | OurBus |

Operators in the "same family" appear to share a booking platform (numeric trip IDs, route codes such as `BHL`,
`NWL`, `LXUS`, `IT`, `PPB`, `CJ`). The 8 operators with `t_..._b_...` trip IDs are different: their data is the
official Coach USA GTFS feed (section 5.6).

Which operators cross timezone boundaries (by tzdb offsets on winter and summer dates): 14 of 54 (Amtrak,
Greyhound, FlixBus, Salt Lake Express, Limousine de Mexico, Jefferson, Limousine Express, Northwestern, Barons,
Miller, Indian Trails, OurBus, Express Arrow, MTR Western). Limousine de Mexico and OurBus cross in reality but
not in the source labels.

### 5.1 Express Arrow
See section 3.2. Verified on four routes against the operator's website.

### 5.2 Limousine Express: Arizona (known bad data)
Portal local time minus raw time: New Mexico stops +1h, California +0h, **Arizona stops +2h**, in both November and
(on a summer date) August. A correct Pacific clock needs +1h in winter and **+2h in summer**, because Arizona has no
DST (UTC-7 all year): Arizona is 1h ahead of Pacific time in winter and equal to it in summer. The raw data is
static (identical in the 2026-10-15 and 2026-11-01 snapshots), so it cannot be right in both seasons.

Raw evidence of the error: Lordsburg NM to Willcox AZ is 5-61 minutes raw for ~90 miles, and Phoenix to Blythe
(westbound) is 210-245 min raw but Blythe to Phoenix (eastbound) is 105-130 min for the same road; a
1-hour error of opposite sign in each direction explains the ~2h gap.

Fix (opt-in, off by default): `convert --apply-time-corrections` uses `src/tds_gtfs/time_corrections.json` to add
`observed_offset - (stop UTC offset - agency UTC offset)` minutes to Arizona stops: +60 in winter, +120 in
summer. Trips are split at the DST changes, so affected trips get ids `<trip>~1`, `<trip>~2` with separate
calendars (9 Limousine Express trips). Caveat: the portal's Arizona local times do not change with the season, so
the physical bus would have to run Lordsburg to Willcox in 1h05 in winter and 2h05 in summer, and Phoenix to Blythe
in 3h05 vs 2h05. We follow the portal.

### 5.3 Limousine de Mexico: Chihuahua stops (unresolved)
Raw = portal - 1h at every stop, including the Chihuahua-state stops (Villa Ahumada, Chihuahua, Delicias), so the
clock is Pacific and the Mexican stops look like they are shown on El Paso's clock. Chihuahua state is UTC-6
year-round, 1h ahead of El Paso in winter. The portal's own duration (8h20) is a plain difference of the displayed
times, i.e. it also treats Delicias as being in El Paso's zone. A Juarez to Chihuahua leg of 5h10 (as shown) versus
4h10 (if the stops are true local) is more typical at 4-4.5h, which hints the portal's Mexican times may be true
local. Unresolved; if confirmed it would be a second correction entry like Arizona.

### 5.4 Salt Lake Express, MTR Western, Miller, Barons, Indian Trails, Peter Pan, C&J, Adirondack
Straightforward: one clock, verified from portal comparisons (see evidence file).

### 5.5 OurBus
OurBus stores **stop-local** times. The portal (a) shows the raw numbers verbatim for Denver (Mountain), Ithaca
(Eastern) and Lafayette to Chesterfield (Eastern to Central) and (b) computes trip durations by subtracting the
stops' zone offsets (Lafayette 4:00 PM to Chesterfield 8:50 PM is "5h 50m"; the reverse 11:30 AM to 5:00 PM is
"4h 30m"). The converter uses `{"timezone": "America/New_York", "clock": "stop_local"}`: each stop is shifted
individually from its own zone into Eastern (Denver +2h, Central +1h).

Caveat: on the Lafayette/Bloomington to St. Louis route the stop-local reading implies impossible legs (Troy IL to
Terre Haute IN is 3h10 one way and 1h30 the other for ~145 miles; a single clock would give a plausible 2h10/2h30).
The operator (STL Crew Shuttle) probably typed the times on one clock. We mirror the portal because it is what
customers see. It affects 4 of 1,270 OurBus trips.

### 5.6 Coach USA / Trillium operators (official feed)
`https://api.prod.coachusa.com/gtfs` (Trillium Solutions, feed id `562_563_664_1558_1559_1566_1573_1574_1801_2356`,
version 2026-11-09) contains 10 agencies. Eight are TDS agencies with **identical `agency_id`s and identical trip
IDs** (933 of 989 shared trips have byte-identical stop times; the other 56 differ because the official feed is
newer than the 2026-11-01 snapshot): ShortLine Hudson, Suburban Transit, Rockland Coaches, Community Coach,
Orange Westchester Link, Newark Airport Express, Van Galder (Coach USA), Wisconsin Coach Lines. The other two,
Coach USA Erie (1558) and Waukesha County Transit (2356, routes 901/904/905), have no trips.

The feed declares `agency_timezone = America/New_York` for **every** agency, including the Chicago-area Van Galder
and Wisconsin Coach Lines (their stops are `America/Chicago`). The declaration is correct: Van Galder's
`trip_short_name` is `<2 letters><HHMM>` (for example `RO0520`, `MJ2115`, `MC1200`) and the first-stop departure
in the feed is exactly **60 minutes later** than that HHMM for all 81 trips (RO0520 leaves at 06:20 in the feed =
5:20 AM Central). So these two operators run on the same "operator clock" model as the portal operators, but with
an Eastern clock; the converter previously guessed Central for both (most common stop zone) and would have been
1 hour off. All 8 are now set to `America/New_York`. Wisconsin Coach Lines is covered by the feed declaration plus
the Van Galder evidence (its trip codes do not embed times).

## 6. What the converter does (summary)

| Step | Behaviour |
|---|---|
| Times | Passed through unchanged (zero-padded, `>= 24:00` kept). Single-sided times mirrored, rollovers fixed, untimed stops left blank with `timepoint=0`. |
| `agency_timezone` | From `agency_timezones.json` (verified), else the most common stop zone (reported as `"timezone_source": "inferred"` in `summary.json`). |
| `stop_timezone` | From coordinates via `timezonefinder`; source label only as fallback. |
| Clock rule `stop_local` | Shifts each stop from its own zone into `agency_timezone` (OurBus). |
| Corrections (opt-in) | `time_corrections.json` (Limousine Express, Arizona, seasonal, splits trips). |
| Diagnostics | `diagnostics.json`: legs implausibly fast (> 80 mph straight-line, >= 15 miles) or much faster/slower one way than the reverse (>= 45 min and >= 35%). Flags the Limousine Express Arizona legs; other operators have unrelated hits, so treat it as a review list. |
| Booking queries | `pixi run queries` writes `data/booking-queries.md` for operators that are not verified. |

Code: `src/tds_gtfs/convert.py` (rules and corrections), `diagnostics.py`, `queries.py`.

## 7. Unverified operators

Amtrak (1,835 trips) plus 28 others (719 trips): Martz Bus 105, Trans-Bridge 98, Fullington 83, Michigan Flyer
(D2A2) 53, Mexicoach 47, SHUTTO 34, Michigan Flyer (DAX) 32, Land to Air Express 30, Michigan Flyer 28, BayRunner
26, Hazleton 22, Expreso Lackawanna 22, International Bus Lines 21, TAC 20, Yes Blue 19, Virginia Breeze (Dillon's)
13, Sunway Charters 10, Wheat Line 8, Shore Connect 8, American Star Tours 8, Dungeness Line 6, BeeLine Express 6,
Rapid Connection 4, Lamers Connect 4, Delta Bus Lines 4, All Aboard America 4, Virginia Breeze (Academy) 2, Smile
Bus 2.

They use the guessed local zone. Reasons the risk is thought to be lower: every single-zone portal operator that
was verified (except Express Arrow) was local; Mexicoach, International Bus Lines and Rapid Connection stay within
the Los Angeles/Tijuana offset; the Pacific-only operators cannot be wrong unless their clock is another zone. But
Van Galder and Wisconsin Coach Lines show that an operator's clock can be another zone than its stops even in an
official feed, so Martz, Trans-Bridge, Fullington, and one trip each from Land to Air Express and Delta Bus Lines
remain the highest-value checks.

## 8. How to verify another operator

1. `pixi run queries` and pick the operator's section in `data/booking-queries.md` (booking portals search by
   stops and date, not by trip ID, so the file lists origin, destination, date and the expected local times
   under each candidate clock).
2. Search the operator's own booking site for that stop pair and date. Compare the first departure and the
   stops before and after any zone change.
3. Decide the clock:
   * portal = raw at every stop: the clock is the operator's local zone (single-zone operators);
   * portal differs by a constant per zone: the clock is the zone where the offset is 0; add the operator to
     `agency_timezones.json`;
   * portal = raw everywhere but durations subtract zone offsets: stop-local (`"clock": "stop_local"`);
   * offsets that do not follow zone rules (Arizona): data error, consider a `time_corrections.json` entry.
4. Check the portal's duration: it should equal the raw first-to-last span for a one-clock operator.

## 9. Open questions

* Limousine Express Arizona: is the portal's season-independent local time what the buses really run? Needs a
  second summer date and ideally the operator's own timetable.
* Limousine de Mexico: are the Chihuahua times in El Paso time or Chihuahua time?
* OurBus Lafayette/St. Louis route: which clock did the operator type (see 5.5)?
* Amtrak: clock rule for the official feed (not planned to use TDS for Amtrak).
* Salt Lake Express: the portal's SLE 8005 has stops the TDS trip lacks (Beaver Dam AZ) and a different first stop
  ("Bluff St Office" vs "Shop"), so only the Pacific stops were compared.
* The portal's LXUS 2003 has stops (Fontana, East Los Angeles) absent from the TDS trip.
