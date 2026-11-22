# API policy

What a release promises, how a change is announced, and what the library does when
something goes wrong. The tests in `tests/test_public_api.py` and
`tests/test_api_policy.py` guard it.

## What is public

The public API is every name in `gbfs_toolkit.__all__`, importable as `gbfs_toolkit.<name>`
(`import gbfs_toolkit as gb`), plus the `gbfs` command line. The submodules
(`gbfs_toolkit.io.timeseries`, `gbfs_toolkit.spatial.graph`, ...) are organised for the
reader of the reference, and each declares its own `__all__`; the top-level names are the
supported entry points. Anything else is internal and may change in any release:

- a name that starts with an underscore (`_stability`, `_require_pyarrow`, ...);
- the module `gbfs_toolkit.core.utils` (its helpers are shared plumbing, not API);
- the column order of a returned frame beyond the documented columns, and the exact text
  of warnings and error messages.

## Stability levels

| Level | Names | Promise |
|---|---|---|
| **Stable** | every public name not listed below | Within a major version: same name, same parameters (an added keyword-only parameter with a default is allowed), same documented behaviour, same results on the same inputs. A change of result is announced in the changelog; a change of a documented contract waits for the next major version. |
| **Experimental** | the flow simulator and its compiler: `SimConfig`, `simulate_city_flows`, `generate_gbfs_parquet`, `export_ml_dataset`, `calibrate_city`, `compute_footprint` | May change, or go, in a minor release. Their docstrings carry an "Experimental" note. Simulated numbers have no external reference yet. |
| **Experimental modules** | the data-lake modules added in 2.1.0: `collect`, `history`, `quality`, `aggregate`, `store`, `stations.match`, `trips`, `release`, `repro`, and the `gbfs collect`, `quality`, `release` and `verify` commands | Public, tested and documented, but names, parameters and output columns may change in a minor release while they are used on more systems. Import them by path (`from gbfs_toolkit import quality`): they are not re-exported at the top level. Their module docstrings carry an "Experimental" note. See the [roadmap](roadmap.md) for how a module becomes stable. |

The experimental names are listed once, in `gbfs_toolkit/_stability.py` (`EXPERIMENTAL` for names,
`EXPERIMENTAL_MODULES` for modules); a test checks that each one carries the note in its docstring.

A **change of default** that the changelog lists under *Open points* follows the same road: the
corrected behaviour is added as an option (off by default) in a minor release; a call whose result
would differ and which leaves the option unset emits a `FutureWarning` that says the default changes in
the next major release and how to choose now (`warn_default_change`, internal); the default changes in
that major release. The warning is raised only where the two behaviours differ, and never when the option
is given. `tests/test_open_points.py` checks it for each.

A **typed result** (`AuditReport`) is a subclass of the type it replaces, so code written for the old
type keeps working; the exception is an identity check on the exact class.

A bug fix is not a breaking change, even when it changes a result: if a function's
docstring promises something and the code did otherwise, the code is corrected. The
changelog says so under *Fixed*, with the inputs for which the result moves. When
correcting a result would break a verdict that published work already relies on, the
default is kept, the behaviour is documented, and the correct one is offered as an
option that is off by default (see the *Open points* in the changelog).

## Deprecation

A public name, parameter or behaviour is removed in three steps:

1. A **minor** release deprecates it. The old way keeps working and emits a
   `FutureWarning` that names the version that deprecated it, the removal and the
   replacement. The changelog lists it under *Deprecated*.
2. It stays for **at least one further minor release** and at least **six months**.
3. The next **major** release removes it.

`FutureWarning` rather than `DeprecationWarning`, as in pandas: the second is hidden
from end users by default, and the people who run an audit are rarely the ones who
write the code.

Inside the library, a deprecation is written with two helpers (from
`gbfs_toolkit.core.utils`, internal): `warn_deprecated(...)` for a parameter or a
behaviour, and the `@deprecated(since=..., alternative=...)` decorator for a function.
Both produce the same message and add a "Deprecated" note to the reference page. To make
a deprecation an error in your own test suite:

```python
import warnings
warnings.simplefilter("error", FutureWarning)
```

## Errors

- `GBFSError` is the base of every problem with a feed or a frame: `GBFSFetchError`
  (network, HTTP status), `GBFSDiscoveryError` (no usable `gbfs.json`),
  `GBFSValidationError` (a frame that breaks the data model; `SchemaError` is its
  subclass for a missing column or a wrong type, and is also a `ValueError`) and
  `GBFSNotModified` (a conditional fetch that returned 304). `except GBFSError` catches
  all of them.
- A column that a function needs and the frame lacks raises `SchemaError`. Where the
  library once raised a bare `KeyError`, the error is still a `KeyError` as well, so
  existing handlers keep working.
- An invalid argument value (an unknown `method=`, a `freq` that is not a fixed
  frequency) raises `ValueError`, as in pandas and numpy.
- A missing optional dependency raises `ImportError` naming the extra to install
  (`pip install gbfs-toolkit[cluster]`).
- A problem with one feed in a batch (`fetch_multiple`, `audit_catalogue`) is logged and
  reported in the result, not raised, so one bad feed does not stop the others.

## Logging and output

The library never prints, except the `gbfs` command line and `show_versions`, whose job
is to print. Everything else reports through the standard `logging` module,
under the logger `gbfs_toolkit` (and its children, one per module). A library installs
no handler of its own: nothing appears until your application asks.

```python
import logging
logging.basicConfig(level=logging.INFO)        # fetch progress, skipped feeds
logging.getLogger("gbfs_toolkit").setLevel(logging.DEBUG)
```

Levels: `INFO` for progress, `WARNING` for a feed that was skipped or a result that is
degraded, `DEBUG` for details such as a cache that could not be written. Data-quality
findings are never logged: they are in the returned frames (the A1 to A7 flags).
Standard `warnings` are used for what the caller's code should change (a deprecation, a
suspicious argument).

## Versions

Versioning follows [SemVer](https://semver.org). Which Python and dependency versions a
release supports is in [Releasing](https://github.com/cycling-data-lab/gbfs-toolkit/blob/main/RELEASING.md#supported-versions).
