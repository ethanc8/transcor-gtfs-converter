"""Convert raw maps.tds.ai route files into GTFS zips.

Raw model: each geo.json is a FeatureCollection with one Feature per *trip*; the
feature properties carry agency/route info plus ``trips`` = {trip_id, calendar,
stop_times[ {arrival_time, departure_time, stop{...}} ]}. Geometry is always empty,
so no shapes.txt is produced. Calendar exceptions are modelled by the source as
separate single-day calendars, so only calendar.txt is needed.

One feed per operator is produced, with the source's IDs unchanged.
"""
from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

from . import diagnostics
from .rawdata import read_manifest, route_file

ROUTE_TYPES = {"bus": 3, "rail": 2, "transit": 3}
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
AGENCY_URL = "https://maps.tds.ai/"
# Operators whose long "City, ST (pickup instructions...)" stop names are shortened; the original text
# goes into stop_desc. Currently only OurBus (see docs/data-notes.md).
SHORTEN_STOP_NAMES_FOR = {"ourbus"}
STOP_NAME_LIMIT = 60
CLAUSE_LIMIT = 40
FALLBACK_TZ = "America/New_York"


@dataclass
class AgencyData:
    agency_id: str
    name: str
    routes: dict = field(default_factory=dict)      # route_id -> (short, long, type)
    stops: dict = field(default_factory=dict)       # stop_id -> (name, lat, lon, tz|None, desc)
    services: dict = field(default_factory=dict)    # service_id -> (days, start, end)
    trips: list = field(default_factory=list)       # (route_id, service_id, trip_id, headsign, short_name, shape_id)
    shapes: dict = field(default_factory=dict)      # shape_id -> [(lat, lon), ...]
    stop_times: list = field(default_factory=list)  # (trip_id, arr, dep, stop_id, seq, timepoint)
    tz_votes: Counter = field(default_factory=Counter)
    stats: Counter = field(default_factory=Counter)
    timezone: str = FALLBACK_TZ
    tz_source: str = "inferred"  # "verified" if from agency_timezones.json


def _tz_config() -> dict:
    data = json.loads((Path(__file__).parent / "agency_timezones.json").read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def verified_timezones() -> dict[str, str]:
    """agency id -> verified agency_timezone (entries are "Zone" or {"timezone": ..., "clock": ...})."""
    return {k: v if isinstance(v, str) else v["timezone"] for k, v in _tz_config().items()}


def clock_rules() -> dict[str, str]:
    """agency id -> clock rule. "stop_local": each stop's raw time is that stop's own local time
    (aggregators like OurBus), so every stop is shifted individually into agency_timezone."""
    return {k: v["clock"] for k, v in _tz_config().items() if isinstance(v, dict) and v.get("clock")}


def time_corrections() -> dict[str, dict]:
    data = json.loads((Path(__file__).parent / "time_corrections.json").read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "agency"


def shorten_parenthetical(name: str) -> tuple[str, str]:
    """Shorten "City, ST (long free text)" to "City, ST (first clause)".

    Returns (stop_name, stop_desc); stop_desc is the original name when it was shortened, else "".
    The first clause ends at the first ". ", " - ", ", " or "; " (or a nested "("), and is cut at
    CLAUSE_LIMIT characters on a word boundary. Names up to STOP_NAME_LIMIT characters or without
    a parenthetical are left alone.
    """
    if len(name) <= STOP_NAME_LIMIT or " (" not in name:
        return name, ""
    prefix, inner = name.split(" (", 1)
    clause = re.split(r"\.\s|\s-\s|,\s|;\s|\(", inner.strip().rstrip(")").strip())[0].strip(" :;,-")
    if len(clause) > CLAUSE_LIMIT:
        clause = clause[:CLAUSE_LIMIT].rsplit(" ", 1)[0].strip(" :;,-")
    short = f"{prefix} ({clause})" if clause else prefix
    return (short, name) if short != name else (name, "")


def parse_time(s) -> int | None:
    if s is None or str(s).strip() == "":
        return None
    m = re.fullmatch(r"\s*(\d+):(\d\d)(?::(\d\d))?\s*", str(s))
    if not m:
        return None
    return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3] or 0)


def fmt_time(sec: int) -> str:
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def parse_ymd(s) -> str | None:
    try:
        return date.fromisoformat(str(s)[:10]).strftime("%Y%m%d")
    except (TypeError, ValueError):
        return None


def normalize_stop_times(raw_sts: list[dict], stats: Counter, shifts: list[int] | None = None):
    """Return [(arr, dep, stop_raw)] with times as seconds (None = untimed stop).

    ``shifts`` (seconds per stop) is added to timed stops first. Fixes: single-sided times are
    mirrored, midnight rollovers get +24h so times never decrease, departure is never before arrival.
    """
    out, prev = [], 0
    for i, st in enumerate(raw_sts):
        a, d = parse_time(st.get("arrival_time")), parse_time(st.get("departure_time"))
        a = d if a is None else a
        d = a if d is None else d
        if a is not None and shifts and shifts[i]:
            a, d = a + shifts[i], d + shifts[i]
            stats["time_corrected_stops"] += 1
        if a is not None:
            while a < prev:
                a += 86400
                d = d + 86400 if d is not None else d
                stats["rollover_fixed"] += 1
            if d < a:
                d = a
                stats["departure_before_arrival_fixed"] += 1
            prev = d
        out.append((a, d, st))
    return out


def shape_points(pts, order: str) -> list[tuple[float, float]]:
    """Normalise a coordinate list to [(lat, lon)].

    The route files carry the inline shape as [lon, lat] but the separate shape_*.json files as
    [lat, lon]; ``order`` is "lonlat" or "latlon". A pair that is out of range for its stated order
    is swapped, consecutive duplicates are dropped.
    """
    out: list[tuple[float, float]] = []
    for p in pts or []:
        try:
            a, b = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            continue
        lat, lon = (b, a) if order == "lonlat" else (a, b)
        if not -90 <= lat <= 90:
            lat, lon = lon, lat
        if -90 <= lat <= 90 and -180 <= lon <= 180 and (not out or out[-1] != (lat, lon)):
            out.append((lat, lon))
    return out


class TzLookup:
    def __init__(self):
        self._finder = None
        self._cache: dict[tuple[float, float], str | None] = {}

    def __call__(self, lat: float, lon: float) -> str | None:
        key = (round(lat, 3), round(lon, 3))
        if key not in self._cache:
            if self._finder is None:
                from timezonefinder import TimezoneFinder
                self._finder = TimezoneFinder()
            self._cache[key] = self._finder.timezone_at(lat=lat, lng=lon)
        return self._cache[key]


def load_agency(raw: Path, aid: str, entry: dict, tzl: TzLookup, correction: dict | None = None,
                agency_tz: str | None = None, clock_rule: str | None = None) -> AgencyData:
    ad = AgencyData(aid, entry.get("slug") or aid)
    seen_trips: set[str] = set()
    for r in entry.get("routes", []):
        f = route_file(raw, r["path"])
        if not f.exists():
            ad.stats["missing_route_file"] += 1
            continue
        try:
            fc = json.loads(f.read_text())
        except ValueError:
            ad.stats["bad_json"] += 1
            continue
        shape_for = _shape_resolver(ad, raw, fc)
        for feat in fc.get("features", []):
            _add_trip(ad, feat.get("properties") or {}, ROUTE_TYPES.get(r["type"], 3), seen_trips, tzl,
                      correction, agency_tz, clock_rule, shape_for)
    if ad.tz_votes:
        ad.timezone = ad.tz_votes.most_common(1)[0][0]
    return ad


def _shape_resolver(ad: AgencyData, raw: Path, fc: dict):
    """Return shape_for(shape_id, route_id) -> key in ad.shapes (or None) for one route file."""
    inline = fc.get("shape_coordinates") or {}
    urls: dict[str, str] = {}
    for x in fc.get("shape_urls") or []:
        if isinstance(x, dict):
            urls.update(x)

    cache: dict[str, list] = {}

    def load(sid: str):
        if sid in inline:
            return shape_points(inline[sid], "lonlat")
        if sid in urls:
            f = route_file(raw, urls[sid])
            if f.exists():
                try:
                    return shape_points(json.loads(f.read_text()).get("shape_coordinates"), "latlon")
                except ValueError:
                    ad.stats["bad_shape_json"] += 1
        return None

    def shape_for(sid: str, route_id: str):
        sid = str(sid or "")
        if sid not in cache:
            cache[sid] = load(sid)
        pts = cache[sid]
        if not pts or len(pts) < 2:
            ad.stats["trip_without_shape"] += 1
            return None
        key = sid
        if key in ad.shapes and ad.shapes[key] != pts:
            key = f"{sid}~{route_id}"   # same id, different geometry in another route file (not seen so far)
            ad.stats["shape_id_collision"] += 1
        ad.shapes.setdefault(key, pts)
        return key

    return shape_for


def trip_short_name(raw, p: dict) -> str:
    """The source's trip_short_name unless it merely repeats the route's long name (portal-style
    operators), in which case the route short name is used. Null stays empty. See docs/data-notes.md."""
    raw = str(raw).strip() if raw is not None else ""
    if not raw:
        return ""
    if raw == str(p.get("route_long_name") or "").strip():
        return str(p.get("route_short_name") or "").strip()
    return raw


def stop_timezone(lat: float, lon: float, label: str | None, tzl: TzLookup) -> str | None:
    """Timezone from coordinates (tzdb); the source label is only a fallback.

    Source labels are unreliable: Arizona stops are labelled America/Denver, Blythe CA is
    America/Tijuana, Indiana stops are often missing.
    """
    return tzl(lat, lon) or label


def _utc_offset_min(tz: str, d: date) -> int:
    return int(datetime(d.year, d.month, d.day, 12, tzinfo=ZoneInfo(tz)).utcoffset().total_seconds() // 60)


def _runs(start: str, end: str, days: str, fn):
    """Split a calendar into runs over which fn(date) is constant (only days the service runs).

    Returns [(start_ymd, end_ymd, fn_value)].
    """
    d, last = date.fromisoformat(f"{start[:4]}-{start[4:6]}-{start[6:]}"), date.fromisoformat(f"{end[:4]}-{end[4:6]}-{end[6:]}")
    runs = []
    while d <= last:
        if days[d.weekday()] == "1":
            v = fn(d)
            if runs and runs[-1][2] == v:
                runs[-1][1] = d
            else:
                runs.append([d, d, v])
        d += timedelta(days=1)
    return [(a.strftime("%Y%m%d"), b.strftime("%Y%m%d"), v) for a, b, v in runs]


def _add_trip(ad: AgencyData, p: dict, rtype: int, seen: set, tzl: TzLookup,
              correction: dict | None = None, agency_tz: str | None = None,
              clock_rule: str | None = None, shape_for=None) -> None:
    t = p.get("trips") or {}
    trip_id = str(t.get("trip_id") or "")
    route_id = str(p.get("route_id") or t.get("route_id") or "")
    if not trip_id or not route_id:
        ad.stats["trip_missing_ids"] += 1
        return
    if trip_id in seen:
        ad.stats["duplicate_trip_skipped"] += 1
        return
    cal = t.get("calendar") or {}
    days = "".join("1" if cal.get(d) in (True, 1, "1", "true") else "0" for d in DAYS)
    start, end = parse_ymd(cal.get("start_date")), parse_ymd(cal.get("end_date"))
    if not start or not end or end < start or days == "0" * 7:
        ad.stats["trip_bad_calendar"] += 1
        return
    raw_sts = t.get("stop_times") or []
    stops, sids = {}, []
    for st in raw_sts:
        s = st.get("stop") or {}
        sid = str(s.get("stop_id") or st.get("stop_id") or "")
        try:
            lat, lon = float(s["stop_lat"]), float(s["stop_lon"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            sid = ""
        if not sid:
            ad.stats["trip_bad_stop"] += 1
            return
        sids.append(sid)
        raw_name = str(s.get("stop_name") or sid)
        name, desc = shorten_parenthetical(raw_name) if ad.agency_id in SHORTEN_STOP_NAMES_FOR else (raw_name, "")
        stops[sid] = (name, lat, lon, stop_timezone(lat, lon, s.get("stop_timezone") or None, tzl), desc)
    def shift_fn(d: date) -> tuple[int, ...]:
        """Minutes added to each stop's raw time on service date d."""
        out = []
        for sid in sids:
            z, m = stops[sid][3], 0
            if clock_rule == "stop_local" and agency_tz and z:
                m += _utc_offset_min(agency_tz, d) - _utc_offset_min(z, d)
            if correction and agency_tz and z == correction["stop_timezone"]:
                m += correction["observed_offset_minutes"] - (_utc_offset_min(z, d) - _utc_offset_min(agency_tz, d))
            out.append(m)
        return tuple(out)

    needs_shift = bool(agency_tz) and (clock_rule == "stop_local" or bool(
        correction and any(stops[s][3] == correction["stop_timezone"] for s in sids)))
    variants = (_runs(start, end, days, shift_fn) if needs_shift else []) or [(start, end, None)]
    seen.add(trip_id)
    short_name = trip_short_name(t.get("trip_short_name"), p)
    shape_key = (shape_for(t.get("shape_id"), route_id) if shape_for else None) or ""
    ad.routes.setdefault(route_id, (str(p.get("route_short_name") or ""),
                                    str(p.get("route_long_name") or ""), rtype))
    for sid, v in stops.items():
        ad.stops.setdefault(sid, v)
    for n, (vstart, vend, minutes) in enumerate(variants, 1):
        shifts = [m * 60 for m in minutes] if minutes else None
        sts = normalize_stop_times(raw_sts, ad.stats, shifts)
        if len(sts) < 2 or sts[0][0] is None or sts[-1][0] is None:
            ad.stats["trip_bad_stop_times"] += 1
            return
        tid = trip_id if len(variants) == 1 else f"{trip_id}~{n}"
        service_id = f"{days}_{vstart}_{vend}"
        ad.services[service_id] = (days, vstart, vend)
        ad.trips.append((route_id, service_id, tid, ad.stops[sids[-1]][0], short_name, shape_key))
        for seq, ((a, d, _), sid) in enumerate(zip(sts, sids), 1):
            ad.stop_times.append((tid, fmt_time(a) if a is not None else "",
                                  fmt_time(d) if d is not None else "", sid, seq, 1 if a is not None else 0))
            if ad.stops[sid][3]:
                ad.tz_votes[ad.stops[sid][3]] += 1
        ad.stats["trips"] += 1
    if len(variants) > 1:
        ad.stats["trips_split_by_date_rules"] += 1


# --- writing ----------------------------------------------------------------

def _csv(header: list[str], rows) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue().encode()


def write_feed(path: Path, a: AgencyData, version: str) -> None:
    agencies = [a]
    pre = lambda a, x: x  # noqa: E731
    feed_tz = a.timezone
    services = dict(a.services)
    starts = [v[1] for v in services.values()]
    ends = [v[2] for v in services.values()]

    files = {
        "agency.txt": _csv(["agency_id", "agency_name", "agency_url", "agency_timezone"],
                           [(a.agency_id, a.name, AGENCY_URL, feed_tz) for a in agencies]),
        "routes.txt": _csv(["route_id", "agency_id", "route_short_name", "route_long_name", "route_type"],
                           [(pre(a, rid), a.agency_id, s, l, t)
                            for a in agencies for rid, (s, l, t) in a.routes.items()]),
        "stops.txt": _csv(["stop_id", "stop_name", "stop_desc", "stop_lat", "stop_lon", "stop_timezone"],
                          [(pre(a, sid), n, d, f"{la:.6f}", f"{lo:.6f}", z or "")
                           for a in agencies for sid, (n, la, lo, z, d) in a.stops.items()]),
        "calendar.txt": _csv(["service_id", *DAYS, "start_date", "end_date"],
                             [(sid, *d, s, e) for sid, (d, s, e) in sorted(services.items())]),
        "trips.txt": _csv(["route_id", "service_id", "trip_id", "trip_headsign", "trip_short_name", "shape_id"],
                          [(pre(a, r), s, pre(a, t), h, n, sh) for a in agencies for r, s, t, h, n, sh in a.trips]),
        "stop_times.txt": _csv(["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence",
                                "timepoint"],
                               [(pre(a, t), ar, de, pre(a, s), q, tp)
                                for a in agencies for t, ar, de, s, q, tp in a.stop_times]),
        "shapes.txt": _csv(["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"],
                           [(sid, f"{la:.6f}", f"{lo:.6f}", i) for a in agencies for sid in sorted({x[5] for x in a.trips if x[5]})
                            for i, (la, lo) in enumerate(a.shapes[sid], 1)]),
        "feed_info.txt": _csv(["feed_publisher_name", "feed_publisher_url", "feed_lang", "feed_start_date",
                               "feed_end_date", "feed_version"],
                              [("Converted from maps.tds.ai (TDS MMC Network Transportation Information)",
                                AGENCY_URL, "en", min(starts, default=""), max(ends, default=""), version)]),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)


def convert(raw: Path, out: Path, apply_corrections: bool = False) -> dict:
    manifest = read_manifest(raw)
    version = manifest.get("source_date") or ""
    tzl = TzLookup()
    agencies: list[AgencyData] = []
    verified = verified_timezones()
    corrections = time_corrections() if apply_corrections else {}
    rules = clock_rules()
    for aid, entry in sorted(manifest["agencies"].items()):
        ad = load_agency(raw, aid, entry, tzl, corrections.get(aid), verified.get(aid), rules.get(aid))
        ad.name = _agency_name(raw, entry) or ad.name
        if aid in verified:
            ad.timezone, ad.tz_source = verified[aid], "verified"
        if ad.stats["trips"] == 0:
            print(f"agency {aid} ({ad.name}): no usable trips; skipped {dict(ad.stats)}")
            continue
        agencies.append(ad)
    out.mkdir(parents=True, exist_ok=True)
    diag = {}
    for ad in agencies:
        write_feed(out / f"{ad.agency_id}_{slugify(ad.name)}.zip", ad, version)
        d = diagnostics.check_agency(ad)
        ad.stats["warn_fast_legs"], ad.stats["warn_asymmetric_legs"] = len(d["fast_legs"]), len(d["asymmetric_legs"])
        if d["fast_legs"] or d["asymmetric_legs"]:
            diag[ad.agency_id] = {"name": ad.name, **d}
    (out / "diagnostics.json").write_text(json.dumps(diag, indent=1))
    summary = {
        "source_date": version,
        "agencies": {a.agency_id: {"name": a.name, "timezone": a.timezone, "timezone_source": a.tz_source, **{k: v for k, v in a.stats.items()},
                                   "stops": len(a.stops), "routes": len(a.routes)} for a in agencies},
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def _agency_name(raw: Path, entry: dict) -> str | None:
    """agency_name from the first readable route file (the manifest only has a slug)."""
    for r in entry.get("routes", []):
        f = route_file(raw, r["path"])
        if f.exists():
            try:
                feats = json.loads(f.read_text()).get("features") or []
                if feats:
                    return feats[0]["properties"].get("agency_name")
            except (ValueError, KeyError):
                continue
    return None
