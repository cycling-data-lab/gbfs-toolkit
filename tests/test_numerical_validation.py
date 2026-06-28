"""Cross-validate the home-grown estimators against the reference implementations.

Guards against subtle scientific bugs: the spatial statistics are checked against PySAL/esda
(using identical weights, so the test isolates the formula from the neighbour-graph choice) and
the outage survival against lifelines' Kaplan-Meier. These run in CI via the `[dev]` extra.
"""

import numpy as np
import pandas as pd
import pytest

import gbfs_toolkit as gb

# esda / libpysal emit many third-party deprecation and runtime warnings; not our concern here.
pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture
def spatial_sample():
    rng = np.random.default_rng(0)
    n = 60
    lat = 48.85 + rng.normal(0, 0.02, n)
    lon = 2.35 + rng.normal(0, 0.02, n)
    y = rng.normal(0, 1, n)
    info = pd.DataFrame({"lat": lat, "lon": lon, "v": y})
    return info, lat, lon, y


def _row_standardised_W(lat, lon, k):
    libpysal = pytest.importorskip("libpysal")
    from gbfs_toolkit.spatial.analytics import _knn_weights

    w = libpysal.weights.WSP(_knn_weights(lat, lon, k)).to_W()
    w.transform = "r"
    return w


def test_global_morans_i_matches_esda(spatial_sample):
    esda = pytest.importorskip("esda")
    info, lat, lon, y = spatial_sample
    k = 8
    mine = gb.morans_i(info, "v", k=k)["morans_i"]
    # Feed esda the same great-circle k-NN weights, so we validate the formula, not the graph.
    ref = esda.Moran(y, _row_standardised_W(lat, lon, k), permutations=0).I
    assert abs(mine - ref) < 1e-3


def test_local_morans_i_matches_esda(spatial_sample):
    esda = pytest.importorskip("esda")
    info, lat, lon, y = spatial_sample
    k = 8
    mine = gb.local_morans_i(info, "v", k=k, permutations=0)["local_i"].to_numpy()
    ref = esda.Moran_Local(y, _row_standardised_W(lat, lon, k), permutations=0).Is
    np.testing.assert_allclose(mine, ref, atol=1e-6)


def test_outage_survival_matches_lifelines():
    lifelines = pytest.importorskip("lifelines")
    rng = np.random.default_rng(1)
    durations = np.abs(rng.normal(30, 15, 80)).round(1)
    surv = gb.outage_survival(pd.DataFrame({"duration_minutes": durations}))
    kmf = lifelines.KaplanMeierFitter().fit(durations)
    km = np.array(
        [float(kmf.survival_function_at_times(t).iloc[0]) for t in surv["duration_minutes"]]
    )
    np.testing.assert_allclose(surv["survival"].to_numpy(), km, atol=1e-9)


def test_gini_matches_reference():
    # Closed-form check of the Gini coefficient against the mean-absolute-difference definition.
    from gbfs_toolkit.core.utils import gini

    rng = np.random.default_rng(2)
    x = np.abs(rng.normal(50, 20, 200))
    mad = np.abs(x[:, None] - x[None, :]).mean()
    reference = mad / (2 * x.mean())
    assert abs(gini(x) - reference) < 1e-9
