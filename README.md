# transcor-gtfs-converter

Converts the intercity bus/rail data at <https://maps.tds.ai> into GTFS.

```
pixi run fetch                       # -> data/raw/   (newest snapshot; --source-date YYYY-MM-DD, --agency ID)
pixi run convert                     # -> data/gtfs/<id>_<name>.zip (one feed per operator)
pixi run import-har some.har --out data/raw   # offline: build data/raw from a browser capture
pixi run test
```

GitHub Actions (`.github/workflows/fetch-and-convert.yml`) runs on the 1st and 15th of each month
(the site's snapshot cadence) and uploads `tds-gtfs-<date>` and `tds-raw-<date>` artifacts.

## Consuming the feeds

Each run publishes a GitHub release tagged with the source date (for example `2026-11-01`). Every operator is a
separate asset, so one URL goes straight into a GTFS ingester:

```
https://github.com/<owner>/<repo>/releases/latest/download/220_northwestern_stage_lines.zip   # newest, stable URL
https://github.com/<owner>/<repo>/releases/download/2026-11-01/220_northwestern_stage_lines.zip # that snapshot
```

`feeds.json` (also a release asset) lists every feed with its URLs, SHA-256, size, trip count, validity dates and
agency timezone. Zips are byte-for-byte reproducible, so a checksum only changes when the content does.
File names are `<agency_id>_<slug>.zip`. Scheduled runs (1st and 15th) skip a snapshot that already has a release;
a manual run (`workflow_dispatch`) re-uploads and refreshes it, and an older snapshot never becomes "latest".
Each release also has `transcor.dmfr.json`, a minimal [DMFR](https://github.com/transitland/distributed-mobility-feed-registry)
with one `f-tds~...` feed and one `o-tds~...` operator per feed (own IDs, no links to existing registry IDs), pointing at
the `latest` URLs, so a registry can be told to fetch every feed. Operators that already have a current feed published
elsewhere are left out (`src/tds_gtfs/external_feeds.json`, see `docs/other-feeds.md`); operators whose other feed is
stale are included. The release notes list operators added or removed since the previous release.
`pixi run release-index --tag <date> --source-date <date>` writes `feeds.json`, the DMFR and the notes locally
(`--repo` defaults to `ethanc8/transcor-gtfs-converter`). The registry-side clean-up that follows importing the DMFR
is written up in `random/atlas-changes.md`.

## Documentation

* [docs/timezones.md](docs/timezones.md): how times and timezones work in the TDS data and what the converter does
* [docs/data-notes.md](docs/data-notes.md): operator kinds, trip_short_name, operator codes, shapes, stop names
* [docs/other-feeds.md](docs/other-feeds.md): operators that also have other GTFS feeds (and TDS's own published feeds)
* [docs/timezone-evidence.md](docs/timezone-evidence.md): the portal and official-feed comparisons behind each verified operator

## Output

* **One feed per operator**, with the source's own IDs (no combined feed: stop IDs are reused by
  different operators for different places).
* Shapes: the `features[].geometry` is always empty, but every route file has a top-level `shape_coordinates`
  object (shape_id -> coordinates, one shape inline, as `[lon, lat]`) and `shape_urls` (the other shapes, as separate
  `shape_<id>.json` files with `[lat, lon]` coordinates). `fetch` downloads those files too and `convert` writes
  `shapes.txt` and `trips.shape_id` (6,978 of 6,981 trips have a shape).
* `trip_short_name`: the source value (Amtrak train numbers, run numbers of the 8 real-GTFS-style operators), or
  the route short name where the source just repeats the route long name (portal operators); empty for FlixBus,
  Greyhound and OurBus. OurBus's long pickup-instruction stop names are shortened (original text in `stop_desc`).
  See `docs/data-notes.md`.
* Calendar exceptions are single-day
  calendars in the source, so only `calendar.txt` is used. Untimed intermediate stops get blank times
  with `timepoint=0`. Rail routes (Amtrak) get `route_type=2`, everything else 3.
* `agency_url` is required by GTFS but not provided by the source; it is set to `https://maps.tds.ai/`.
* **Times and `agency_timezone`.** The source has no agency timezone. Its stop_times are one continuous
  clock for the whole operator (GTFS-style "agency time"), *not* stop-local time, and the maps.tds.ai client
  mislabels them with each stop's timezone. Verified against booking portals / official feeds
  (`src/tds_gtfs/agency_timezones.json`): FlixBus, Greyhound, Barons Bus Lines, Peter Pan, Peter Pan (BZ), C&J and Adirondack Trailways = America/New_York (Flix/Greyhound
  match the official UTC feed minus 5h/4h), Miller Transportation = America/Indiana/Indianapolis, Indian Trails = America/Detroit, Jefferson
  Lines and Express Arrow = America/Chicago (Express Arrow's all-Mountain routes are still +1h), Salt Lake
  Express = America/Denver, Northwestern Stage Lines, MTR Western, Limousine Express and Limousine de Mexico =
  America/Los_Angeles. OurBus is an aggregator whose raw times are each stop's own local time (the portal
  shows the raw numbers verbatim and computes durations by subtracting the stops' zone offsets: Lafayette IN
  4:00 PM -> Chesterfield MO 8:50 PM is "5h 50m"), so it uses `{"timezone": "America/New_York", "clock":
  "stop_local"}` and every stop is shifted individually into Eastern (Denver +2h, Central +1h). Caveat: on the
  Lafayette-St. Louis route the published local times imply physically impossible legs (Troy IL -> Terre Haute
  IN is 1h30 westbound-to-eastbound but 3h10 the other way); we mirror the published schedule anyway.
  Every other operator falls back to the most common stop timezone, reported as
  `"timezone_source": "inferred"` in `summary.json`.
* **Known bad data.** Limousine Express's Arizona stops are 2h earlier than the portal's local times in both
  winter and summer, which is 1h too early in winter and 2h too early in summer against a Pacific clock
  (Arizona has no DST). `convert --apply-time-corrections` (off by default; `time_corrections.json`) fixes this
  by splitting the affected trips at the DST changes (trip ids get a `~1`, `~2` suffix). Limousine de Mexico's
  Chihuahua-state stops are raw = portal - 1h like El Paso, i.e. the portal seems to show them in El Paso's
  clock although Chihuahua state is UTC-6; unresolved.
* `stop_timezone` is always derived from the stop's coordinates (`timezonefinder`/tzdb); the source's label is
  only a fallback because it is unreliable (Arizona stops are labelled `America/Denver`, Blythe CA
  `America/Tijuana`). tzdb puts the Navajo Nation in `America/Denver` and Arizona (incl. Hopi) in
  `America/Phoenix`; the data has no Navajo Nation stops.
* `convert` also writes `diagnostics.json`: legs that are implausibly fast (>80 mph straight line) or much
  slower/faster one way than the reverse. This is what flags the Limousine Express Arizona problem; some
  operators have unrelated hits.
* `pixi run queries` writes `data/booking-queries.md`: booking-portal spot checks for every operator whose clock
  is not yet verified.
