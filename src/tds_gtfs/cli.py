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

    r = sub.add_parser("release-index", help="write feeds.json and release notes for a GitHub release")
    r.add_argument("--gtfs", type=Path, default=Path("data/gtfs"))
    r.add_argument("--repo", default="ethanc8/transcor-gtfs-converter", help="owner/name, used in the download URLs")
    r.add_argument("--previous", type=Path, help="feeds.json of the previous release (for the added/removed notes)")
    r.add_argument("--previous-tag", default="", help="tag of the previous release")
    r.add_argument("--tag", required=True, help="release tag (the source date)")
    r.add_argument("--source-date", required=True)
    r.add_argument("--run-url", default="")
    r.add_argument("--notes-out", type=Path, default=Path("data/release-notes.md"))

    a = p.parse_args(argv)
    if a.cmd == "fetch":
        return fetch_mod.fetch_all(a.out, a.source_date, a.workers, a.max_failure_rate, a.agency)
    if a.cmd == "import-har":
        print(har_mod.import_har(a.har, a.out))
        return 0
    if a.cmd == "release-index":
        import json

        from . import release
        idx = release.build_index(a.gtfs, a.repo, a.tag, a.source_date)
        prev = json.loads(a.previous.read_text()) if a.previous and a.previous.exists() else None
        (a.gtfs / "feeds.json").write_text(json.dumps(idx, indent=1))
        dmfr = release.build_dmfr(idx)
        (a.gtfs / release.DMFR_FILE).write_text(json.dumps(dmfr, indent=2) + "\n")
        a.notes_out.parent.mkdir(parents=True, exist_ok=True)
        a.notes_out.write_text(release.build_notes(idx, a.run_url, prev, a.previous_tag))
        print(f"{len(idx['feeds'])} feeds indexed, {len(dmfr['feeds'])} in the DMFR")
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
