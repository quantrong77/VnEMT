"""Coupled-branch transformer model (inverse-inductance form) and Yy0 / Yd1 groups."""

from __future__ import annotations

import numpy as np
import pytest

from vnemt.components.transformer import three_phase_transformer
from vnemt.core import EmtSolver, simulate
from vnemt.errors import TopologyError
from vnemt.model.netlist import Element, Netlist

F = 50.0
W = 2 * np.pi * F


def steady_phasor(t: np.ndarray, x: np.ndarray, t0: float) -> complex:
    """Fundamental phasor (peak, sine reference) over whole cycles after t0."""
    n = 2 * round(1 / F / (t[1] - t[0]))  # two cycles
    m = t >= t0
    tt, xx = t[m][:n], x[m][:n]
    return complex(2 * np.mean(xx * np.exp(-1j * (W * tt - np.pi / 2))))


@pytest.mark.req("F1-L02")
def test_single_phase_ratio_and_leakage_with_resistive_load() -> None:
    """Load R2 on winding 2 referred to winding 1: a^2 R2 in series with L_k."""
    u1, a, lk, r2 = 1000.0, 4.0, 0.02, 5.0
    net = Netlist([
        Element("VS", "V_ac", ("A", "gnd"), {"U_peak_V": u1, "f_Hz": F}),
        Element("T1", "XF1", ("A", "gnd", "B", "gnd"), {"U1_V": a, "U2_V": 1.0, "L_k_H": lk}),
        Element("RL", "R", ("B", "gnd"), {"R_ohm": r2}),
    ])
    res = simulate(EmtSolver(net, dt=10e-6), 0.2, ["T1.w1.I", "T1.w2.I", "B.V"])
    z = a * a * r2 + 1j * W * lk
    i1 = steady_phasor(res.time, res["T1.w1.I"], 0.1)
    assert abs(i1 - u1 / z) / abs(u1 / z) < 1e-3
    np.testing.assert_allclose(res["T1.w2.I"], -a * res["T1.w1.I"], atol=1e-9)
    v2 = steady_phasor(res.time, res["B.V"], 0.1)
    assert abs(v2 - r2 * a * u1 / z) / abs(v2) < 1e-3  # load current = -i_w2 = a i1


def test_transformer_parameters_validated() -> None:
    net = Netlist([Element("VS", "V_dc", ("A", "gnd"), {"U_V": 1.0}),
                   Element("T1", "XF1", ("A", "gnd", "B", "gnd"),
                           {"U1_V": 1.0, "U2_V": 1.0, "L_k_H": 0.0})])
    with pytest.raises(TopologyError, match="L_k_H"):
        EmtSolver(net, dt=1e-6)


def _three_phase(winding2: str) -> dict[str, complex]:
    upk = 345e3 * np.sqrt(2 / 3)
    els = [Element(f"V{p}", "V_ac", (f"H{p}", "gnd"),
                   {"U_peak_V": upk, "f_Hz": F, "phase_deg": -120 * k})
           for k, p in enumerate("abc")]
    els += three_phase_transformer("TR", ("Ha", "Hb", "Hc"), ("La", "Lb", "Lc"), S_MVA=600,
                                   U1_kV=345, U2_kV=213.4, xk_pu=0.18, f_Hz=F,
                                   winding2=winding2)
    els += [Element(f"RL{p}", "R", (f"L{p}", "gnd"), {"R_ohm": 1e7}) for p in "abc"]
    res = simulate(EmtSolver(Netlist(els), dt=20e-6), 0.1, ["Ha.V", "Hb.V", "La.V", "Lb.V"])
    ph = {n: steady_phasor(res.time, res[n], 0.06) for n in res.names}
    return {"hv_ab": ph["Ha.V"] - ph["Hb.V"], "lv_ab": ph["La.V"] - ph["Lb.V"]}


@pytest.mark.req("F1-L02")
@pytest.mark.parametrize(("winding2", "shift_deg"), [("y", 0.0), ("d", -30.0)])
def test_three_phase_ratio_and_vector_group(winding2: str, shift_deg: float) -> None:
    p = _three_phase(winding2)
    ratio = abs(p["lv_ab"]) / abs(p["hv_ab"])
    assert ratio == pytest.approx(213.4 / 345, rel=1e-4)
    shift = np.degrees(np.angle(p["lv_ab"] / p["hv_ab"]))
    assert shift == pytest.approx(shift_deg, abs=0.01)


@pytest.mark.req("F1-L02")
def test_three_phase_short_circuit_current() -> None:
    """LV terminals solidly shorted: I_HV = U1/(sqrt3 x_k Zb) = I_rated / x_k."""
    upk = 345e3 * np.sqrt(2 / 3)
    els = [Element(f"V{p}", "V_ac", (f"H{p}", "gnd"),
                   {"U_peak_V": upk, "f_Hz": F, "phase_deg": -120 * k})
           for k, p in enumerate("abc")]
    els += three_phase_transformer("TR", ("Ha", "Hb", "Hc"), ("La", "Lb", "Lc"), 600, 345,
                                   213.4, 0.18, F, winding2="d")
    els += [Element(f"S{p}", "R", (f"L{p}", "gnd"), {"R_ohm": 1e-6}) for p in "abc"]
    res = simulate(EmtSolver(Netlist(els), dt=20e-6), 0.4, ["TRa.w1.I"])
    i_rated_pk = 600e6 / (np.sqrt(3) * 345e3) * np.sqrt(2)
    i = abs(steady_phasor(res.time, res["TRa.w1.I"], 0.36))
    assert i == pytest.approx(i_rated_pk / 0.18, rel=1e-3)
