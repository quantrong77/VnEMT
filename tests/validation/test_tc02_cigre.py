"""TC-02 (SPEC 10.2, r4): CIGRE-type LCC monopole, VnEMT configuration (SPEC 10.2.1).

Acceptance from a zero start, steady state reached within 1.0 s and held until 1.5 s:
Id = 1.00 pu +/- 1 %, gamma_min = gamma_ref +/- 1 deg, rectifier alpha 10-20 deg,
P_dc = 1000 MW +/- 3 %, AC bus voltages 0.95-1.05 pu, Id peak-to-peak < 5 %, no commutation
failure, and the rectifier Ud matches the quasi-steady-state formula (measured U_LL, alpha,
Id) within 1 %.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import vnemt
from vnemt.results import Result

F = 50.0


@pytest.fixture(scope="module")
def tc02(cases_dir: Path) -> Result:
    return vnemt.load(cases_dir / "tc02_cigre_lcc.yaml").run()


def _rms_pu(res: Result, names: list[str], u_kv: float, m: np.ndarray) -> list[float]:
    return [float(np.sqrt(np.mean(res[n][m] ** 2)) / (u_kv * 1e3 / np.sqrt(3))) for n in names]


@pytest.mark.slow
@pytest.mark.req("F3-01")
def test_tc02_steady_state_operating_point(tc02: Result) -> None:
    res = tc02
    t = res.time
    after = t >= 1.0
    idc = res["REC_CTRL.Id"][after]
    assert np.max(np.abs(idc - 1.0)) < 0.01
    assert np.ptp(res["REC_Ls.I"][after]) / 2000.0 < 0.05
    assert np.max(np.abs(res["INV_CTRL.gamma_min"][after] - 15.0)) < 1.0
    alpha_r = res["REC_CTRL.alpha"][after]
    assert 10.0 <= alpha_r.min() and alpha_r.max() <= 20.0
    assert np.all(res["INV_CTRL.mode"][after] == 0.0)  # inverter on CEA

    last = t > t[-1] - 2 / F  # two cycles for averages
    ud = float(np.mean(res["REC_DC.V"][last]))
    i_a = float(np.mean(res["REC_Ls.I"][last]))
    assert ud * i_a / 1e6 == pytest.approx(1000.0, rel=0.03)
    for u in _rms_pu(res, ["ACR_a.V", "ACR_b.V", "ACR_c.V"], 345.0, last) + \
            _rms_pu(res, ["ACI_a.V", "ACI_b.V", "ACI_c.V"], 230.0, last):
        assert 0.95 <= u <= 1.05
    assert not any(m[2] == "cf" for m in res.markers)


@pytest.mark.slow
@pytest.mark.req("F1-L01")
def test_tc02_rectifier_voltage_matches_quasi_steady_state(tc02: Result) -> None:
    """Two series bridges: Ud = 2 [1.35 U_v cos(alpha) - (3/pi) Xc Id], U_v valve-side line
    voltage from the measured bus (fundamental) and the transformer ratio with tap 1.01."""
    res = tc02
    last = res.time > res.time[-1] - 2 / F
    n = round(1 / F / (res.time[1] - res.time[0])) * 2
    ta, va = res.time[last][:n], res["ACR_a.V"][last][:n]
    v1 = abs(2 * np.mean(va * np.exp(-1j * 2 * np.pi * F * ta)))  # fundamental phase peak
    u_v = v1 * np.sqrt(1.5) * 213.4 / (345.0 * 1.01)
    xc = 0.18 * 213.4e3**2 / 603.73e6
    alpha = np.radians(np.mean(res["REC_CTRL.alpha"][last]))
    i_a = float(np.mean(res["REC_Ls.I"][last]))
    ud_formula = 2 * (3 * np.sqrt(2) / np.pi * u_v * np.cos(alpha) - 3 / np.pi * xc * i_a)
    assert float(np.mean(res["REC_DC.V"][last])) == pytest.approx(ud_formula, rel=0.01)
