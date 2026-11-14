# Timezone evidence by operator

Raw times are the TDS `stop_times` (snapshot 2026-11-01). "Portal" means the operator's booking site, which
states "all times displayed are in local time" and computes durations from real elapsed time (OurBus is the
exception, see below). "Local minus raw" is portal local time at a stop minus the raw time (modulo 24h), in
hours. Dates are service dates in November 2026 unless noted. All November dates are standard time.

Notation: "raw +1h" means the raw time is 1 hour *later* than the portal's local time at that stop; "raw -1h" means
1 hour earlier. A raw offset of 0 at stops in zone X, and raw +1h / -1h in the zones one hour west / east of X,
means the raw clock is zone X (a clock in zone X runs 1 hour ahead of the zone to its west).

## Verified operators

### FlixBus (`fbuu`) and Greyhound (`geus`): America/New_York
* Official feed `gtfs.gis.flix.tech/gtfs_generic_us.zip` has `agency_timezone = UTC` and UTC times, with
  UUID-style trip IDs and stop IDs.
* TDS trips (816 features) were matched to official trips by first/last stop coordinates (rounded to 0.01 degrees)
  and the sequence of minute offsets from the first departure. Raw time-of-day of the first stop minus official
  UTC time-of-day has two dominant values: **-5.0h** (3,584 matches) and **-4.0h** (1,783 matches), i.e. America/New_York
  in winter/summer. The remaining matches are scattered noise from ambiguous matching.
* Portal (FlixBus Chicago to New York, Mon 16 Nov, 07:15 PM departure): Chicago-area stops are raw +1h (20:15
  raw vs 7:15 PM); everything from Lafayette IN on is raw = local. Duration 20h45 = raw span.

### Express Arrow (203): America/Chicago
The operator's own website timetables (local times) versus TDS raw, for routes that are entirely Mountain time
as well as ones that cross:

| Route | Zones | Local vs raw |
|---|---|---|
| Denver to Omaha (BHL 120) | MT to CT | Denver RTD dep 9:25 vs 10:25, Brush 11:00 vs 12:00, Ogallala (MT) 1:00 PM vs 14:00: raw **+1h**. North Platte (CT) 2:50 PM vs 14:50 onwards to Omaha 8:40 PM vs 20:40: raw **+0h** |
| Denver to Buffalo, WY (BHL 121) | all MT | Greeley 2:30 vs 15:30, Cheyenne 3:40 vs 16:40, Wheatland 5:00 vs 18:00, Casper 7:20 vs 20:20, Buffalo 9:25 PM vs 22:25: all **+1h** |
| Buffalo to Denver (BHL 122) | all MT | Buffalo 7:20 vs 08:20, Casper 9:00 vs 10:00, Cheyenne 12:45 vs 13:45, Denver 3:15 vs 16:15: all **+1h** |
| Billings to Cheyenne (BHL 124) | all MT | Billings 4:45 vs 05:45, Cody 6:40 dep vs 07:40, Casper 11:45 vs 12:45, Cheyenne 2:45 PM vs 15:45: all **+1h** |

The Omaha to Denver direction (BHL 119) is 20 minutes earlier in TDS than on the website for the same stop, so
it is a different timetable revision and was not used.

### Jefferson Lines (202): America/Chicago
Portal JL 701 Minneapolis to Billings: identical to raw through Vivian SD (Central). From Kadoka (Mountain) on,
raw is **+1h** (Kadoka 4:05 PM portal vs raw 17:05; Billings arrival 12:25 AM portal vs 25:25 raw). Raw span 18h40 is continuous.

### Northwestern Stage Lines (220): America/Los_Angeles
Portal NWL 720 Boise to Portland (Mon 16 Nov): Boise 8:15 AM local vs raw 07:15; Nampa 8:45 vs 07:45; Ontario
9:30 vs 08:30 (all raw -1h, Mountain stops), Baker City 9:45 AM onwards equal raw (Pacific). Duration 10h15 = raw span.

### Limousine Express (402): America/Los_Angeles, with Arizona error
Portal LXUS 2001 (and 2002/2003) vs raw, Nov 2026, local minus raw:

| Stops | Zone | Local minus raw |
|---|---|---|
| El Paso, Las Cruces, Deming, Lordsburg | MT | +1.00 |
| Willcox, Tucson, Eloy, Phoenix | AZ | **+2.00** (expected +1.00) |
| Blythe through Los Angeles | PT | 0.00 |

The same three trips agreed to the minute. On the portal's 08/10 query (a summer date) LXUS 2001 showed
identical local times (Willcox 2:45 PM, Phoenix 5:35 PM, Blythe 7:40 PM, 14h40 duration), so portal minus raw is
still +2h for Arizona in summer, where +0h would be correct for a Pacific clock. The raw times are identical in
the 2026-10-15 and 2026-11-01 snapshots (not recomputed by date). Handling is in `docs/timezones.md` section 5.2.
Portal LXUS 2003 has extra stops (Fontana, East Los Angeles) that the TDS trip lacks, so the tail of that trip
was not compared.

### Salt Lake Express (303): America/Denver
Portal SLE 8005 (Mon 16 Nov): Mesquite (Virgin River) NV arrive 3:35 AM / depart 3:45 AM vs raw 04:45; CasaBlanca
3:46 AM vs 04:46; Las Vegas Airport 5:10 AM vs 06:10: Pacific stops are raw **+1h**, so the clock is Mountain.
Duration 2h10 = 4:00 AM MT to 5:10 AM PT. The TDS trip starts at "Saint George (Shop)" 03:35 while the portal's
first stop is "Bluff St Office" 4:00 AM, and TDS lacks Beaver Dam AZ, so the St. George stops were not compared.

### MTR Western (324): America/Los_Angeles
Portal OCI 8409 Bend to Juntura (Mon 16 Nov): Bend 3:00 PM, Brothers 3:50, Burns 5:20, Drewsey 6:15 PM equal raw
(Pacific); Juntura (Mountain) 7:30 PM vs raw 18:30 is **raw -1h**. Duration 3h30.

### Limousine de Mexico (403): America/Los_Angeles (Chihuahua open)
Portal LXMX 54201 (Sat 14 Nov): El Paso 11:30 AM, Ciudad Juarez 1:00 PM, Villa Ahumada 2:45 PM, Chihuahua 6:30 PM,
Delicias 7:50 PM vs raw 10:30, 12:00, 13:45, ..., 18:50: **raw -1h at every stop**, including the Chihuahua-state
stops. See `docs/timezones.md` 5.3.

### Miller Transportation (205): America/Indiana/Indianapolis
Portal MRT 366 Evansville to Indianapolis (Mon 16 Nov): Evansville 1:30 PM and Dale 2:25 PM (Central) are raw
+1h (14:30, 15:25); Paoli 4:30 PM and Indianapolis 7:00 PM (Eastern) equal raw. Duration 4h30 = raw span.

### Barons Bus Lines (302): America/New_York
Portal BSB 22 Chicago to Columbus (Mon 16 Nov): Chicago 6:05 AM and Rolling Prairie 7:25 AM are raw +1h (07:05,
08:25); South Bend 8:55 AM equals raw. The portal's Columbus stop (2:35 PM) differs from TDS's "Columbus (E Mound
St)" 14:50, but both are Eastern and consistent with raw = Eastern.

### Indian Trails (224): America/Detroit
Portal IT 58 Milwaukee to Escanaba (Mon 16 Nov): Milwaukee 7:45 PM, Sheboygan 8:45, Green Bay 10:05 PM, Cedar River
12:25 AM are raw +1h (Central stops); Escanaba 2:00 AM (Eastern) equals raw 26:00. IT 59 (reverse, Escanaba 4:05 AM
= raw, Cedar River 3:40 AM and Milwaukee 8:20 AM raw +1h), IT 60 Ironwood to Escanaba (9:30 PM vs 22:30, raw +1h; arrive
2:20 AM = raw) and IT 21 Detroit to Grand Rapids (equal raw) agree. Durations (5h15, 5h15, 3h50, 4h25) equal the
raw spans.

### Peter Pan (221), Peter Pan (BZ) (345), C&J (368), Adirondack Trailways (223): America/New_York
All stops are Eastern, and every portal time equals raw.

* Peter Pan PPB 8600P New York to Washington, Tue 17 Nov: 12:00 AM, 1:50, 3:35, 4:05, 5:15 AM (raw 00:00, 01:50, 03:35,
  04:05, 05:15). PPB 8531P Philadelphia to New York: 12:30 PM to 2:30 PM.
* Peter Pan (BZ) BZ 0105B + 0213B Boston Logan to New York with a Providence transfer: 9:00 AM, 9:30, 10:30, then
  11:00, 1:05 PM, 3:00 PM (raw 09:00, 09:30, 10:30, 11:00, 13:05, 15:00).
* C&J NYDV-12:45 New York to Dover: 12:45 PM, 6:35 PM, 6:55 PM, 7:10 PM, 6h25.
* Adirondack N813-D Toronto to New York (overnight): 8:00 PM, Niagara Falls 9:40, Buffalo 10:55, Batavia 12:05 AM,
  Rochester 12:50, Syracuse 2:25, Newark 6:40, New York 7:10 AM, 11h10 (raw 20:00 to 31:10).

### OurBus (`ourbus`): America/New_York, `stop_local`
Portal searches (Nov 2026) and raw:

| Search | Portal | Raw (trip) |
|---|---|---|
| Denver Airport to Breckenridge, Mon 23 Nov | 8:00 AM, Frisco 10:30, 11:00 AM | 08:00, 10:30, 11:00 (377596) |
| Breckenridge to Denver Airport, Mon 23 Nov | 2:50 AM, 3:15, 5:55 AM | 02:50, 03:15, 05:55 (378684) |
| Ithaca to Syracuse Airport, Mon 23 Nov | 2:20 AM, 2:35, 4:05 AM | 02:20, 02:35, 04:05 (362765) |
| Lafayette to Chesterfield, Fri 12 Mar 2027 (also available 2026-11-20, -24, -12-19) | 4:00 PM, Terre Haute 5:30, Troy 7:40, Richmond Heights 8:20, 8:50 PM; trip summary **5h 50m** | 16:00, 17:30, 19:40, 20:20, 20:50 |
| Chesterfield to Lafayette, Sun 29 Nov (also 2027-01-10, -03-21) | 11:30 AM, Richmond Heights 12:00, Troy 12:30, Terre Haute 3:00 PM, 5:00 PM; summary **4h 30m** | (second trip 2:00 PM to 7:30 PM, also 4h30) |

The OurBus portal shows the raw numbers verbatim (no "local time" statement) and its durations are the naive
difference adjusted by the stops' zone offsets (+1h forward, -1h reverse), i.e. it treats each number as that
stop's local time. That is the basis of `stop_local`. The raw legs of this route are physically implausible when
read as stop-local (Troy to Terre Haute 3h10 vs 1h30) but plausible as one clock (2h10/2h30). The TDS snapshot
has this route only on 2027-01-10 and 2027-03-12, so the portal's November variant (without Terre Haute on the
Fri/Tue listing) is not in the snapshot; the shared stops matched.

## Official-feed comparisons (not portal)

### Coach USA / Trillium feed (`https://api.prod.coachusa.com/gtfs`): the 8 `t_..._b_...` operators
See `docs/timezones.md` 5.6. The feed (version 2026-11-09, publisher Trillium Solutions) has the same agency IDs and
trip IDs as TDS for ShortLine Hudson (285/285 trips shared), Suburban Transit (221/221), Rockland Coaches
(116 of 122), Community Coach (39/39), Orange Westchester Link (20/20), Newark Airport Express (159/159), Van
Galder (81/81) and Wisconsin Coach Lines (68 of 70), and declares `America/New_York` for all of them. For Van
Galder, first-stop departure minus the HHMM in `trip_short_name` is +60 minutes for all 81 trips, confirming that
the Eastern declaration is the real clock for a Central-zone operator.

### Amtrak
Official `content.amtrak.com/content/gtfs/GTFS.zip` (`agency_timezone = America/New_York`) and the catenary
`amtrak-gtfs-fixed.zip` both contain the same California Zephyr trip 310066 times as TDS (Emeryville 11:25 PT,
Salt Lake City 28:55, Denver 44:27, Chicago 63:39). The catenary fixer's README says it changes stops, routes and
shapes and only logs trips departing after midnight in non-Eastern zones; it does not shift times. The elapsed
time 52h14 is continuous. Whether those times are Eastern, Pacific or something else was not determined.

## Reproducing the numbers

* Raw data: `pixi run fetch` (or `import-har` from `random/*.har` for the Nov 2026 capture).
* Portal spot-check sheets: `pixi run queries` writes `data/booking-queries.md`.
* Leg plausibility and asymmetry: `data/gtfs/diagnostics.json` after `pixi run convert`.
* The leg-speed test (section 3.1 of `timezones.md`) and the crossing-operator count were one-off scripts
  (haversine distance x 1.25, tzdb zones from `timezonefinder`, UTC offsets on 2026-11-10); see the thresholds
  in `src/tds_gtfs/diagnostics.py` for the reusable version.
