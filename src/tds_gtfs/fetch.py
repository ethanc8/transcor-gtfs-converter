"""Download the raw data from maps.tds.ai, mirroring what the web UI does.

Flow (as seen in the browser capture):
  GET  /                    -> session cookies, CSRF _token, list of source dates
  POST /create              -> selects source date + modes; server keeps it in the session
  GET  /map                 -> HTML listing every agency (checkbox value = agency id)
  POST /get-agency-routes   -> {"bus": [...paths], "rail": [...], "transit": [...]}
  GET  /routes/<path>       -> one geo.json per route (one feature per trip)
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .rawdata import decode_agency_routes, route_file, write_manifest

BASE = "https://maps.tds.ai"
UA = "transcor-gtfs-converter (GitHub Actions; +https://github.com/)"
MODES = ("bus", "rail")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def make_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=5, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=None, respect_retry_after_header=True)
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=32))
    s.headers["User-Agent"] = UA
    return s


def parse_home(page: str) -> tuple[str, list[str]]:
    token = re.search(r'name="_token"\s+value="([^"]+)"', page)
    if not token:
        raise RuntimeError("CSRF _token not found on home page (blocked by Cloudflare?)")
    sel = re.search(r'<select[^>]*name="source_date"[^>]*>(.*?)</select>', page, re.S)
    dates = re.findall(r'<option\s+value="([^"]+)"', sel.group(1)) if sel else []
    return token.group(1), dates


def parse_agencies(page: str) -> dict[str, str]:
    """agency id -> slug hint (e.g. '368' -> 'cj_bus_lines')."""
    out = {}
    for m in re.finditer(r'id="load_([^"]*)"[^>]*type="checkbox"[^>]*value="([^"]*)"', page):
        slug, aid = html.unescape(m.group(1)), html.unescape(m.group(2))
        out[aid] = slug[len(aid):] if slug.startswith(aid) else slug
    return out


class Client:
    def __init__(self, source_date: str | None):
        self.s = make_session()
        r = self.s.get(BASE + "/", timeout=60)
        r.raise_for_status()
        token, dates = parse_home(r.text)
        if not dates:
            raise RuntimeError("no source dates found on home page")
        self.source_date = source_date or dates[0]
        if self.source_date not in dates:
            raise RuntimeError(f"source date {self.source_date} not offered; have {dates[:5]}...")
        r = self.s.post(BASE + "/create", timeout=120,
                        data=[("_token", token), ("source_date", self.source_date)]
                        + [("types[]", m) for m in MODES])
        r.raise_for_status()
        self.agencies = parse_agencies(r.text)
        if not self.agencies:
            raise RuntimeError("agency list empty after /create")
        self.s.headers.update({"SOURCE-DATE": self.source_date, "Referer": BASE + "/map"})

    def agency_routes(self, agency: str) -> dict[str, list[str]]:
        xsrf = urllib.parse.unquote(self.s.cookies.get("XSRF-TOKEN", ""))
        r = self.s.post(BASE + "/get-agency-routes", json={"agency": agency}, timeout=120,
                        headers={"X-XSRF-TOKEN": xsrf, "X-Requested-With": "XMLHttpRequest",
                                 "Accept": "application/json, text/plain, */*"})
        r.raise_for_status()
        return decode_agency_routes(r.text)

    def route(self, path: str) -> bytes:
        r = self.s.get(f"{BASE}/routes/{path}", timeout=120)
        r.raise_for_status()
        return r.content


def _shape_paths(route_json: Path) -> list[str]:
    try:
        urls = json.loads(route_json.read_text()).get("shape_urls") or []
    except (OSError, ValueError):
        return []
    return [v for x in urls if isinstance(x, dict) for v in x.values()]


def fetch_all(out: Path, source_date: str | None, workers: int, max_failure_rate: float,
              only_agencies: list[str] | None = None) -> int:
    c = Client(source_date)
    log(f"source date {c.source_date}; {len(c.agencies)} agencies")
    manifest = {"source_date": c.source_date, "fetched_at": datetime.now(timezone.utc).isoformat(),
                "agencies": {}}
    todo: list[tuple[str, str]] = []
    for aid, slug in sorted(c.agencies.items()):
        if only_agencies and aid not in only_agencies:
            continue
        try:
            groups = c.agency_routes(aid)
        except Exception as e:  # noqa: BLE001
            log(f"  agency {aid}: route list failed: {e}")
            manifest["agencies"][aid] = {"slug": slug, "routes": [], "error": str(e)}
            continue
        routes = [{"path": p, "type": t} for t, paths in groups.items() for p in paths]
        manifest["agencies"][aid] = {"slug": slug, "routes": routes}
        todo += [(aid, r["path"]) for r in routes]
        time.sleep(0.05)
    log(f"{len(todo)} route files to fetch")

    failures = []

    def job(path: str):
        dest = route_file(out, path)
        if dest.exists() and dest.stat().st_size > 0:
            return
        body = c.route(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        tmp.write_bytes(body)
        tmp.replace(dest)

    def run(items):
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(job, p): (a, p) for a, p in items}
            for i, f in enumerate(as_completed(futs), 1):
                try:
                    f.result()
                except Exception as e:  # noqa: BLE001
                    failures.append((*futs[f], str(e)))
                if i % 250 == 0:
                    log(f"  {i}/{len(items)}")

    run(todo)
    # Each route file carries one shape inline ("shape_coordinates") and lists the others in
    # "shape_urls" ([{shape_id: "<agency>/.../shape_<id>.json"}]); fetch those too.
    shape_items = sorted({(a, sp) for a, rp in todo for sp in _shape_paths(route_file(out, rp))})
    log(f"{len(shape_items)} shape files to fetch")
    run(shape_items)
    todo += shape_items
    manifest["failures"] = [{"agency": a, "path": p, "error": e} for a, p, e in failures]
    write_manifest(out, manifest)
    rate = len(failures) / max(len(todo), 1)
    log(f"done: {len(todo) - len(failures)} ok, {len(failures)} failed ({rate:.1%})")
    return 0 if rate <= max_failure_rate else 1
