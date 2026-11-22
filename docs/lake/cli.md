# Command line: collect, compact, quality, release, verify

!!! warning "Experimental"
    The commands below were added in 2.1.0 and may change in a minor release. `gbfs audit`
    is stable. See the [overview](index.md).

Needs the extras of the library calls behind them: `pip install "gbfs-toolkit[fetch,parquet]"` (and
`[cli]` for coloured audit tables). Exit codes: `0` success, `1` a check failed (a failed poll, a
mismatching release), `2` bad arguments, missing input or a refusal.

## `gbfs collect`

Polls feeds politely and writes one fragment per poll under `OUT/<feed>/<system>/_fragments/<day>/`
([collect](collect.md)); `--compact` gathers the fragments of closed days into `OUT/<feed>/<system>/<day>.parquet`
when it is done, and `--write day` rewrites the day file at each poll instead. With none of `--interval`,
`--duration` and `--iterations` it polls **once**.

```bash
gbfs collect --system harbor=https://example.org/gbfs/gbfs.json \
             --out data/collected \
             --user-agent "my-lab-gbfs/1.0 (mailto:me@example.org)"

# a poll a minute for an hour, vehicles too, and the dated metadata
gbfs collect --systems-file systems.csv --out data/collected \
             --user-agent "my-lab-gbfs/1.0 (mailto:me@example.org)" \
             --feeds station_status vehicle_status --metadata \
             --interval 60 --duration 3600
```

`--systems-file` is a CSV (`system_id` plus `auto_discovery_url`, `gbfs_url` or `url`; the output of
`gbfs_toolkit.systems_catalog` works) or a JSON object `{system_id: url}`. `--user-agent` is required.
`--min-interval` (seconds, default 1) and the feed's `ttl` are never undercut; `--no-ttl` ignores the
`ttl` and you then own the load.

## `gbfs compact`

Gathers the fragments of closed days into one file per system and day, atomically and idempotently
(running it again changes nothing). Today's fragments (UTC) are left alone unless `--include-today`.

```bash
gbfs compact data/collected                    # both feeds
gbfs compact data/collected --kind station_status --systems harbor
```

## `gbfs quality`

Daily coverage and incidents of a collection ([quality](quality.md)). `PATH` is a `collect` folder or a
lake, read in place (not loaded whole) unless `--systems` is given.

```bash
gbfs quality data/collected --end 2026-03-31 --incidents known-incidents.json --out reports/march
gbfs quality data/lake --layout lake --expected-polls 96 --poll-resolution 15min --strict
```

It prints, per system, the days in each status and the mean completeness, then the incident counts;
`--json` prints the same as JSON, `--out DIR` writes `daily_coverage.csv` and `incidents.json`, and
`--strict` exits `1` if any system-day is not `ok`. Leave today out with `--end` (it is still being
collected).

## `gbfs release`

Freezes a closed period of a lake into a new folder ([release](release.md)). It uploads nothing and
has no default licence.

```bash
gbfs release data/lake releases/demo-2026-03 --name demo-2026-03 \
             --start 2026-03-01 --end 2026-03-31 --license CC-BY-4.0 --systems harbor lakeside
```

## `gbfs verify`

Checks a release folder against its `SHA256SUMS`, or a data manifest against data
([repro](repro.md)).

```bash
gbfs verify releases/demo-2026-03            # every file matches, none unlisted
gbfs verify releases/demo-2026-03 --deep     # and the content fingerprint matches
gbfs verify data_manifest.json --data data/lake/
```
