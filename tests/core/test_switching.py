"""Switching, interpolation, CDA and LU caching (SPEC S-02, S-04, S-05, S-11, S-13; V1, V2)."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.optimize import brentq

from vnemt.core import EmtSolver, simulate
from vnemt.errors import TopologyError
from vnemt.model.netlist import Element, Netlist

F = 50.0
W = 2 * np.pi * F


def E(eid: str, kind: str, k: str, m: str, **p: float | tuple[float, ...]) -> Element:
    return Element(eid, kind, (k, m), p)  # type: ignore[arg-type]


def first_event(res, eid: str, on: bool, after: float = 0.0) -> float:
    return next(t for t, i, s in res.events if i == eid and s is on and t > after)


# ---------------------------------------------------------------- S-02 CDA
def _interrupt_inductor(cda: bool, r_off: float, dt: float = 50e-6) -> np.ndarray:
    net = Netlist([
        E("VS", "V_dc", "A", "gnd", U_V=100.0),
        E("R1", "R", "A", "B", R_ohm=10.0),
        E("S1", "SW", "B", "C", closed=1.0, t_open_s=0.05, R_off_ohm=r_off),
        E("L1", "L", "C", "gnd", L_H=0.1),
    ])
    res = simulate(EmtSolver(net, dt=dt, cda=cda), 0.06, ["L1.V"])
    out: np.ndarray = res["L1.V"][res.time > 0.0502]
    return out


@pytest.mark.req("S-02")
@pytest.mark.parametrize("r_off", [1e6, 1e9])
def test_inductor_current_interruption_cda(r_off: float) -> None:
    """Opening a switch in series with L (i0 = 10 A) forces i_L -> 0 through R_off.

    Exact solution: v_L = -i0 R_off exp(-t R_off / L), i.e. ~0 after 1 us. The trapezoidal
    rule alone gives a sustained alternating v_L of tens of kV. CDA (two backward-Euler half
    steps) damps the stiff L-R_off mode by (1 + x)^-2, x = dt R_off / (2L); the remainder
    still alternates under the trapezoidal rule with amplitude ~ 4 i0 L^2 / (dt^2 R_off).
    """
    i0, lv, dt = 10.0, 0.1, 50e-6
    v_trap = _interrupt_inductor(False, r_off)
    v_cda = _interrupt_inductor(True, r_off)
    assert np.all(np.sign(v_trap[1:]) != np.sign(v_trap[:-1]))
    assert np.min(np.abs(v_trap)) > 1e3
    residual = 4 * i0 * lv**2 / (dt**2 * r_off)
    assert np.max(np.abs(v_cda)) <= residual * 1.05  # SPEC S-02 (r3)
    assert np.max(np.abs(v_cda)) == pytest.approx(residual, rel=0.05)
    assert np.max(np.abs(v_cda)) < np.max(np.abs(v_trap)) / 200
    if r_off >= 1e9:
        assert np.max(np.abs(v_cda)) <= 0.01 * 100.0  # <= 1 % of the 100 V source


# ------------------------------------------------------------ S-04 interpolation
@pytest.mark.req("S-04")
@pytest.mark.parametrize("dt", [20e-6, 50e-6])
def test_half_wave_rl_rectifier_extinction_time_within_1pct_dt(dt: float) -> None:
    """Diode + R-L from Um sin(wt): i = Um/Z [sin(wt - th) + sin(th) e^(-t/tau)], i(beta) = 0."""
    um, r, lv = 1000.0, 10.0, 0.05
    net = Netlist([
        E("VS", "V_ac", "A", "gnd", U_peak_V=um, f_Hz=F),
        E("D1", "D", "A", "B", R_on_ohm=1e-6, R_off_ohm=1e9),
        E("R1", "R", "B", "C", R_ohm=r),
        E("L1", "L", "C", "gnd", L_H=lv),
    ])
    res = simulate(EmtSolver(net, dt=dt), 0.03, ["L1.I"])
    z, th, tau = np.hypot(r, W * lv), np.arctan2(W * lv, r), lv / r

    def i(t: float) -> float:
        return float(um / z * (np.sin(W * t - th) + np.sin(th) * np.exp(-t / tau)))

    t_beta = brentq(i, 0.5 / F, 1.0 / F)
    t_off = first_event(res, "D1", on=False)
    assert abs(t_off - t_beta) < 0.01 * dt
    # re-ignition exactly at the next positive zero crossing of the source
    assert abs(first_event(res, "D1", on=True, after=t_off) - 1 / F) < 0.01 * dt


@pytest.mark.req("S-04")
def test_rc_charge_with_off_grid_switch_closing() -> None:
    t1, u, r, c = 1.234567e-3, 100.0, 100.0, 10e-6
    net = Netlist([
        E("VS", "V_dc", "A", "gnd", U_V=u),
        E("S1", "SW", "A", "B", t_close_s=t1, R_on_ohm=1e-9),
        E("R1", "R", "B", "C", R_ohm=r),
        E("C1", "C", "C", "gnd", C_F=c),
    ])
    res = simulate(EmtSolver(net, dt=20e-6), 0.006, ["C1.V"])
    exact = np.where(res.time > t1, u * (1 - np.exp(-(res.time - t1) / (r * c))), 0.0)
    assert np.max(np.abs(res["C1.V"] - exact)) / u < 1e-3
    assert res.events[0][0] == pytest.approx(t1, abs=1e-12)


@pytest.mark.req("S-04")
def test_breaker_opens_at_next_current_zero() -> None:
    """Pure sinusoidal current (closing at the angle without DC offset) zeros at w t = k pi."""
    um, r, lv, dt = 1000.0, 5.0, 0.03, 30e-6
    th = np.arctan2(W * lv, r)
    net = Netlist([
        E("VS", "V_ac", "A", "gnd", U_peak_V=um, f_Hz=F, phase_deg=np.rad2deg(th)),
        E("CB", "SW", "A", "B", closed=1.0, t_open_s=0.0123, open_at_zero=1.0,
          R_on_ohm=1e-6, R_off_ohm=1e9),
        E("R1", "R", "B", "C", R_ohm=r),
        E("L1", "L", "C", "gnd", L_H=lv),
    ])
    res = simulate(EmtSolver(net, dt=dt), 0.04, ["CB.I", "CB.on"])
    t_open = first_event(res, "CB", on=False)
    assert abs(t_open - 0.02) < 0.01 * dt  # first zero after the 12.3 ms command
    after = res.time > t_open + dt
    assert np.max(np.abs(res["CB.I"][after])) < 1e-3
    assert np.all(res["CB.on"][after] == 0.0)


# ------------------------------------------------- 6-pulse diode bridge (V1, V2)
U_LL, LC, LD, RD = 10e3, 5e-3, 1.0, 50.0


def bridge(dt: float, cda: bool = True) -> EmtSolver:
    upk = U_LL * np.sqrt(2 / 3)
    els = []
    for ph, ang in zip("abc", (0.0, -120.0, 120.0), strict=True):
        els += [
            E(f"V{ph}", "V_ac", f"S{ph}", "gnd", U_peak_V=upk, f_Hz=F, phase_deg=ang),
            E(f"L{ph}", "L", f"S{ph}", ph.upper(), L_H=LC),
        ]
    # valve numbering in firing order: D1 a+, D3 b+, D5 c+, D4 a-, D6 b-, D2 c-
    for d, ph, up in (("D1", "A", True), ("D3", "B", True), ("D5", "C", True),
                      ("D4", "A", False), ("D6", "B", False), ("D2", "C", False)):
        els.append(E(d, "D", ph, "P") if up else E(d, "D", "N", ph))
    els += [E("LD", "L", "P", "X", L_H=LD), E("RD", "R", "X", "N", R_ohm=RD)]
    return EmtSolver(Netlist(els), dt=dt, cda=cda)


def bridge_ud_id(dt: float, t_end: float = 0.4) -> tuple[float, float, object]:
    res = simulate(bridge(dt), t_end, ["P.V", "N.V", "LD.I"])
    last = res.time > t_end - 2 / F  # two full cycles
    ud = float(np.mean((res["P.V"] - res["N.V"])[last]))
    idc = float(np.mean(res["LD.I"][last]))
    return ud, idc, res


@pytest.mark.req("S-04")
def test_diode_bridge_average_voltage_matches_commutation_formula() -> None:
    """Ud = (3 sqrt2 / pi) U_LL - (3/pi) w Lc Id   (alpha = 0), error < 1 %."""
    ud, idc, res = bridge_ud_id(20e-6)
    ud_formula = 3 * np.sqrt(2) / np.pi * U_LL - 3 / np.pi * W * LC * idc
    assert abs(ud - ud_formula) / ud_formula < 0.01
    assert idc == pytest.approx(ud / RD, rel=1e-3)
    # overlap check: cos(mu) = 1 - 2 w Lc Id / (sqrt2 U_LL)
    mu = np.arccos(1 - 2 * W * LC * idc / (np.sqrt(2) * U_LL))
    d1_on = first_event(res, "D1", on=True, after=0.36)
    d3_on = first_event(res, "D3", on=True, after=d1_on)
    d1_off = first_event(res, "D1", on=False, after=d3_on)
    mu_sim = W * (d1_off - d3_on)
    assert np.rad2deg(abs(mu_sim - mu)) < 0.5


@pytest.mark.req("S-04")
def test_diode_bridge_has_no_chatter() -> None:
    """Steady state: each of the six diodes switches on once and off once per cycle."""
    _, _, res = bridge_ud_id(20e-6, t_end=0.2)
    window = [e for e in res.events if 0.16 < e[0] <= 0.18]
    assert len(window) == 12
    for d in ("D1", "D2", "D3", "D4", "D5", "D6"):
        assert sum(1 for e in window if e[1] == d) == 2


@pytest.mark.req("S-05")
def test_lu_factorisations_are_cached_per_switch_state() -> None:
    s = bridge(20e-6)
    simulate(s, 0.2, ["P.V"])
    assert s.stats.events > 100
    assert s.stats.lu_factorizations <= 20


@pytest.mark.slow
@pytest.mark.req("S-04")
def test_diode_bridge_converges_when_dt_halves() -> None:
    """V2: Ud error decreases as dt is halved 50 -> 25 -> 12.5 us."""
    ref, _, _ = bridge_ud_id(2.5e-6)
    errs = [abs(bridge_ud_id(dt)[0] - ref) for dt in (50e-6, 25e-6, 12.5e-6)]
    assert errs[0] > errs[1] > errs[2]
    assert errs[0] / ref < 2e-3


# ----------------------------------------------------------------- validation
def test_switch_resistances_must_be_ordered() -> None:
    net = Netlist([E("VS", "V_dc", "A", "gnd", U_V=1.0),
                   E("S1", "SW", "A", "gnd", R_on_ohm=10.0, R_off_ohm=1.0)])
    with pytest.raises(TopologyError, match="R_on_ohm < R_off_ohm"):
        EmtSolver(net, dt=1e-6)
