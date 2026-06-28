"""Compare semantic data quality across a whole country or operator.

Live (downloads the MobilityData catalogue and fetches each feed), so this is the
one scenario that is not exercised offline:

    python 10_macro_scale_audit.py --country FR --limit 25

Are the data-quality anomalies local bugs, or global architecture choices of an
operator? This filters the world catalogue to a country, audits every reachable
feed with one call, and ranks the classes by how widely they fire — turning the
per-feed audit into a cross-corpus comparison.
"""

import argparse
import collections

import gbfs_toolkit as gb


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", default="FR", help="ISO country code to scan")
    ap.add_argument("--limit", type=int, default=25, help="cap the number of systems")
    args = ap.parse_args()

    # 1. The world inventory, filtered to one country.
    catalog = gb.systems_catalog()
    national = gb.filter_catalog(catalog, country_code=args.country)
    ids = national["system_id"].astype(str).tolist()[: args.limit]
    print(f"{args.country}: {len(national)} systems in the catalogue, auditing {len(ids)}\n")

    # 2. Fetch and audit them all in one call (heuristic-free, declared types).
    verdict, status = gb.audit_catalogue(ids, catalog=catalog, a7_scope="all")
    reachable = sum(1 for s in status.values() if s.startswith("ok"))
    print("Coverage:", dict(collections.Counter(s.split(":")[0] for s in status.values())))
    print(f"Audited {reachable}/{len(ids)} feeds, {len(verdict)} stations\n")

    # 3. How widely does each class fire across the corpus?
    if len(verdict):
        flags = [f"A{i}" for i in range(1, 8)]
        per_system = verdict.groupby("system_id")[flags].max()
        print("Systems flagged per class:")
        print(per_system.sum().to_string())


if __name__ == "__main__":
    main()
