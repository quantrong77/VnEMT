"""Bergeron line model: travelling waves, losses, modal coupling (SPEC 6, F2-06), snapshots."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from vnemt.core import EmtSolver, simulate
from vnemt.core.lines import modal_parameters
from vnemt.core.snapshot import load_snapshot
from vnemt.errors import TopologyError
from vnemt.model.netlist import Element, Netlist

LP, CP, LEN = 1e-3, 11e-9, 300.0  # H/km, F/km, km
ZC = math.sqrt(LP / CP)
TAU = LEN * math.sqrt(LP * CP)


def single(u: float = 100.0, r_s: float = ZC, r_load: float = 1e9, r_line: float = 0.0,
           dt: float = 10e-6) -> EmtSolver:
    return EmtSolver(Netlist([
        Element("VS", "V_dc", ("S", "gnd"), {"U_V": u}),
        Element("RS", "R", ("S", "K"), {"R_ohm": r_s}),
        Element("TL", "LINE", ("K", "M"), {"length_km": LEN, "L_H_per_km": LP,
                                           "C_F_per_km": CP, "R_ohm_per_km": r_line}),
        Element("RL", "R", ("M", "gnd"), {"R_ohm": r_load}),
    ]), dt=dt)


def test_modal_parameters_single() -> None:
    el = Element("TL", "LINE", ("K", "M"), {"length_km": LEN, "L_H_per_km": LP, "C_F_per_km": CP})
    _, zc, tau, r = modal_parameters(el)
    assert zc[0] == pytest.approx(ZC) and tau[0] == pytest.approx(TAU) and r[0] == 0.0


@pytest.mark.req("S-01")
def test_lossless_step_into_open_line_with_matched_source() -> None:
    """Matched source: U/2 travels, doubles at the open end at tau; the reflection returns to
    the sending end at 2 tau and is absorbed. tau = 0.995 ms is not a multiple of dt."""
    dt = 10e-6
    res = simulate(single(dt=dt), 4 * TAU, ["K.V", "M.V"])
    t = res.time
    assert np.max(np.abs(res["M.V"][t < TAU - dt])) < 1e-9
    # the 1e9 ohm termination reflects with (1e9 - Zc)/(1e9 + Zc) = 1 - 6e-7
    gamma_r = (1e9 - ZC) / (1e9 + ZC)
    assert np.allclose(res["M.V"][(t > TAU + dt) & (t < 3 * TAU)], 50.0 * (1 + gamma_r),
                       rtol=1e-9)
    assert np.allclose(res["K.V"][(t > dt) & (t < 2 * TAU - dt)], 50.0, rtol=1e-9)
    # the returning front went through two interpolations (at M, then at K): spread <= 2 dt
    assert np.allclose(res["K.V"][t > 2 * TAU + 2 * dt], 50.0 * (1 + gamma_r), rtol=1e-9)
    # arrival instant: the linear interpolation puts the front within one step of tau
    k = np.flatnonzero(res["M.V"] > 50.0)[0]
    assert abs(t[k] - TAU) <= dt


@pytest.mark.req("S-01")
def test_lossy_line_dc_steady_state() -> None:
    r_line, r_load, r_s = 0.02, 200.0, 10.0
    res = simulate(single(r_s=r_s, r_load=r_load, r_line=r_line, dt=20e-6), 0.2,
                   ["RL.I", "TL.k1.I"])
    i_exact = 100.0 / (r_s + r_line * LEN + r_load)
    assert res["RL.I"][-1] == pytest.approx(i_exact, rel=1e-6)
    assert res["TL.k1.I"][-1] == pytest.approx(i_exact, rel=1e-6)


L2 = (1.6e-3, 0.6e-3, 0.6e-3, 1.6e-3)
C2 = (10e-9, -2e-9, -2e-9, 10e-9)


@pytest.mark.req("F2-06")
def test_two_conductor_induced_voltage_on_open_conductor() -> None:
    """Conductor 1 stepped by an ideal source, conductor 2 open at both ends: before any
    reflection returns, v_2 = (Z_0 - Z_1)/(Z_0 + Z_1) U (ground mode Z_0, line mode Z_1)."""
    z0 = math.sqrt((L2[0] + L2[1]) / (C2[0] + C2[1]))
    z1 = math.sqrt((L2[0] - L2[1]) / (C2[0] - C2[1]))
    el = Element("DL", "LINE", ("K1", "K2", "M1", "M2"),
                 {"length_km": LEN, "L_H_per_km": L2, "C_F_per_km": C2})
    _, zc, tau, _ = modal_parameters(el)
    assert sorted(zc) == pytest.approx(sorted([z0, z1]))
    net = Netlist([Element("VS", "V_dc", ("K1", "gnd"), {"U_V": 100.0}), el,
                   Element("R2", "R", ("K2", "gnd"), {"R_ohm": 1e9}),
                   Element("RM1", "R", ("M1", "gnd"), {"R_ohm": 1e9}),
                   Element("RM2", "R", ("M2", "gnd"), {"R_ohm": 1e9})])
    res = simulate(EmtSolver(net, dt=5e-6), 1.5 * float(np.min(tau)), ["K2.V"])
    early = res["K2.V"][(res.time > 10e-6) & (res.time < 1.9 * float(np.min(tau)))]
    assert np.allclose(early, (z0 - z1) / (z0 + z1) * 100.0, rtol=1e-6)


def test_line_parameter_errors() -> None:
    with pytest.raises(TopologyError, match="nhỏ hơn bước thời gian"):
        EmtSolver(Netlist([Element("VS", "V_dc", ("K", "gnd"), {"U_V": 1.0}),
                           Element("TL", "LINE", ("K", "M"), {"length_km": 1.0, "L_H_per_km": LP,
                                                              "C_F_per_km": CP}),
                           Element("R", "R", ("M", "gnd"), {"R_ohm": 1.0})]), dt=20e-6)
    bad = Element("DL", "LINE", ("K1", "K2", "M1", "M2"),
                  {"length_km": 100.0, "L_H_per_km": (1.6e-3, 0.6e-3, 0.6e-3, 1.0e-3),
                   "C_F_per_km": (10e-9, -2e-9, -2e-9, 10e-9)})
    with pytest.raises(TopologyError, match="chéo hóa"):
        modal_parameters(bad)


@pytest.mark.req("S-09")
def test_line_history_in_snapshot(tmp_path: Path) -> None:
    from vnemt.core.snapshot import save_snapshot

    full = simulate(single(), 5 * TAU, ["K.V", "M.V"])
    s1 = single()
    st = s1.initial_state()
    for _ in range(int(2.37 * TAU / s1.dt)):
        st = s1.step(st)
    save_snapshot(s1, st, tmp_path / "s.h5")
    s2 = single()
    rest = simulate(s2, 5 * TAU, ["K.V", "M.V"], start=load_snapshot(s2, tmp_path / "s.h5"))
    k0 = st.step
    for n in ("K.V", "M.V"):
        np.testing.assert_array_equal(full[n][k0:], rest[n])
