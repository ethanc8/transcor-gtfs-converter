"""Describe a built set of GTFS zips for publishing as a GitHub release.

Writes ``feeds.json`` (machine readable index with checksums and stable download URLs) and a markdown
release-notes file. Each feed is a separate release asset, so a consumer can paste one URL into a GTFS
ingester. ``releases/latest/download/<file>`` always points at the newest release.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

from .convert import slugify

DEFAULT_REPO = "ethanc8/transcor-gtfs-converter"
DMFR_FILE = "transcor.dmfr.json"
DMFR_SCHEMA = "https://dmfr.transit.land/json-schema/dmfr.schema-v0.6.0.json"
LATEST = "https://github.com/{repo}/releases/latest/download/{file}"
VERSIONED = "https://github.com/{repo}/releases/download/{tag}/{file}"


def external_status() -> dict[str, dict]:
    data = json.loads((Path(__file__).parent / "external_feeds.json").read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def onestop_words(name: str) -> str:
    """'Peter Pan Bus Lines' -> 'peter~pan~bus~lines' (the name part of a Onestop ID)."""
    return "~".join(w for w in slugify(name).split("_") if w)


def _feed_info(zip_path: Path) -> dict:
    with zipfile.ZipFile(zip_path) as z:
        return next(csv.DictReader(io.TextIOWrapper(z.open("feed_info.txt"), "utf-8")), {})


def build_index(gtfs_dir: Path, repo: str, tag: str, source_date: str) -> dict:
    summary = json.loads((gtfs_dir / "summary.json").read_text())["agencies"]
    external = external_status()
    feeds = []
    for aid, a in sorted(summary.items(), key=lambda kv: kv[1]["name"].lower()):
        file = f"{aid}_{slugify(a['name'])}.zip"
        path = gtfs_dir / file
        if not path.exists():
            raise FileNotFoundError(path)
        info = _feed_info(path)
        status = external.get(aid, {}).get("status", "none")
        words = onestop_words(a["name"])
        feeds.append({
            "agency_id": aid,
            "agency_name": a["name"],
            "file": file,
            "url_latest": LATEST.format(repo=repo, file=file),
            "url_versioned": VERSIONED.format(repo=repo, tag=tag, file=file),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size_bytes": path.stat().st_size,
            "trips": a.get("trips", 0),
            "routes": a.get("routes", 0),
            "stops": a.get("stops", 0),
            "feed_start_date": info.get("feed_start_date", ""),
            "feed_end_date": info.get("feed_end_date", ""),
            "agency_timezone": a["timezone"],
            "timezone_source": a["timezone_source"],
            "external_feed_status": status,
            "in_dmfr": status != "current",
            "dmfr_feed_id": f"f-tds~{words}" if status != "current" else None,
            "dmfr_operator_id": f"o-tds~{words}" if status != "current" else None,
        })
    return {"source_date": source_date, "release_tag": tag, "repository": repo, "feeds": feeds}


def build_dmfr(index: dict) -> dict:
    """Minimal DMFR: one feed + one operator per converted operator, with their own Onestop IDs.

    IDs use the prefixes f-tds~ / o-tds~ and are never linked to existing registry IDs (no supersedes_ids),
    so tools that merge connected components of the operator/feed graph keep these separate. Operators
    that already have a current GTFS feed elsewhere are omitted.
    """
    feeds = []
    for f in index["feeds"]:
        if not f["in_dmfr"]:
            continue
        feeds.append({
            "id": f["dmfr_feed_id"],
            "spec": "gtfs",
            "urls": {"static_current": f["url_latest"]},
            "operators": [{
                "onestop_id": f["dmfr_operator_id"],
                "name": f["agency_name"],
                "associated_feeds": [{"gtfs_agency_id": f["agency_id"]}],
            }],
        })
    return {"$schema": DMFR_SCHEMA, "feeds": feeds}


def diff_index(previous: dict | None, current: dict) -> dict:
    """Agencies added to / removed from the data since the previous release, plus renamed files (URL changes)."""
    if previous is None:
        return {"first": True, "added": [], "removed": [], "renamed": []}
    prev = {f["agency_id"]: f for f in previous["feeds"]}
    cur = {f["agency_id"]: f for f in current["feeds"]}
    return {
        "first": False,
        "added": [cur[k] for k in sorted(cur.keys() - prev.keys(), key=lambda k: cur[k]["agency_name"].lower())],
        "removed": [prev[k] for k in sorted(prev.keys() - cur.keys(), key=lambda k: prev[k]["agency_name"].lower())],
        "renamed": [(prev[k], cur[k]) for k in sorted(cur.keys() & prev.keys()) if prev[k]["file"] != cur[k]["file"]],
    }


def _changes_section(index: dict, previous: dict | None, previous_tag: str) -> list[str]:
    d = diff_index(previous, index)
    if d["first"]:
        return ["## Changes since the last release", "", "This is the first release.", ""]
    out = [f"## Changes since {previous_tag}", ""]
    if not (d["added"] or d["removed"] or d["renamed"]):
        return out + ["No operators were added or removed.", ""]
    for title, items in (("Added", d["added"]), ("Removed", d["removed"])):
        if items:
            out.append(f"**{title}:** " + ", ".join(f"{f['agency_name']} (`{f['agency_id']}`)" for f in items))
            out.append("")
    if d["renamed"]:
        out.append("**Download file renamed (the `latest` URL changed):** "
                   + ", ".join(f"{a['agency_name']}: `{a['file']}` to `{b['file']}`" for a, b in d["renamed"]))
        out.append("")
    return out


def build_notes(index: dict, run_url: str = "", previous: dict | None = None, previous_tag: str = "") -> str:
    repo, tag = index["repository"], index["release_tag"]
    rows = [
        "| Operator | Feed (stable URL) | Trips | Valid through | Agency timezone |",
        "|---|---|---:|---|---|",
    ]
    for f in index["feeds"]:
        end = f["feed_end_date"]
        end = f"{end[:4]}-{end[4:6]}-{end[6:]}" if len(end) == 8 else end
        tz = f["agency_timezone"] + ("" if f["timezone_source"] == "verified" else " (inferred)")
        other = "" if f["in_dmfr"] else " (also published elsewhere, not in the DMFR)"
        rows.append(f"| {f['agency_name']}{other} | [`{f['file']}`]({f['url_latest']}) | {f['trips']} | {end} | {tz} |")
    return "\n".join([
        f"# TDS GTFS, source data {index['source_date']}",
        "",
        "One GTFS zip per operator, converted from the data at https://maps.tds.ai (snapshot "
        f"`{index['source_date']}`). Each zip is a separate release asset: paste its URL into a GTFS ingester.",
        "",
        f"* Newest feed, always: `https://github.com/{repo}/releases/latest/download/<file>`",
        f"* This exact release: `https://github.com/{repo}/releases/download/{tag}/<file>`",
        "* `feeds.json` lists every feed with checksums, sizes and both URLs; `summary.json` and `diagnostics.json` "
        "hold conversion statistics and data-quality warnings.",
        "* \"(inferred)\" timezones are guesses from the stop locations; verified ones are documented in "
        "`docs/timezones.md`.",
        "* Amtrak, FlixBus/Greyhound and the Coach USA operators also have official feeds, see `docs/other-feeds.md`.",
        f"* `{DMFR_FILE}` ([DMFR](https://github.com/transitland/distributed-mobility-feed-registry) with one `f-tds~` "
        "feed and one `o-tds~` operator per feed, pointing at the `latest` URLs) lists "
        f"{sum(1 for f in index['feeds'] if f['in_dmfr'])} of the {len(index['feeds'])} feeds; the rest have a "
        "current feed published elsewhere (marked below).",
        *([f"", f"Built by {run_url}"] if run_url else []),
        "",
        *_changes_section(index, previous, previous_tag),
        *rows,
        "",
    ])
