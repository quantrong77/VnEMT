"""TC-01: six-pulse thyristor bridge, alpha sweep 0-150 deg (SPEC 10.2; F1-L01, F1-L03,
F1-L04, F1-L05).

Acceptance (SPEC):
* F1-L01: Ud matches ``Ud0 cos(alpha) - (3/pi) Xc Id`` within 1 %. Near alpha = 90 deg Ud -> 0,
  so the error is normalised by ``Ud0`` (the only meaningful scale over the whole sweep).
* F1-L03: firing pulse spacing deviation < 0.1 deg in steady state.
* F1-L04: measured gamma matches ``cos(gamma) = cos(beta) + sqrt2 Xc Id / U_LL`` within 0.5 deg.
  This relation holds while the extinction interval is not cut by the commutation notch of the
  opposite valve group, i.e. for gamma < 60 deg - mu; the sweep checks it for alpha >= 120 deg
  (inverter operation). mu is checked against ``cos(alpha+mu) = cos(alpha) - sqrt2 Xc Id/U_LL``
  over the whole sweep.
* F1-L05: with ``t_q`` longer than the available extinction time the valve re-conducts and a
  commutation failure is recorded.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import vnemt
from vnemt.analysis.lcc import measure_bridge
from vnemt.io.case_loader import CaseFile, load_yaml

F, U_LL, LC, ID, RP = 50.0, 10e3, 5e-3, 250.0, 1e5
XC = 2 * np.pi * F * LC
UD0 = 3 * np.sqrt(2) / np.pi * U_LL
VALVES = ["T1", "T2", "T3", "T4", "T5", "T6"]
EMF = ("Sa.V", "Sb.V", "Sc.V")


def run_case(cases_dir: Path, alpha: float, dt_us: float = 20.0, t_q: float | None = None):
    data = load_yaml((cases_dir / "tc01_bridge6.yaml").read_text(encoding="utf-8"))
    data["controls"][1]["alpha_deg"] = alpha
    data["case"]["solver"]["dt_us"] = dt_us
    if t_q is not None:
        for el in data["circuit"]["elements"]:
            if el["type"] == "T":
                el["t_q_s"] = t_q
    res = vnemt.Case(CaseFile(data=data, path=None, sha256="")).run()
    return res, measure_bridge(res, VALVES, EMF, F)


def measured(x: np.ndarray) -> np.ndarray:
    """Drop the last extinction interval if the run ended before it was complete."""
    done = x[~np.isnan(x)]
    assert len(done) >= len(x) - 1
    return done


def steady(res, m, cycles: int = 2):
    t_end = res.time[-1]
    last = res.time > t_end - cycles / F
    ud = float(np.mean((res["P.V"] - res["N.V"])[last]))
    sel = m.t > t_end - cycles / F
    return ud, ID + ud / RP, sel


@pytest.mark.req("F1-L01")
@pytest.mark.req("F1-L03")
@pytest.mark.req("F1-L04")
@pytest.mark.parametrize("alpha", [
    0.0,
    pytest.param(15.0, marks=pytest.mark.slow),
    30.0,
    pytest.param(60.0, marks=pytest.mark.slow),
    90.0,
    pytest.param(105.0, marks=pytest.mark.slow),
    120.0,
    pytest.param(135.0, marks=pytest.mark.slow),
    150.0,
])
def test_tc01_alpha_sweep(cases_dir: Path, alpha: float) -> None:
    res, m = run_case(cases_dir, alpha)
    ud, idb, sel = steady(res, m)
    ud_formula = UD0 * np.cos(np.radians(alpha)) - 3 / np.pi * XC * idb
    assert abs(ud - ud_formula) / UD0 < 0.01

    # firing: measured alpha and equidistance of the 6 pulses
    assert np.max(np.abs(m.alpha[sel] - alpha)) < 0.1
    spacing = np.diff(m.t[sel]) * 360 * F
    assert np.max(np.abs(spacing - 60.0)) < 0.1
    assert list(np.diff(m.valve[sel]) % 6) == [1] * (sel.sum() - 1)

    mu_formula = np.degrees(np.arccos(np.cos(np.radians(alpha))
                                      - np.sqrt(2) * XC * idb / U_LL)) - alpha
    assert np.max(np.abs(m.mu[sel] - mu_formula)) < 0.5
    if alpha >= 120.0:
        beta = np.radians(180.0 - alpha)
        gamma_formula = np.degrees(np.arccos(np.cos(beta) + np.sqrt(2) * XC * idb / U_LL))
        assert np.max(np.abs(measured(m.gamma[sel]) - gamma_formula)) < 0.5
    assert m.n_cf == 0


@pytest.mark.req("F1-L03")
def test_tc01_firing_independent_of_time_step(cases_dir: Path) -> None:
    """Firing instants are off-grid: alpha, mu, gamma hold at dt = 50 us."""
    alpha = 140.0
    res, m = run_case(cases_dir, alpha, dt_us=50.0)
    _, idb, sel = steady(res, m)
    assert np.max(np.abs(m.alpha[sel] - alpha)) < 0.1
    beta = np.radians(180.0 - alpha)
    gamma_formula = np.degrees(np.arccos(np.cos(beta) + np.sqrt(2) * XC * idb / U_LL))
    assert np.max(np.abs(measured(m.gamma[sel]) - gamma_formula)) < 0.5


@pytest.mark.req("F1-L05")
def test_tc01_commutation_failure_when_tq_exceeds_extinction_time(cases_dir: Path) -> None:
    """alpha = 150 deg gives gamma ~ 22.8 deg = 1.27 ms; t_q = 2 ms cannot be met."""
    _, m = run_case(cases_dir, 150.0, t_q=2e-3)
    assert m.n_cf > 0
    _, m_ok = run_case(cases_dir, 150.0, t_q=1e-3)
    assert m_ok.n_cf == 0


@pytest.mark.req("F1-L03")
def test_tc01_deblock_without_overvoltage(cases_dir: Path) -> None:
    """At deblocking every valve inside its gate window is fired: no valve group is left
    unfired, so the DC voltage never exceeds the peak line voltage by much."""
    res, _ = run_case(cases_dir, 30.0)
    ud = res["P.V"] - res["N.V"]
    assert np.max(np.abs(ud)) < 1.2 * np.sqrt(2) * U_LL
