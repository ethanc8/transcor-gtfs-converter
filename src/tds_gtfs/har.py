"""Build a raw-data directory from a browser HAR capture (offline testing)."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.parse import urlparse

from .rawdata import decode_agency_routes, route_file, write_manifest


def _body(entry: dict) -> str | None:
    c = entry["response"]["content"]
    t = c.get("text")
    if not t:
        return None
    return base64.b64decode(t).decode() if c.get("encoding") == "base64" else t


def import_har(har_path: Path, out: Path) -> dict:
    har = json.loads(har_path.read_text())
    manifest = {"source_date": None, "fetched_at": None, "agencies": {}, "failures": []}
    n_files = 0
    for e in har["log"]["entries"]:
        req, url = e["request"], urlparse(e["request"]["url"])
        hdr = {h["name"].lower(): h["value"] for h in req["headers"]}
        manifest["source_date"] = manifest["source_date"] or hdr.get("source-date")
        body = _body(e)
        if body is None:
            continue
        if req["method"] == "POST" and url.path == "/get-agency-routes":
            aid = json.loads(req["postData"]["text"])["agency"]
            groups = decode_agency_routes(body)
            manifest["agencies"][aid] = {
                "slug": "", "routes": [{"path": p, "type": t} for t, ps in groups.items() for p in ps]}
        elif req["method"] == "GET" and url.path.startswith("/routes/") and url.path.endswith(".json"):
            dest = route_file(out, url.path[len("/routes/"):])
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(body)
            n_files += 1
    write_manifest(out, manifest)
    return {"agencies": len(manifest["agencies"]), "files": n_files}
