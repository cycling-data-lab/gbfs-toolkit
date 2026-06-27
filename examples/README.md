# Examples

Worked end-to-end scripts, in the order you'd actually meet them.

| Script | What it does | Needs |
|--------|--------------|-------|
| [`01_audit_a_feed.py`](01_audit_a_feed.py) | Inspect and audit an unknown feed; keep the trustworthy stations | `[fetch]` |
| [`02_collect_snapshot.py`](02_collect_snapshot.py) | One cron-driven collection run into a Parquet lake (conditional GET) | `[fetch]`, `[parquet]` |
| [`03_analyze_history.py`](03_analyze_history.py) | Coverage, daily typologies and turnover from a built-up lake | `[parquet]`, `[cluster]` |
| [`04_equity_and_coverage.py`](04_equity_and_coverage.py) | Capacity concentration and spatial equity of a network | `[fetch]`, `[geo]` |

Install what a script needs, e.g. `pip install gbfs-toolkit[fetch,parquet,cluster,geo]`.

Feeds are operator-run and change without notice — a URL that worked last month may move or
break. `01` and `04` take a `gbfs.json` URL directly; `02`/`03` resolve a system by its
MobilityData catalogue id (`velib`, `bike_share_toronto`, …). Find ids with:

```python
import gbfs_toolkit as gb
cat = gb.systems_catalog()
gb.filter_catalog(cat, country_code="FR")[["system_id", "name"]]
```
