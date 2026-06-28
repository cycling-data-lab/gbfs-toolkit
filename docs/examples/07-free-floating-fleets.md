# Audit free-floating & ghost fleets

Free-floating systems break the station paradigm: the truth lives in the
`vehicles` / `free_bike_status` feed, not in `station_status`. This scenario is
the one no syntactic validator can do — it reconciles both sides of a hybrid
fleet, finds vehicles that are declared but never move (inflating the advertised
supply), and measures whether the live fleet is collapsing into a few blocks.
Self-contained (synthetic panel, no network), run in CI.

!!! info "Requirements"
    None for the core (bundled / synthetic data). `[geo]` only if you add the
    optional geofencing step (measuring density against the real service area).

What the script does:

- **Reconciles the fleet.** [`reconcile_fleet_state`][gbfs_toolkit.reconcile_fleet_state]
  merges the docked `station_status` and the free-floating `vehicles` feed into one
  labelled tally, avoiding the double-count that inflates a naive sum.
- **Finds the ghosts.** [`detect_ghost_vehicles`][gbfs_toolkit.detect_ghost_vehicles]
  flags vehicles that stay put across the panel — declared in the feed but never
  rented, padding the operator's headline fleet size.
- **Measures spatial collapse.** [`spatial_entropy`][gbfs_toolkit.spatial_entropy]
  tracks the Shannon entropy of the live distribution: a falling entropy means the
  fleet is piling up in a few cells rather than serving the city.

Run it:

```console
$ python examples/07_free_floating_fleets.py
```

Full source:

```python
--8<-- "examples/07_free_floating_fleets.py"
```
