"""Quality pass: input-validation guards, branch coverage for fetch/catalog/stats,
and the geopandas paths."""

import sys

import pandas as pd
import pytest

import gbfs_toolkit as gb
from gbfs_toolkit import SchemaError

# --- input validation: clear SchemaError, not cryptic KeyError ---------------


def test_validation_guards_raise_schema_error():
    with pytest.raises(SchemaError):
        gb.join_availability(pd.DataFrame({"x": [1]}), pd.DataFrame({"station_id": ["a"]}))
    with pytest.raises(SchemaError):
        gb.calculate_net_flow(pd.DataFrame({"system_id": ["x"], "station_id": ["a"]}))
    with pytest.raises(SchemaError):
        gb.coverage_report(pd.DataFrame({"system_id": ["x"]}))
    with pytest.raises(SchemaError):
        gb.detect_ghost_vehicles(pd.DataFrame({"system_id": ["x"], "vehicle_id": ["v"]}))
    with pytest.raises(SchemaError):
        gb.link_transit_stops(pd.DataFrame({"station_id": ["a"]}), pd.DataFrame({"stop_lat": [1]}))


# --- stats: empty / degenerate inputs ---------------------------------------


def test_stats_handle_empty_inputs():
    empty = pd.DataFrame({"capacity": [], "lat": [], "lon": [], "occ": []})
    assert gb.system_profile(empty)["n_stations"] == 0
    cm = gb.concentration_metrics(empty)
    assert cm["n_stations"] == 0
    assert gb.lorenz_curve(empty).iloc[0]["cum_value_share"] == 0.0
    cov = gb.coverage_stats(empty)
    assert cov["n_stations"] == 0
    mi = gb.morans_i(pd.DataFrame({"lat": [1.0], "lon": [2.0], "v": [1.0]}), "v")
    assert mi["n"] == 1  # too few points → NaN metrics, n reported
    rk = gb.ripley_k(pd.DataFrame({"lat": [1.0], "lon": [2.0]}), radii=[100])
    assert rk["k"].isna().all()


def test_multimodal_empty_info():
    out = gb.link_transit_stops(
        pd.DataFrame({"lat": [], "lon": []}), pd.DataFrame({"stop_lat": [1.0], "stop_lon": [2.0]})
    )
    assert "is_transit_feeder" in out.columns and out.empty


# --- fetch: session, conditional GET, error wrapping ------------------------


def test_build_session_has_retry_adapters():
    pytest.importorskip("requests")
    s = gb.build_session(total=2)
    assert s.adapters["https://"].max_retries.total == 2


class _Resp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError("http error")


def test_fetch_feed_json_200_returns_response():
    sess = type(
        "S",
        (),
        {"get": lambda self, u, timeout=None, headers=None: _Resp(200, {"ok": 1}, {"ETag": "e"})},
    )()
    resp = gb.fetch_feed_json("u", session=sess)
    assert resp.data == {"ok": 1} and resp.etag == "e"


def test_get_json_wraps_network_error():
    import requests

    from gbfs_toolkit.fetch import _get_json

    class _Boom:
        def get(self, *a, **k):
            raise requests.ConnectionError("down")

    with pytest.raises(gb.GBFSFetchError):
        _get_json("u", session=_Boom())


# --- fetch: feed delegators over an injected full discovery doc --------------

_DISCOVERY = {
    "version": "2.3",
    "ttl": 60,
    "data": {
        "en": {
            "feeds": [
                {"name": "station_information", "url": "info"},
                {"name": "station_status", "url": "status"},
                {"name": "free_bike_status", "url": "bikes"},
                {"name": "system_information", "url": "sysinfo"},
                {"name": "system_regions", "url": "regions"},
                {"name": "system_alerts", "url": "alerts"},
            ]
        }
    },
}
_DOCS = {
    "g": _DISCOVERY,
    "info": {
        "data": {"stations": [{"station_id": "1", "lat": 48.85, "lon": 2.35, "capacity": 10}]}
    },
    "status": {
        "data": {
            "stations": [{"station_id": "1", "num_bikes_available": 4, "num_docks_available": 6}]
        }
    },
    "bikes": {"data": {"bikes": [{"bike_id": "b1", "lat": 48.8, "lon": 2.3}]}},
    "sysinfo": {"data": {"system_id": "velib", "timezone": "Europe/Paris", "name": "Velib"}},
    "regions": {"data": {"regions": [{"region_id": "r1", "name": "Centre"}]}},
    "alerts": {"data": {"alerts": [{"alert_id": "a1", "type": "SYSTEM_CLOSURE"}]}},
}


def _feed():
    return gb.GBFSFeed.from_url("g", get_json=_DOCS.get, system_id="velib")


def test_feed_delegators():
    feed = _feed()
    assert feed.has("station_status")
    assert feed.ttl == 60
    assert feed.timezone == "Europe/Paris"
    assert feed.system_regions().iloc[0]["region_id"] == "r1"
    assert feed.alerts().iloc[0]["type"] == "SYSTEM_CLOSURE"
    snap = feed.snapshot()
    assert {"information", "status", "vehicles"} <= set(snap)
    summary = feed.summary()
    assert summary["total_stations"] == 1
    tally = feed.reconcile_fleet()
    assert tally["available_in_stations"] == 4
    local = feed.to_local_time(feed.station_status(), columns=("fetched_at",))
    assert str(local["fetched_at"].dt.tz) == "Europe/Paris"


# --- catalog ----------------------------------------------------------------


def test_catalog_local_resolve_and_filter(tmp_path):
    csv = tmp_path / "systems.csv"
    csv.write_text(
        "System ID,Name,Country Code,Auto-Discovery URL\n"
        "velib,Velib Metropole,FR,https://example.com/gbfs.json\n"
        "bixi,Bixi,CA,https://bixi.example/gbfs.json\n",
        encoding="utf-8",
    )
    cat = gb.systems_catalog(str(csv))
    assert "system_id" in cat.columns and "auto-discovery_url" in cat.columns
    fr = gb.filter_catalog(cat, country_code="fr")
    assert len(fr) == 1 and fr.iloc[0]["system_id"] == "velib"
    by_name = gb.filter_catalog(cat, name="bixi")
    assert by_name.iloc[0]["system_id"] == "bixi"
    info = gb.resolve("velib", cat)
    assert info["auto_discovery_url"].endswith("gbfs.json")


def test_catalog_url_success_writes_cache(tmp_path, monkeypatch):
    import gbfs_toolkit.catalog as cat

    monkeypatch.setattr(cat, "CACHE_PATH", tmp_path / "c" / "systems.csv")

    class _OK:
        text = "System ID,Name\nvelib,Velib\n"
        status_code = 200

        def raise_for_status(self):
            pass

    class _Req:
        class RequestException(Exception):  # noqa: N818 — mirrors requests
            pass

        def get(self, *a, **k):
            return _OK()

    monkeypatch.setitem(sys.modules, "requests", _Req())
    df = cat.systems_catalog("https://example.invalid/success.csv", refresh=True)
    assert "velib" in df["system_id"].tolist()
    assert (tmp_path / "c" / "systems.csv").exists()  # cached for next time


# --- timeseries resample + manifest edge ------------------------------------


def test_panel_resample(tmp_path):
    pytest.importorskip("pyarrow")
    base = tmp_path / "lake"
    for t, bikes in [(1_700_000_000, 10), (1_700_000_900, 4)]:  # 15 min apart
        snap = pd.DataFrame(
            {
                "system_id": "x",
                "station_id": ["1"],
                "num_bikes_available": [bikes],
                "num_docks_available": [20 - bikes],
                "last_reported": pd.to_datetime([t], unit="s", utc=True),
                "fetched_at": pd.to_datetime([t], unit="s", utc=True),
            }
        )
        gb.append_to_parquet(snap, base)
    panel = gb.build_availability_panel(base, system_id="x", resample_freq="5min")
    # 0,5,10,15 min → 4 rows, forward-filled
    assert len(panel) == 4


def test_manifest_on_empty_dir(tmp_path):
    man = gb.generate_manifest(tmp_path)
    assert man["n_files"] == 0
    assert man["total_bytes"] == 0
    assert man["files"] == []
    assert man.get("total_rows", 0) == 0  # empty lake → zero rows (or summary skipped)


# --- osm enrichment (geopandas path) ----------------------------------------


def test_enrich_with_osm_geodataframe():
    gpd = pytest.importorskip("geopandas")
    info = pd.DataFrame({"station_id": ["a"], "lat": [48.8550], "lon": [2.3500]})
    pts = gpd.GeoDataFrame(
        {"amenity": ["cafe", "pharmacy"]},
        geometry=gpd.points_from_xy([2.3500, 2.3500], [48.85503, 48.85510]),
        crs="EPSG:4326",
    )
    out = gb.enrich_with_osm(info, pts, radius_m=300, category_col="amenity")
    assert out.iloc[0]["osm_within"] == 2
    assert "osm_cafe" in out.columns
    # station_surroundings routes a GeoDataFrame through enrich_with_osm
    ctx = gb.station_surroundings(info, osm=pts, radius_m=300, osm_category_col="amenity")
    assert ctx.iloc[0]["osm_within"] == 2


# --- dynamic audit (D1/D2/D3) -----------------------------------------------


def test_audit_dynamic_flags():
    now = pd.Timestamp("2026-01-01T00:10:00Z")
    av = pd.DataFrame(
        {
            "station_id": ["neg", "over", "stale", "ok"],
            "num_bikes_available": [-1, 10, 5, 5],
            "num_docks_available": [5, 15, 5, 5],
            "capacity": [10, 20, 10, 10],  # 'over': 10+15=25 > 20
            "last_reported": pd.to_datetime(
                ["2026-01-01T00:09:30Z", "2026-01-01T00:09:30Z", "2026-01-01T00:00:00Z", now]
            ),
            "fetched_at": now,
        }
    )
    out = gb.audit_dynamic(av, ttl_seconds=60).set_index("station_id")
    assert bool(out.loc["neg", "D1_negative"])
    assert bool(out.loc["over", "D2_over_capacity"])
    assert bool(out.loc["stale", "D3_stale"])  # 10 min old ≫ ttl 60s
    assert not bool(out.loc["ok", "flagged"])


# --- fetch_multiple, from_system_id, module one-liners (offline) -------------

_V_DISC = {
    "version": "2.2",
    "data": {
        "en": {
            "feeds": [
                {"name": "station_information", "url": "v_info"},
                {"name": "station_status", "url": "v_status"},
            ]
        }
    },
}
_V = {
    "g_velib": _V_DISC,
    "v_info": {
        "data": {"stations": [{"station_id": "1", "lat": 48.85, "lon": 2.35, "capacity": 10}]}
    },
    "v_status": {
        "data": {
            "stations": [{"station_id": "1", "num_bikes_available": 4, "num_docks_available": 6}]
        }
    },
}


def _getter(url):
    if url in _V:
        return _V[url]
    raise gb.GBFSFetchError(f"no such url: {url}")


def test_fetch_multiple_mixes_ok_and_failed():
    cat = pd.DataFrame(
        {
            "system_id": ["velib", "broken"],
            "name": ["Velib", "Broken"],
            "country_code": ["FR", "FR"],
            "auto_discovery_url": ["g_velib", "g_broken"],  # g_broken not in _getter → fails
        }
    )
    res = gb.fetch_multiple(["velib", "broken"], catalog=cat, get_json=_getter, max_workers=2)
    assert isinstance(res["velib"], gb.GBFSFeed)
    assert isinstance(res["broken"], Exception)


def test_module_oneliners():
    av = gb.availability("g_velib", get_json=_getter, system_id="velib")
    assert av.iloc[0]["num_bikes_available"] == 4
    verdict = gb.audit_feed("g_velib", get_json=_getter, system_id="velib")
    assert set(verdict["audit_type"]) == {"static", "dynamic"}
