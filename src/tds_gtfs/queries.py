"""Generate booking-portal spot checks for operators whose clock timezone is not verified yet.

For a trip, the raw times are in an unknown operator clock Z. For each candidate Z (the real
timezones of the trip's stops) we print what the *local* time at each key stop would be if Z were
the clock. Compare with the portal's local times to see which candidate matches.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .convert import DAYS, TzLookup, parse_time, time_corrections, verified_timezones
from .rawdata import read_manifest, route_file

OFFICIAL = {"51", "fbuu", "geus"}  # we have official feeds; not checked via portals


def _valid_on(cal: dict, d: date) -> bool:
    return bool(cal.get(DAYS[d.weekday()])) and cal["start_date"] <= d.isoformat() <= cal["end_date"]


def _fmt(dt: datetime, base: date) -> str:
    n = (dt.date() - base).days
    s = dt.strftime("%I:%M %p").lstrip("0")
    return s + (f" (+{n}d)" if n else "")


def _local(raw_sec: int, clock: str, stop_tz: str, d: date) -> datetime:
    naive = datetime(d.year, d.month, d.day) + timedelta(seconds=raw_sec)
    return naive.replace(tzinfo=ZoneInfo(clock)).astimezone(ZoneInfo(stop_tz))


def _trips(raw: Path, entry: dict, tzl: TzLookup, d: date):
    for r in entry["routes"]:
        f = route_file(raw, r["path"])
        if not f.exists():
            continue
        for feat in json.loads(f.read_text())["features"]:
            p = feat["properties"]; t = p["trips"]
            if not _valid_on(t["calendar"], d):
                continue
            sts = t["stop_times"]
            if len(sts) < 2 or not (sts[0]["departure_time"] or sts[0]["arrival_time"]):
                continue
            secs = [parse_time(s["arrival_time"] or s["departure_time"]) for s in sts]
            if None in secs or max(b - a for a, b in zip(secs, secs[1:])) > 8 * 3600:
                continue  # skip trips with untimed stops or implausible gaps: poor spot checks
            tzs = [tzl(float(s["stop"]["stop_lat"]), float(s["stop"]["stop_lon"])) for s in sts]
            yield p, sts, tzs


def _off(z: str, d: date) -> float:
    return datetime(d.year, d.month, d.day, 12, tzinfo=ZoneInfo(z)).utcoffset().total_seconds()


def _table(p, sts, tzs, d: date) -> list[str]:
    cands, offs = [], set()  # candidate clocks, one per distinct UTC offset on that date (most common zone first)
    for z, _ in sorted(((z, tzs.count(z)) for z in set(tzs) if z), key=lambda x: -x[1]):
        if _off(z, d) not in offs:
            offs.add(_off(z, d)); cands.append(z)
    change = next((i for i in range(1, len(tzs)) if tzs[i] and tzs[i - 1] and _off(tzs[i], d) != _off(tzs[i - 1], d)), None)
    keep = {0, len(sts) - 1}
    if change is not None:
        keep |= {change - 1, change}
    hdr = "| stop | stop tz | raw arr/dep | " + " | ".join(f"local if clock = {c.split('/')[-1]}" for c in cands) + " |"
    rows = [hdr, "|" + "---|" * (3 + len(cands))]
    for i in sorted(keep):
        s = sts[i]; a, dp = s["arrival_time"], s["departure_time"]
        sec = parse_time(a or dp)
        cells = [_fmt(_local(sec, c, tzs[i], d), d) for c in cands]
        rows.append(f"| {s['stop']['stop_name'][:40]} | {tzs[i].split('/')[-1]} | {a[:5] if a else ''}/{dp[:5] if dp else ''} | " + " | ".join(cells) + " |")
    return rows


def render(raw: Path, day: str, summer_day: str = "2027-06-15") -> str:
    d = date.fromisoformat(day)
    m = read_manifest(raw); tzl = TzLookup(); verified = verified_timezones()
    out = [f"# Booking-portal spot checks (service date {day})\n",
           "Raw times are the converter's input. Each table shows what the portal's *local* time would be at the",
           "listed stops under each candidate operator clock; the matching column is the operator's clock.",
           "Pick a trip valid on the date, search the operator's own booking site (not an aggregator), and",
           "compare local times at the first stop, the stop before the zone change and the stop after it.\n"]
    singles = []
    for aid, e in sorted(m["agencies"].items()):
        if aid in verified or aid in OFFICIAL:
            continue
        crossing, longest = [], None
        for p, sts, tzs in _trips(raw, e, tzl, d):
            if None in tzs:
                continue
            offs = {_off(z, d) for z in tzs}
            if len(offs) > 1:
                crossing.append((len(sts), p["route_id"], p, sts, tzs))
            elif longest is None or len(sts) > longest[0]:
                longest = (len(sts), p, sts, tzs)
        name = next((x[2]["agency_name"] for x in crossing), None) or (longest[1]["agency_name"] if longest else aid)
        if crossing:
            out.append(f"## {name} (agency {aid}) - crosses timezones\n")
            seen = set()
            for _, rid, p, sts, tzs in sorted(crossing, key=lambda x: -x[0]):
                if rid in seen or len(seen) >= 2:
                    continue
                seen.add(rid)
                t = p["trips"]
                out.append(f"**{p['route_short_name']} - {p['route_long_name']}**, route_id `{p['route_id']}`, trip_id `{t['trip_id']}`, "
                           f"runs {t['calendar']['start_date']}..{t['calendar']['end_date']}\n")
                out += _table(p, sts, tzs, d) + [""]
        elif longest:
            singles.append((aid, longest))
    if singles:
        out += ["## Operators that never cross a timezone (clock currently guessed = local zone)\n",
                "Check only the first departure and last arrival: if the portal shows the same times, the guess is right;",
                "if it differs by whole hours, the operator's clock is another zone (as with Express Arrow).\n",
                "| operator | route / trip_id | first stop raw dep | last stop raw arr | stop zone |", "|---|---|---|---|---|"]
        for aid, (_, p, sts, tzs) in singles:
            out.append(f"| {p['agency_name']} ({aid}) | {p['route_short_name']} {p['route_long_name'][:40]} / `{p['trips']['trip_id']}` | "
                       f"{sts[0]['stop']['stop_name'][:25]} {(sts[0]['departure_time'] or sts[0]['arrival_time'])[:5]} | "
                       f"{sts[-1]['stop']['stop_name'][:25]} {(sts[-1]['arrival_time'] or sts[-1]['departure_time'])[:5]} | {tzs[0].split('/')[-1]} |")
    # Arizona summer check for Limousine Express
    if "402" in m["agencies"]:
        sd = date.fromisoformat(summer_day)
        for p, sts, tzs in _trips(raw, m["agencies"]["402"], tzl, sd):
            if p["route_short_name"] == "LXUS 2001":
                out += [f"\n## Arizona summer check: Limousine Express LXUS 2001 on {summer_day}\n",
                        "Read the portal's local time at these Arizona stops and subtract the raw time. In summer Arizona (no DST)",
                        "matches Pacific time, so the correction needed equals that difference:",
                        "* **+2h** (same as November): raw is 2h too early; the winter correction (+1h) is then wrong, summer needs +2h",
                        "* **+1h**: raw is 1h too early in summer too; a fixed +1h correction works year-round",
                        "* **+0h**: raw is already right in summer; the +1h correction must apply to winter service dates only\n",
                        "| stop | raw arr | local if error persists (+2h) | local if clean Pacific clock (+0h) |", "|---|---|---|---|"]
                for s, z in zip(sts, tzs):
                    if z == "America/Phoenix":
                        h = parse_time(s["arrival_time"])
                        mk = lambda off: datetime(sd.year, sd.month, sd.day) + timedelta(seconds=h + off * 3600)
                        out.append(f"| {s['stop']['stop_name'][:30]} | {s['arrival_time'][:5]} | {_fmt(mk(2), sd)} | {_fmt(mk(0), sd)} |")
                break
    return "\n".join(out) + "\n"
