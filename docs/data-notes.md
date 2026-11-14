# Data notes

What the non-timezone parts of the TDS data look like and how the converter treats them. Timezones are in
[timezones.md](timezones.md). Findings are from the 2026-11-01 snapshot.

## Operator kinds

The 54 "agencies" fall into three kinds, which differ in IDs, calendars and field conventions.

### Real-GTFS-style operators (8)

Their data is the official Coach USA GTFS feed (`https://api.prod.coachusa.com/gtfs`, hosted by Trillium
Solutions, which explains the `t_<n>_b_<block>_tn_<n>` trip IDs): same `agency_id`s and same trip IDs as TDS. The
feed also lists Coach USA Erie (1558) and Waukesha County Transit (2356, no trips), which TDS does not have.
Because it is an official feed, the TDS data for these 8 could be replaced by it directly (it also has
`direction_id`, `block_id`, and 7 more routes without trips). See [timezones.md](timezones.md) 5.6.

| `agency_id` | Operator | Trips | Calendar window starts | `trip_short_name` in the source |
|---|---|---|---|---|
| 1559 | Rockland Coaches | 119 | 2025 | `105-3`, `102-1`, `100-1` |
| 1566 | Community Coach | 39 | 2023 | `MTh63`, `MTh53`, `MTh33` |
| 1573 | Suburban Transit | 221 | 2025 | `MTh112-1`, `MTh115-1` |
| 1574 | ShortLine Hudson | 285 | 2024 | `156`, `155`, `411` |
| 1801 | Orange Westchester Link | 20 | 2021 | `341`, `345`, `343` |
| 562 | Van Galder (Coach USA) | 81 | 2026 | `RO1120`, `MJ1915` |
| 563 | Wisconsin Coach Lines | 68 | 2023 | `S4`, `S1`, `S3` |
| 664 | Newark Airport Express | 159 | 2025 | `303-2`, `302-2`, `301-6` |

Their `trip_short_name` is a real run/trip number, so it is kept. Their `route_short_name` is the brand (for
example `Rockland Coaches`) and the route number sits in `route_long_name` (`9/9A`), which looks swapped; it is
left as is for now.

### Booking-portal operators (about 42)

Numeric trip IDs (`1399935_1`, `444824`), route short names with an operator code (`PPB 8600P`, `BZ 0105B`,
`BHL 119`), calendars that are a rolling year starting around 2026-11. Verified timezone behaviour is in
[timezone-evidence.md](timezone-evidence.md). In the source, `trip_short_name` always equals
`route_long_name` ("New York (P.A.B.T.) -> Washington"), which is useless, so the converter replaces it (below).

### Aggregators / big brands

Amtrak (train numbers in `trip_short_name`), FlixBus, Greyhound (null `trip_short_name`, `route_short_name`
is just the brand) and OurBus (null, brand only; stop-local times, long pickup-instruction stop names).

## trip_short_name

Rule (`convert.trip_short_name`): keep the source value, except when it merely repeats the route's long name, in
which case use the route's short name. A null/empty value stays empty.

| Operator | Result |
|---|---|
| Real-GTFS-style operators, Amtrak | source value (`105-3`, `MTh112-1`, `19`, ...) |
| Portal operators | the route short name (`PPB 8600P`, `CJ 01:10-LGDV`, `Jefferson Lines 001`) |
| FlixBus, Greyhound, OurBus | empty (nothing useful exists; the route short name would just be the brand) |

Result for the 2026-11-01 snapshot: 4,895 of 6,981 trips have a `trip_short_name`; none repeats the route long
name; the 2,086 blanks are exactly FlixBus, Greyhound and OurBus.

## Operator codes

The source has no abbreviation field, only the numeric `agency_id`. For most portal operators the code is the
prefix of `route_short_name`:

| Code | Operator | Code | Operator |
|---|---|---|---|
| PPB | Peter Pan | LXUS / LXMX / LXIT / LXRC | Limousine Express / Limousine de Mexico / International Bus Lines / Rapid Connection |
| BZ | Peter Pan (BZ) | MXCH | Mexicoach |
| CJ | C&J | MFL / D2A2 / DAX | Michigan Flyer (3 brands) |
| ADT | Adirondack Trailways | SUTO | SHUTTO |
| FMT | Martz | LTA | Land to Air Express |
| SLE | Salt Lake Express | LAB | Lamers Connect |
| TBL | Trans-Bridge | BRS | BayRunner Shuttle |
| MRT | Miller | EZE | Expreso Lackawanna |
| BSB | Barons | HZL | Hazleton |
| BHL | Express Arrow | TAC | TAC Transportation |
| NWL | Northwestern Stage Lines | BLU | Yes Blue |
| OCI | MTR Western | VBB / VBBA | Virginia Breeze (Dillon's / Academy) |
| OWL | Orange Westchester Link | HCL | Sunway Charters |
| ANS | American Star Tours | WHT | Wheat Line |
| SHOR | Shore Connect | PRE | BeeLine Express |
| DL | Dungeness Line | DEA | Delta Bus Lines |
| IBU | All Aboard America | SBUS | Smile Bus |

Operators whose short names use the full name instead of a code: Indian Trails (the portal says `IT`), Jefferson
Lines (`JL`), Fullington Trailways, and the other real-GTFS-style operators. Amtrak has no short name;
FlixBus, Greyhound and OurBus use the brand. The `IT`/`JL` codes exist only on the portals.

## Shapes

`features[].geometry` is always empty, but each route file has a top-level `shape_coordinates` (shape id to
`[lon, lat]` points, one shape inline) and `shape_urls` (`[{shape_id: "<path>/shape_<id>.json"}]`, the other
shapes, with `[lat, lon]` points). `fetch` downloads the shape files; `convert` normalises the order and writes
`shapes.txt` plus `trips.shape_id`. Shape IDs are consistent within an operator (no conflicting geometry for the
same ID). 6,978 of 6,981 trips get a shape (one each for FlixBus, Greyhound and OurBus have none); 61 trips
(44 Amtrak, 17 OurBus) have an end stop more than 10 miles from their shape.

## Stop names

OurBus stop names embed pickup instructions: `City, ST (long free text)`. Of the 330 stops over 60 characters,
327 are OurBus; 243 have one clean parenthetical, 64 nested parentheses, 17 are truncated at about 255
characters (never closed), 4 have a stray `)`, and 2 (O'Hare Terminal 5 for Van Galder and Wisconsin Coach
Lines) are legitimately long.

For OurBus only (`convert.SHORTEN_STOP_NAMES_FOR`): when the name is longer than 60 characters and has a
parenthetical, keep the text before ` (` plus the **first clause** of the parenthetical, and put the original
name into `stop_desc`. The first clause ends at the first `. `, ` - `, `, `, `; ` or nested `(` and is cut at 40
characters on a word boundary:

| Original | `stop_name` |
|---|---|
| `New York, NY (W 42nd Street and 9th Avenue, on the 42nd Street side of TD Bank (All drinks must have...` | `New York, NY (W 42nd Street and 9th Avenue)` |
| `Boston, MA (Dalton Street, Back Bay - Dalton and Belvidere Streets, ...` | `Boston, MA (Dalton Street)` |
| `Providence, RI (On the street below the convention center: 99 W. Exchange St., ...)` | `Providence, RI (On the street below the convention)` |

Result: 327 of 351 OurBus stops shortened, 318 distinct names (prefix-only would leave 182), longest name 78
characters. Trip headsigns (the last stop's name) get the shortened name too. Other operators are untouched
(`stop_desc` empty).

Other stop-name issues seen but not fixed: Greyhound title-case artefacts (`Lee'S`, `59Th`), ALL-CAPS codes
(`(WNS)`), double spaces, FlixBus repeated city names (`Framingham Framingham, MA ...`).
