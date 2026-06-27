# Examples

Four worked, end-to-end scripts, in the order you would actually meet them: audit an unknown
feed, collect snapshots into a data lake, analyse the resulting history, then measure network
equity. Each has its own page with a step-by-step walkthrough, the command to run it, and the full
source.

| Example | Goal | Extras |
|---|---|---|
| [Audit a feed](examples/01-audit-a-feed.md) | Inspect an unknown feed and keep the trustworthy stations | `[fetch]` |
| [Collect a snapshot](examples/02-collect-a-snapshot.md) | One cron-driven collection run into a Parquet lake | `[fetch]`, `[parquet]` |
| [Analyse history](examples/03-analyze-history.md) | Coverage, daily typologies and turnover from a built-up lake | `[parquet]`, `[cluster]` |
| [Equity and coverage](examples/04-equity-and-coverage.md) | Capacity concentration and spatial equity of a network | `[fetch]`, `[geo]` |

Install what a script needs, for example:

```bash
pip install "gbfs-toolkit[fetch,parquet,cluster,geo]"
```

The runnable `.py` files live in the
[`examples/`](https://github.com/cycling-data-lab/gbfs-toolkit/tree/main/examples) directory of the
repository.

## Finding a system id

Examples `02` and `03` resolve a system by its MobilityData catalogue id (`velib`,
`bike_share_toronto`, and so on). Examples `01` and `04` take a `gbfs.json` URL directly. To find
an id:

```python
import gbfs_toolkit as gb

cat = gb.systems_catalog()
gb.filter_catalog(cat, country_code="FR")[["system_id", "name"]]
```

!!! note "Feeds change without notice"
    GBFS feeds are operator-run. A URL that worked last month may move or break, and the exact
    fields a feed publishes vary by operator and GBFS version. The audit is designed to make those
    differences visible rather than to assume them away.
