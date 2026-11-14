import json
import zipfile
from pathlib import Path

from tds_gtfs.convert import convert, fmt_time, normalize_stop_times, parse_time
from collections import Counter
from tds_gtfs.rawdata import decode_agency_routes, write_manifest


def stop(i, tz="America/New_York"):
    return {"stop_id": str(i), "stop_name": f"S{i}", "stop_lat": "40.0", "stop_lon": "-74.0", "stop_timezone": tz}


def feature(trip_id, times, days=(True,) * 7, route="R1"):
    names = "monday tuesday wednesday thursday friday saturday sunday".split()
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": []},
            "properties": {"agency_id": "A", "agency_name": "Agency A", "route_id": route,
                           "route_short_name": "1", "route_long_name": "One",
                           "trips": {"trip_id": trip_id, "route_id": route,
                                     "calendar": {**dict(zip(names, days)), "start_date": "2026-11-03",
                                                  "end_date": "2027-11-02"},
                                     "stop_times": [{"trip_id": trip_id, "stop_id": str(i), "arrival_time": a,
                                                     "departure_time": d, "stop": stop(i)}
                                                    for i, (a, d) in enumerate(times)]}}}


def make_raw(tmp: Path, features, extra=None, shape_files=None):
    p = "A/1/2/R1/geo.json"
    f = tmp / "routes" / p
    f.parent.mkdir(parents=True)
    for rel, body in (shape_files or {}).items():
        (tmp / "routes" / rel).write_text(json.dumps(body))
    f.write_text(json.dumps({"type": "FeatureCollection", "features": features, **(extra or {})}))
    write_manifest(tmp, {"source_date": "2026-11-01", "agencies": {"A": {"slug": "x", "routes": [{"path": p, "type": "bus"}]}}})


def test_time_helpers():
    assert parse_time("9:35:00") == 9 * 3600 + 35 * 60
    assert parse_time(None) is None
    assert fmt_time(parse_time("25:05:00")) == "25:05:00"


def test_normalize_rollover_and_missing():
    st = Counter()
    out = normalize_stop_times([{"arrival_time": "23:00:00", "departure_time": "23:10:00"},
                                {"arrival_time": None, "departure_time": None},
                                {"arrival_time": "00:30:00", "departure_time": "00:30:00"}], st)
    assert out[1][0] is None
    assert out[2][0] == 24 * 3600 + 30 * 60 and st["rollover_fixed"] == 1


def test_decode_double_encoded():
    body = json.dumps(json.dumps({"bus": ["a/b"], "rail": [], "transit": []}))
    assert decode_agency_routes(body)["bus"] == ["a/b"]


def test_end_to_end(tmp_path):
    raw = tmp_path / "raw"
    make_raw(raw, [feature("t1", [("9:00:00", "9:00:00"), (None, None), ("10:00:00", "10:00:00")]),
                   feature("bad", [("9:00:00", "9:00:00")])])
    out = tmp_path / "out"
    s = convert(raw, out)
    assert s["agencies"]["A"]["trips"] == 1
    with zipfile.ZipFile(out / "A_agency_a.zip") as z:
        assert {"agency.txt", "routes.txt", "stops.txt", "trips.txt", "stop_times.txt", "calendar.txt"} <= set(z.namelist())
        rows = z.read("stop_times.txt").decode().splitlines()
        assert rows[1].startswith("t1,09:00:00") and ",0" in rows[2]  # untimed middle stop
        assert "\n0," in z.read("stops.txt").decode()


def test_verified_timezone_override(tmp_path):
    from tds_gtfs.convert import verified_timezones
    assert verified_timezones()["203"] == "America/Chicago"  # Express Arrow: Central clock, mostly Mountain stops


def _stop(i, lat, lon, label):
    return {"stop_id": str(i), "stop_name": f"S{i}", "stop_lat": str(lat), "stop_lon": str(lon), "stop_timezone": label}


def _arizona_feature():
    f = feature("az", [("12:00:00", "12:00:00"), ("13:00:00", "13:00:00")])
    sts = f["properties"]["trips"]["stop_times"]
    sts[0]["stop"] = _stop(0, 35.53, -108.74, "America/Denver")   # Gallup NM
    sts[1]["stop"] = _stop(1, 33.45, -112.07, "America/Denver")   # Phoenix, mislabelled Denver by the source
    return f


def _times(out):
    with zipfile.ZipFile(out / "A_agency_a.zip") as z:
        return z.read("stop_times.txt").decode().splitlines()[1:], z.read("stops.txt").decode()


def test_stop_timezone_comes_from_coordinates(tmp_path):
    make_raw(tmp_path / "raw", [_arizona_feature()])
    convert(tmp_path / "raw", tmp_path / "out")
    _, stops = _times(tmp_path / "out")
    assert "America/Phoenix" in stops and "America/Denver" in stops


def test_time_correction_is_opt_in_and_seasonal(tmp_path, monkeypatch):
    import tds_gtfs.convert as c
    monkeypatch.setattr(c, "time_corrections", lambda: {"A": {"stop_timezone": "America/Phoenix", "observed_offset_minutes": 120}})
    monkeypatch.setattr(c, "verified_timezones", lambda: {"A": "America/Los_Angeles"})
    make_raw(tmp_path / "raw", [_arizona_feature()])   # runs 2026-11-03..2027-11-02, crossing DST start 2027-03-14
    convert(tmp_path / "raw", tmp_path / "off")
    convert(tmp_path / "raw", tmp_path / "on", apply_corrections=True)
    off, _ = _times(tmp_path / "off"); on, _ = _times(tmp_path / "on")
    assert [r.split(",")[0] for r in off] == ["az", "az"] and off[1].startswith("az,13:00:00")
    assert sorted({r.split(",")[0] for r in on}) == ["az~1", "az~2"]
    phx = {r.split(",")[0]: r.split(",")[1] for r in on if r.split(",")[4] == "2"}
    assert phx == {"az~1": "14:00:00", "az~2": "15:00:00"}   # +1h winter, +2h summer
    assert all(r.split(",")[1] == "12:00:00" for r in on if r.split(",")[4] == "1")  # New Mexico stop untouched


def test_diagnostics_flag_fast_and_asymmetric(tmp_path):
    from tds_gtfs.convert import AgencyData
    from tds_gtfs.diagnostics import check_agency
    ad = AgencyData("A", "A")
    ad.stops = {"a": ("A", 32.0, -108.0, None), "b": ("B", 32.0, -106.8, None)}  # ~70 miles apart
    ad.stop_times = [("t1", "10:00:00", "10:00:00", "a", 1, 1), ("t1", "10:10:00", "10:10:00", "b", 2, 1),
                     ("t2", "10:00:00", "10:00:00", "b", 1, 1), ("t2", "12:00:00", "12:00:00", "a", 2, 1)]
    d = check_agency(ad)
    assert len(d["fast_legs"]) == 1 and len(d["asymmetric_legs"]) == 1


def test_stop_local_clock_rule_shifts_each_stop_into_agency_timezone(tmp_path, monkeypatch):
    import tds_gtfs.convert as c
    monkeypatch.setattr(c, "clock_rules", lambda: {"A": "stop_local"})
    monkeypatch.setattr(c, "verified_timezones", lambda: {"A": "America/New_York"})
    f = feature("d", [("09:00:00", "09:00:00"), ("11:30:00", "11:30:00"), ("12:30:00", "12:30:00")])
    s = f["properties"]["trips"]["stop_times"]
    s[0]["stop"] = _stop(0, 39.85, -104.67, None)   # Denver, Mountain: +2h to Eastern
    s[1]["stop"] = _stop(1, 41.88, -87.63, None)    # Chicago, Central: +1h
    s[2]["stop"] = _stop(2, 40.71, -74.00, None)    # New York: unchanged
    make_raw(tmp_path / "raw", [f])
    convert(tmp_path / "raw", tmp_path / "out")
    rows, _ = _times(tmp_path / "out")
    assert [r.split(",")[1] for r in rows] == ["11:00:00", "12:30:00", "12:30:00"]


def test_shapes_and_trip_short_name(tmp_path):
    f1 = feature("t1", [("09:00:00", "09:00:00"), ("10:00:00", "10:00:00")])
    f1["properties"]["trips"]["shape_id"] = "inl"
    f1["properties"]["trips"]["trip_short_name"] = "19"
    f2 = feature("t2", [("11:00:00", "11:00:00"), ("12:00:00", "12:00:00")])
    f2["properties"]["trips"]["shape_id"] = "url"
    f3 = feature("t3", [("13:00:00", "13:00:00"), ("14:00:00", "14:00:00")])
    f3["properties"]["trips"]["shape_id"] = "missing"
    make_raw(tmp_path / "raw", [f1, f2, f3],
             extra={"shape_coordinates": {"inl": [[-74.0, 40.0], [-74.1, 40.1], [-74.1, 40.1]]},   # [lon, lat], duplicate point
                    "shape_urls": [{"url": "A/1/2/R1/shape_url.json"}]},
             shape_files={"A/1/2/R1/shape_url.json": {"shape_coordinates": [[41.0, -75.0], [41.1, -75.1]]}})  # [lat, lon]
    out = tmp_path / "out"
    convert(tmp_path / "raw", out)
    with zipfile.ZipFile(out / "A_agency_a.zip") as z:
        trips = {r.split(",")[2]: r.split(",") for r in z.read("trips.txt").decode().splitlines()[1:]}
        shapes = z.read("shapes.txt").decode().splitlines()
    assert trips["t1"][4:] == ["19", "inl"] and trips["t2"][4:] == ["", "url"] and trips["t3"][5] == ""
    assert shapes[0] == "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence"
    assert "inl,40.000000,-74.000000,1" in shapes and "inl,40.100000,-74.100000,2" in shapes and len([s for s in shapes if s.startswith("inl")]) == 2
    assert "url,41.000000,-75.000000,1" in shapes and not any(s.startswith("missing") for s in shapes)


def test_trip_short_name_rule():
    from tds_gtfs.convert import trip_short_name
    p = {"route_short_name": "PPB 8600P", "route_long_name": "New York -> Washington"}
    assert trip_short_name("New York -> Washington", p) == "PPB 8600P"   # portal-style: repeats the long name
    assert trip_short_name("105-3", p) == "105-3"                         # real GTFS-style value kept
    assert trip_short_name("19", {"route_short_name": "", "route_long_name": "Crescent"}) == "19"  # Amtrak
    assert trip_short_name(None, p) == ""                                  # null stays empty (FlixBus, Greyhound, OurBus)


def test_shorten_parenthetical():
    from tds_gtfs.convert import shorten_parenthetical as s
    assert s("Boston, MA (Allston Brighton)") == ("Boston, MA (Allston Brighton)", "")   # short names untouched
    long1 = "New York, NY (W 42nd Street and 9th Avenue, on the 42nd Street side of TD Bank (All drinks must have screw-on caps. Infants must have a car seat.))"
    assert s(long1) == ("New York, NY (W 42nd Street and 9th Avenue)", long1)
    long2 = "Boston, MA (Allston Brighton - Bus stop on Harvard Ave, next to 7 Eleven at 1227 Commonwealth Ave, Boston and more words"  # truncated, never closed
    assert s(long2)[0] == "Boston, MA (Allston Brighton)" and s(long2)[1] == long2
    long3 = "O'Hare International Airport - Terminal 5 Arrivals/Departures"          # long but no parenthetical
    assert s(long3) == (long3, "")
    long4 = "Providence, RI (On the street below the convention center: 99 W. Exchange St., Providence, RI 02903)"
    assert s(long4)[0] == "Providence, RI (On the street below the convention)"
    assert s("Worcester, MA (Union Station - Franklin Street and Harding Street, next to Union Station Garage (Same bus stop as WRTA routes))")[0] == "Worcester, MA (Union Station)"


def test_stop_desc_only_for_configured_operators(tmp_path, monkeypatch):
    import tds_gtfs.convert as c
    long_name = "Boston, MA (Dalton Street, Back Bay - Dalton and Belvidere Streets, East side of Dalton, across from Hilton)"
    f = feature("t", [("09:00:00", "09:00:00"), ("10:00:00", "10:00:00")])
    f["properties"]["trips"]["stop_times"][0]["stop"]["stop_name"] = long_name
    make_raw(tmp_path / "raw", [f])
    convert(tmp_path / "raw", tmp_path / "plain")
    monkeypatch.setattr(c, "SHORTEN_STOP_NAMES_FOR", {"A"})
    (tmp_path / "raw2").mkdir()
    make_raw(tmp_path / "raw2", [f])
    convert(tmp_path / "raw2", tmp_path / "short")
    with zipfile.ZipFile(tmp_path / "plain" / "A_agency_a.zip") as z:
        assert long_name in z.read("stops.txt").decode()
    with zipfile.ZipFile(tmp_path / "short" / "A_agency_a.zip") as z:
        rows = list(__import__("csv").DictReader(z.read("stops.txt").decode().splitlines()))
        trips = z.read("trips.txt").decode()
    r = [x for x in rows if x["stop_id"] == "0"][0]
    assert r["stop_name"] == "Boston, MA (Dalton Street)" and r["stop_desc"] == long_name
    assert [x for x in rows if x["stop_id"] == "1"][0]["stop_desc"] == ""
