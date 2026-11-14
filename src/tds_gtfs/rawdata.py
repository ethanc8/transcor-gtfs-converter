"""Layout of the raw-data directory shared by fetch, import-har and convert.

    <raw>/manifest.json            source date + per-agency route lists
    <raw>/routes/<a>/<b>/<c>/<route>/geo.json   verbatim route files
"""
from __future__ import annotations

import json
from pathlib import Path

MANIFEST = "manifest.json"
ROUTES_DIR = "routes"


def route_file(raw: Path, route_path: str) -> Path:
    """Local path for a route path such as '368/143/3673/15437/geo.json'."""
    parts = [p for p in route_path.split("/") if p]
    if any(p in (".", "..") for p in parts):
        raise ValueError(f"unsafe route path: {route_path!r}")
    return raw.joinpath(ROUTES_DIR, *parts)


def decode_agency_routes(body: str) -> dict[str, list[str]]:
    """Parse a get-agency-routes response.

    The server returns a JSON *string* containing JSON, e.g.
    "{\\"bus\\":[\\"317\\\\/143\\\\/...\\"],\\"rail\\":[],\\"transit\\":[]}".
    """
    data = json.loads(body)
    if isinstance(data, str):
        data = json.loads(data)
    return {k: list(v or []) for k, v in data.items() if isinstance(v, list)}


def write_manifest(raw: Path, manifest: dict) -> None:
    raw.mkdir(parents=True, exist_ok=True)
    (raw / MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True))


def read_manifest(raw: Path) -> dict:
    return json.loads((raw / MANIFEST).read_text())
