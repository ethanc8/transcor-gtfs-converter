"""Plausibility checks that catch bad stop times (e.g. the Limousine Express Arizona shift).

* fast legs: straight-line speed above MAX_MPH between consecutive timed stops (>= MIN_MILES apart)
* asymmetric legs: the same stop pair is much faster/slower in one direction than the other
  (a timezone error of +/-1h shows up as roughly 2h of asymmetry)
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict

MAX_MPH = 80.0
MIN_MILES = 15.0
ASYM_MIN_MINUTES = 45
ASYM_MIN_FRACTION = 0.35


def miles(a, b) -> float:
    p = math.pi / 180
    h = math.sin((b[0] - a[0]) * p / 2) ** 2 + math.cos(a[0] * p) * math.cos(b[0] * p) * math.sin((b[1] - a[1]) * p / 2) ** 2
    return 3959 * 2 * math.asin(math.sqrt(h))


def _sec(s: str) -> int:
    h, m, x = s.split(":")
    return int(h) * 3600 + int(m) * 60 + int(x)


def check_agency(ad) -> dict:
    """Return {"fast_legs": [...], "asymmetric_legs": [...]} for an AgencyData."""
    by_trip = defaultdict(list)
    for trip_id, arr, dep, sid, seq, _ in ad.stop_times:
        by_trip[trip_id].append((seq, arr, dep, sid))
    fast, dirs = {}, defaultdict(lambda: defaultdict(list))
    for trip_id, rows in by_trip.items():
        rows.sort()
        timed = [r for r in rows if r[1] and r[2]]
        for (_, _, dep, a), (_, arr, _, b) in zip(timed, timed[1:]):
            d = miles(ad.stops[a][1:3], ad.stops[b][1:3])
            mins = (_sec(arr) - _sec(dep)) / 60
            dirs[(a, b)][trip_id].append(mins)
            if d >= MIN_MILES and (mins <= 0 or d / (mins / 60) > MAX_MPH):
                fast.setdefault((a, b), (ad.stops[a][0], ad.stops[b][0], round(d), mins, trip_id))
    asym = []
    for (a, b), trips in dirs.items():
        if a >= b or (b, a) not in dirs:
            continue
        f = statistics.median(m for v in trips.values() for m in v)
        r = statistics.median(m for v in dirs[(b, a)].values() for m in v)
        if abs(f - r) >= ASYM_MIN_MINUTES and abs(f - r) >= ASYM_MIN_FRACTION * (f + r) / 2:
            asym.append((ad.stops[a][0], ad.stops[b][0], f, r))
    return {
        "fast_legs": [{"from": x[0], "to": x[1], "miles": x[2], "minutes": x[3], "example_trip": x[4]}
                      for x in fast.values()],
        "asymmetric_legs": [{"a": x[0], "b": x[1], "minutes_a_to_b": x[2], "minutes_b_to_a": x[3]}
                            for x in asym],
    }
