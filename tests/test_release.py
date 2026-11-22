"""release: a frozen, checksummed, documented folder from a closed period of a lake."""

from __future__ import annotations

import datetime as dt
import json

import pandas as pd
import pytest

from gbfs_toolkit.core.errors import GBFSValidationError
from gbfs_toolkit.release import CHECKSUM_FILE, freeze_release, table_schema, verify_release

pytest.importorskip("pyarrow")

from gbfs_toolkit.store import read_lake, write_lake  # noqa: E402

TODAY = dt.date(2026, 4, 1)


def snaps(system, start, minutes, bikes=3):
    t = pd.date_range(start, periods=minutes, freq="min", tz="UTC")
    return pd.DataFrame(
        {
            "system_id": system,
            "station_id": "s1",
            "observed_at_utc": t,
            "num_bikes_available": pd.array([bikes] * minutes, dtype="Int64"),
            "num_docks_available": pd.array([5] * minutes, dtype="Int64"),
        }
    )


@pytest.fixture
def lake(tmp_path):
    root = tmp_path / "lake"
    # a: three full days across the end of February and March; b: a partial day
    write_lake(snaps("a", "2026-02-28", 3 * 1440), root)
    write_lake(snaps("b", "2026-03-01", 700), root)
    return root


def freeze(lake, tmp_path, **kw):
    opts = {
        "name": "demo-2026-03",
        "start": "2026-03-01",
        "end": "2026-03-01",
        "license": "CC0-1.0",
        "today": TODAY,
    }
    opts.update(kw)
    return freeze_release(lake, tmp_path / "rel", **opts)


def test_period_is_cut_at_the_bounds_and_across_months(lake, tmp_path):
    info = freeze(lake, tmp_path)
    assert (
        info["systems"] == ["a", "b"]
        and info["rows"] == 1440 + 700
        and info["period"] == ("2026-03-01", "2026-03-01")
    )
    got = read_lake(tmp_path / "rel" / "data" / "station_status")
    t = got["observed_at_utc"]
    assert t.min() >= pd.Timestamp("2026-03-01", tz="UTC") and t.max() < pd.Timestamp(
        "2026-03-02", tz="UTC"
    )
    assert len(got[got["system_id"] == "a"]) == 1440
    cross = freeze(
        lake, tmp_path.parent / (tmp_path.name + "x"), start="2026-02-28", end="2026-03-01"
    )
    assert cross["rows"] == 2 * 1440 + 700 and cross["files"] == 3  # a: Feb + Mar, b: Mar


def test_systems_can_be_chosen(lake, tmp_path):
    info = freeze(lake, tmp_path, systems=["b"])
    assert info["systems"] == ["b"] and info["rows"] == 700
    assert not (tmp_path / "rel" / "data" / "station_status" / "system_id=a").exists()


def test_the_folder_has_every_file_and_checksums_verify(lake, tmp_path):
    freeze(lake, tmp_path)
    rel = tmp_path / "rel"
    names = {p.relative_to(rel).as_posix() for p in rel.rglob("*") if p.is_file()}
    assert {
        "README.md",
        "datapackage.json",
        "croissant.json",
        "daily_coverage.csv",
        "daily_coverage.parquet",
        "incidents.csv",
        "incidents.json",
        "data_manifest.json",
        CHECKSUM_FILE,
    } <= names
    assert not [n for n in names if n.endswith(".tmp")]
    report = verify_release(rel, deep=True)
    assert report["ok"] and report["deep"] == {"rows": True, "fingerprint": True}
    assert report["checked"] == len(names) - 1
    lines = (rel / CHECKSUM_FILE).read_text().splitlines()
    assert all(len(row.split("  ")[0]) == 64 for row in lines) and lines == sorted(
        lines, key=lambda row: row.split("  ", 1)[1]
    )


def test_sha256sum_would_accept_the_file(lake, tmp_path):
    import hashlib

    freeze(lake, tmp_path)
    rel = tmp_path / "rel"
    for line in (rel / CHECKSUM_FILE).read_text().splitlines():
        digest, path = line.split("  ", 1)
        assert hashlib.sha256((rel / path).read_bytes()).hexdigest() == digest


def test_verify_finds_changed_missing_and_extra_files(lake, tmp_path):
    freeze(lake, tmp_path)
    rel = tmp_path / "rel"
    (rel / "README.md").write_text("tampered")
    (rel / "incidents.csv").unlink()
    (rel / "extra.txt").write_text("hi")
    r = verify_release(rel, strict=False)
    assert (
        not r["ok"]
        and r["mismatched"] == ["README.md"]
        and r["missing"] == ["incidents.csv"]
        and r["unlisted"] == ["extra.txt"]
    )
    with pytest.raises(GBFSValidationError, match="changed"):
        verify_release(rel)
    with pytest.raises(GBFSValidationError, match="no SHA256SUMS"):
        verify_release(tmp_path)


def test_verify_rejects_hostile_checksum_files(tmp_path):
    (tmp_path / CHECKSUM_FILE).write_text(f"{'0' * 64}  ../../etc/passwd\n")
    with pytest.raises(GBFSValidationError, match="unsafe"):
        verify_release(tmp_path)
    (tmp_path / CHECKSUM_FILE).write_text("not a checksum line\n")
    with pytest.raises(GBFSValidationError, match="not a 'sha256  path' line"):
        verify_release(tmp_path)


def test_deep_check_catches_a_reencoded_file(lake, tmp_path):
    freeze(lake, tmp_path)
    rel = tmp_path / "rel"
    f = next((rel / "data").rglob("*.parquet"))
    df = pd.read_parquet(f)
    df.loc[df.index[0], "num_bikes_available"] = 99
    df.to_parquet(f, index=False)
    (rel / CHECKSUM_FILE).unlink()
    from gbfs_toolkit.release import _write_checksums

    _write_checksums(rel)  # checksums refreshed by someone who altered the data
    assert verify_release(rel)["ok"]
    with pytest.raises(GBFSValidationError, match="content differs"):
        verify_release(rel, deep=True)


def test_coverage_and_incidents_describe_the_period(lake, tmp_path):
    freeze(
        lake,
        tmp_path,
        incidents=[
            {
                "incident_id": "x",
                "start_utc": "2026-03-01T01:00Z",
                "end_utc": "2026-03-01T02:00Z",
                "scope": "b",
                "cause": "ambiguous_missing_value",
                "summary": "old collector wrote 0",
            },
            {
                "incident_id": "elsewhere",
                "start_utc": "2026-01-01",
                "end_utc": "2026-01-02",
                "cause": "outage_collector",
            },
        ],
    )
    rel = tmp_path / "rel"
    cov = pd.read_csv(rel / "daily_coverage.csv").set_index("system_id")
    assert cov.loc["a", "status"] == "ok" and cov.loc["b", "status"] == "partial"
    inc = json.loads((rel / "incidents.json").read_text())
    assert [i["incident_id"] for i in inc] == ["x"]  # the January one is out of the period
    readme = (rel / "README.md").read_text()
    assert (
        "old collector wrote 0" in readme
        and "| a | 1 | 1 | 0 |" in readme
        and "| b | 1 | 0 | 1 |" in readme
    )


def test_detected_gaps_and_silent_feeds_are_listed(tmp_path):
    root = tmp_path / "lake"
    write_lake(
        pd.concat(
            [
                snaps("a", "2026-03-01", 1440),
                snaps("b", "2026-03-01", 1440),
                snaps("a", "2026-03-02", 1440),
            ]
        ),
        root,
    )  # b is silent on the 2nd
    freeze_release(
        root, tmp_path / "rel", name="r", start="2026-03-01", end="2026-03-02", today=TODAY
    )
    ids = [i["incident_id"] for i in json.loads((tmp_path / "rel" / "incidents.json").read_text())]
    assert ids == ["silent-b-20260302"]


def test_datapackage_is_a_valid_frictionless_package(lake, tmp_path):
    freeze(
        lake,
        tmp_path,
        producers=[{"system_id": "a", "producer": "City of A", "license": "Open Licence 2.0"}],
    )
    pkg = json.loads((tmp_path / "rel" / "datapackage.json").read_text())
    assert pkg["profile"] == "tabular-data-package" and pkg["version"] == "demo-2026-03"
    assert pkg["licenses"][0]["name"] == "CC0-1.0" and pkg["licenses"][0]["path"].startswith(
        "https://"
    )
    res = {r["name"]: r for r in pkg["resources"]}
    assert set(res) == {"station_status", "daily-coverage", "incidents"}
    fields = {f["name"]: f["type"] for f in res["station_status"]["schema"]["fields"]}
    assert (
        fields["observed_at_utc"] == "datetime"
        and fields["num_bikes_available"] == "integer"
        and fields["system_id"] == "string"
    )
    assert all((tmp_path / "rel" / p).is_file() for p in res["station_status"]["path"])
    assert (tmp_path / "rel" / res["daily-coverage"]["path"]).is_file()
    for r in pkg["resources"]:
        for f in r.get("schema", {}).get("fields", []):
            assert f["type"] in {
                "string",
                "integer",
                "number",
                "boolean",
                "datetime",
                "date",
                "any",
            }
    assert "City of A" in (tmp_path / "rel" / "README.md").read_text()


def test_croissant_is_optional_and_well_formed(lake, tmp_path):
    freeze(lake, tmp_path)
    doc = json.loads((tmp_path / "rel" / "croissant.json").read_text())
    assert (
        doc["@type"] == "sc:Dataset" and doc["conformsTo"] == "http://mlcommons.org/croissant/1.0"
    )
    assert doc["distribution"][0]["includes"] == "data/station_status/**/*.parquet"
    rs = doc["recordSet"][0]
    assert rs["@id"] == "station_status" and {f["name"] for f in rs["field"]} >= {
        "station_id",
        "observed_at_utc",
    }
    assert all(f["dataType"].startswith("sc:") for f in rs["field"])
    assert doc["license"].startswith("https://creativecommons.org")
    freeze(lake, tmp_path.parent / (tmp_path.name + "n"), croissant=False)
    assert not (tmp_path.parent / (tmp_path.name + "n") / "rel" / "croissant.json").exists()


def test_without_a_licence_the_readme_says_so(lake, tmp_path, caplog):
    with caplog.at_level("WARNING", logger="gbfs_toolkit"):
        freeze(lake, tmp_path, license=None)
    assert "No licence is declared" in (tmp_path / "rel" / "README.md").read_text()
    assert "licenses" not in json.loads((tmp_path / "rel" / "datapackage.json").read_text())
    assert "no licence declared" in caplog.text


def test_refusals(lake, tmp_path):
    with pytest.raises(GBFSValidationError, match="must be closed"):
        freeze(lake, tmp_path, end="2026-04-01")
    with pytest.raises(GBFSValidationError, match="before it starts"):
        freeze(lake, tmp_path, start="2026-03-05", end="2026-03-01")
    with pytest.raises(GBFSValidationError, match="nothing to freeze"):
        freeze(lake, tmp_path, start="2025-01-01", end="2025-01-02")
    freeze(lake, tmp_path)
    with pytest.raises(GBFSValidationError, match="not empty"):
        freeze(lake, tmp_path)


def test_an_open_period_can_be_allowed_explicitly(tmp_path):
    root = tmp_path / "lake"
    write_lake(snaps("a", "2026-04-01", 100), root)
    info = freeze_release(
        root,
        tmp_path / "r",
        name="open",
        start="2026-04-01",
        end="2026-04-01",
        allow_open_period=True,
        today=dt.date(2026, 4, 1),
    )
    assert info["rows"] == 100


def test_table_schema_types():
    df = pd.DataFrame(
        {
            "i": [1],
            "f": [1.5],
            "b": [True],
            "t": pd.to_datetime(["2026-01-01"], utc=True),
            "s": ["x"],
            "n": pd.array([None], dtype="Int64"),
            "o": [object()],
        }
    )
    types = {f["name"]: f["type"] for f in table_schema(df)["fields"]}
    assert types == {
        "i": "integer",
        "f": "number",
        "b": "boolean",
        "t": "datetime",
        "s": "string",
        "n": "integer",
        "o": "string",
    }


def test_croissant_fields_a_validator_asks_for(lake, tmp_path):
    freeze(lake, tmp_path, cite_as="Doe (2026), demo bike-share snapshots, doi:10.0000/demo")
    doc = json.loads((tmp_path / "rel" / "croissant.json").read_text())
    assert doc["version"] == "1.0.0" and doc["citeAs"].startswith("Doe (2026)")
    csv = next(d for d in doc["distribution"] if d["@id"] == "daily_coverage.csv")
    listed = dict(
        line.split("  ", 1)[::-1]
        for line in (tmp_path / "rel" / "SHA256SUMS").read_text().splitlines()
    )
    assert csv["sha256"] == listed["daily_coverage.csv"]  # the checksum matches the file
    assert {"rai", "examples", "samplingRate", "equivalentProperty"} <= set(doc["@context"])


def test_croissant_is_valid_for_the_mlcommons_validator(lake, tmp_path):
    """Optional: runs when ``mlcroissant`` is installed (``pip install mlcroissant``)."""
    mlc = pytest.importorskip("mlcroissant")
    freeze(lake, tmp_path, cite_as="Doe (2026), demo bike-share snapshots")
    path = tmp_path / "rel" / "croissant.json"
    dataset = mlc.Dataset(jsonld=str(path))  # raises ValidationError on any error
    assert dataset.metadata.name == "demo-2026-03"
    assert {rs.name for rs in dataset.metadata.record_sets} == {"station_status"}
