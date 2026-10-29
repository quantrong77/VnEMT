"""Analytic verification of the linear Dommel solver (SPEC S-01, S-02; level V1/V2)."""

from __future__ import annotations

import numpy as np
import pytest

from vnemt.core import EmtSolver, simulate
from vnemt.errors import TopologyError
from vnemt.model.netlist import Element, Netlist

U, R, L, C = 1000.0, 10.0, 0.01, 10e-6


def rlc_netlist() -> Netlist:
    return Netlist(
        [
            Element("VS", "V_dc", ("N1", "gnd"), {"U_V": U}),
            Element("R1", "R", ("N1", "N2"), {"R_ohm": R}),
            Element("L1", "L", ("N2", "N3"), {"L_H": L}),
            Element("C1", "C", ("N3", "gnd"), {"C_F": C}),
        ]
    )


def rlc_exact(t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a = R / (2 * L)
    wd = np.sqrt(1 / (L * C) - a**2)
    i = U / (wd * L) * np.exp(-a * t) * np.sin(wd * t)
    vc = U * (1 - np.exp(-a * t) * (np.cos(wd * t) + a / wd * np.sin(wd * t)))
    return i, vc


def rel_err(x: np.ndarray, ref: np.ndarray) -> float:
    return float(np.max(np.abs(x - ref)) / np.max(np.abs(ref)))


@pytest.mark.req("S-01")
def test_series_rlc_dc_step_within_0p1_percent() -> None:
    res = simulate(EmtSolver(rlc_netlist(), dt=1e-6), t_end=0.01,
                   signals=["L1.I", "C1.V", "N3.V"])
    i, vc = rlc_exact(res.time)
    assert rel_err(res["L1.I"], i) < 1e-3
    assert rel_err(res["C1.V"], vc) < 1e-3
    np.testing.assert_allclose(res["N3.V"], res["C1.V"])


@pytest.mark.req("S-02")
def test_no_cda_start_lags_half_step() -> None:
    """Without CDA the step start assumes v_L(0) = 0 instead of v_L(0+) = U, which delays
    the trapezoidal solution by dt/2. Shifting the analytic curve by dt/2 removes the error."""
    dt = 1e-6
    res = simulate(EmtSolver(rlc_netlist(), dt=dt, cda=False), t_end=0.01, signals=["L1.I"])
    assert rel_err(res["L1.I"], rlc_exact(res.time)[0]) > 1e-3
    t = np.maximum(res.time - dt / 2, 0.0)
    assert rel_err(res["L1.I"], rlc_exact(t)[0]) < 1e-5


@pytest.mark.req("S-02")
def test_trapezoidal_second_order_convergence() -> None:
    errs = []
    for dt in (50e-6, 25e-6, 12.5e-6):
        res = simulate(EmtSolver(rlc_netlist(), dt=dt), t_end=0.01, signals=["L1.I"])
        errs.append(rel_err(res["L1.I"], rlc_exact(res.time)[0]))
    ratios = [errs[0] / errs[1], errs[1] / errs[2]]
    assert all(3.5 < r < 4.5 for r in ratios), (errs, ratios)


def test_source_current_equals_loop_current() -> None:
    res = simulate(EmtSolver(rlc_netlist(), dt=5e-6), t_end=0.005,
                   signals=["VS.I", "R1.I", "VS.V"])
    np.testing.assert_allclose(res["VS.I"], res["R1.I"], atol=1e-9)
    assert np.all(res["VS.V"] == U)


@pytest.mark.req("S-01")
def test_rl_ac_energisation_norton_source() -> None:
    um, f, rs, lv, phi = 1000.0, 50.0, 1.0, 0.05, 0.3
    net = Netlist(
        [
            Element("VS", "V_ac", ("N1", "gnd"),
                    {"U_peak_V": um, "f_Hz": f, "phase_deg": np.rad2deg(phi), "R_ohm": rs}),
            Element("L1", "L", ("N1", "gnd"), {"L_H": lv}),
        ]
    )
    res = simulate(EmtSolver(net, dt=10e-6), t_end=0.1, signals=["L1.I", "VS.I"])
    w = 2 * np.pi * f
    z, th, tau = np.hypot(rs, w * lv), np.arctan2(w * lv, rs), lv / rs
    t = res.time
    i = um / z * (np.sin(w * t + phi - th) - np.sin(phi - th) * np.exp(-t / tau))
    assert rel_err(res["L1.I"], i) < 1e-3
    np.testing.assert_allclose(res["VS.I"], res["L1.I"], atol=1e-9)


def test_ideal_and_norton_parallel_current_source_agree() -> None:
    """Norton source (U, R) equals current source U/R in parallel with R."""
    a = Netlist([Element("VS", "V_dc", ("A", "gnd"), {"U_V": 100.0, "R_ohm": 5.0}),
                 Element("RL", "R", ("A", "gnd"), {"R_ohm": 20.0}),
                 Element("C1", "C", ("A", "gnd"), {"C_F": 1e-6})])
    b = Netlist([Element("IS", "I_dc", ("A", "gnd"), {"I_A": 20.0}),
                 Element("RS", "R", ("A", "gnd"), {"R_ohm": 5.0}),
                 Element("RL", "R", ("A", "gnd"), {"R_ohm": 20.0}),
                 Element("C1", "C", ("A", "gnd"), {"C_F": 1e-6})])
    ra = simulate(EmtSolver(a, dt=1e-6), 1e-4, ["A.V"])
    rb = simulate(EmtSolver(b, dt=1e-6), 1e-4, ["A.V"])
    np.testing.assert_allclose(ra["A.V"], rb["A.V"], rtol=1e-12, atol=1e-12)
    assert ra["A.V"][-1] == pytest.approx(80.0, rel=1e-6)  # tau = 4 us


def test_ramp_source() -> None:
    net = Netlist([Element("VS", "V_dc", ("A", "gnd"), {"U_V": 10.0, "ramp_s": 1e-3}),
                   Element("R1", "R", ("A", "gnd"), {"R_ohm": 1.0})])
    res = simulate(EmtSolver(net, dt=1e-4), 2e-3, ["A.V"])
    np.testing.assert_allclose(res["A.V"], np.minimum(res.time / 1e-3, 1.0) * 10.0, atol=1e-12)


def test_floating_node_is_reported() -> None:
    net = Netlist([Element("VS", "V_dc", ("A", "gnd"), {"U_V": 1.0}),
                   Element("R1", "R", ("A", "gnd"), {"R_ohm": 1.0}),
                   Element("C1", "C", ("X", "Y"), {"C_F": 1e-6}),
                   Element("R2", "R", ("Y", "X"), {"R_ohm": 1.0})])
    with pytest.raises(TopologyError, match="nút nổi"):
        EmtSolver(net, dt=1e-6)


def test_floating_ideal_source_is_rejected() -> None:
    net = Netlist([Element("VS", "V_dc", ("A", "B"), {"U_V": 1.0}),
                   Element("R1", "R", ("A", "gnd"), {"R_ohm": 1.0}),
                   Element("R2", "R", ("B", "gnd"), {"R_ohm": 1.0})])
    with pytest.raises(TopologyError, match="R_ohm"):
        EmtSolver(net, dt=1e-6)


def test_negative_terminal_ideal_source() -> None:
    net = Netlist([Element("VS", "V_dc", ("gnd", "A"), {"U_V": 10.0}),
                   Element("R1", "R", ("A", "gnd"), {"R_ohm": 2.0})])
    res = simulate(EmtSolver(net, dt=1e-6), 1e-5, ["A.V", "VS.I", "R1.I"])
    assert res["A.V"][-1] == pytest.approx(-10.0)
    assert res["R1.I"][-1] == pytest.approx(-5.0)
    assert res["VS.I"][-1] == pytest.approx(5.0)
