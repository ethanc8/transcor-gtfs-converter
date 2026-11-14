from __future__ import annotations

import argparse
from pathlib import Path

from . import convert as convert_mod
from . import fetch as fetch_mod
from . import har as har_mod


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="tds_gtfs", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="download raw data from maps.tds.ai")
    f.add_argument("--out", type=Path, default=Path("data/raw"))
    f.add_argument("--source-date", help="YYYY-MM-DD snapshot (default: newest offered)")
    f.add_argument("--workers", type=int, default=6)
    f.add_argument("--max-failure-rate", type=float, default=0.01)
    f.add_argument("--agency", action="append", help="only this agency id (repeatable)")

    h = sub.add_parser("import-har", help="build a raw dir from a browser HAR capture")
    h.add_argument("har", type=Path)
    h.add_argument("--out", type=Path, default=Path("data/raw"))

    c = sub.add_parser("convert", help="convert a raw dir to GTFS zips")
    c.add_argument("--raw", type=Path, default=Path("data/raw"))
    c.add_argument("--out", type=Path, default=Path("data/gtfs"))
    c.add_argument("--apply-time-corrections", action="store_true",
                   help="apply the opt-in per-operator fixes in time_corrections.json (off by default)")

    q = sub.add_parser("queries", help="print booking-portal spot checks for operators with unverified clocks")
    q.add_argument("--raw", type=Path, default=Path("data/raw"))
    q.add_argument("--date", default="2026-11-16", help="service date to quote, YYYY-MM-DD")
    q.add_argument("--out", type=Path, default=Path("data/booking-queries.md"))

    a = p.parse_args(argv)
    if a.cmd == "fetch":
        return fetch_mod.fetch_all(a.out, a.source_date, a.workers, a.max_failure_rate, a.agency)
    if a.cmd == "import-har":
        print(har_mod.import_har(a.har, a.out))
        return 0
    if a.cmd == "queries":
        from . import queries
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(queries.render(a.raw, a.date))
        print(f"wrote {a.out}")
        return 0
    s = convert_mod.convert(a.raw, a.out, a.apply_time_corrections)
    print(f"{len(s['agencies'])} operators converted -> {a.out}")
    return 0
