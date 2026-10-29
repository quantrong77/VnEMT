"""Thyristor model (SPEC S-12): gating, holding current, t_q / commutation-failure marker."""

from __future__ import annotations

import numpy as np
import pytest

from vnemt.core import EmtSolver, simulate
from vnemt.model.netlist import Element, Netlist

F, UM, R = 50.0, 1000.0, 10.0
W = 2 * np.pi * F


def half_wave(**valve: float) -> EmtSolver:
    net = Netlist([
        Element("VS", "V_ac", ("A", "gnd"), {"U_peak_V": UM, "f_Hz": F}),
        Element("T1", "T", ("A", "B"), {"R_on_ohm": 1e-6, "R_off_ohm": 1e9, **valve}),
        Element("R1", "R", ("B", "gnd"), {"R_ohm": R}),
    ])
    return EmtSolver(net, dt=20e-6)


def run_fired(s: EmtSolver, t_on: float, t_off: float, t_end: float = 0.02):
    st = s.initial_state()
    s.fire(st, s.switch_index("T1"), t_on, t_off)
    return simulate(s, t_end, ["T1.I"], start=st)


@pytest.mark.req("S-12")
def test_no_conduction_without_gate_pulse() -> None:
    s = half_wave()
    res = simulate(s, 0.04, ["T1.I"])
    assert np.max(np.abs(res["T1.I"])) < 1e-5 and not res.events


@pytest.mark.req("S-12")
def test_fires_at_off_grid_gate_instant_and_turns_off_at_zero() -> None:
    alpha = np.radians(47.3)
    res = run_fired(half_wave(), alpha / W, alpha / W + 0.002)
    on = [t for t, i, s in res.events if s]
    off = [t for t, i, s in res.events if not s]
    assert on[0] == pytest.approx(alpha / W, abs=1e-12)
    assert off[0] == pytest.approx(0.5 / F, abs=0.01 * 20e-6)
    exact = np.where((res.time > alpha / W) & (res.time < 0.01), UM / R * np.sin(W * res.time), 0)
    assert np.max(np.abs(res["T1.I"] - exact)) < 1e-3 * UM / R


@pytest.mark.req("S-12")
def test_gate_window_before_forward_voltage_waits() -> None:
    """Pulse starts while v_AK < 0 (t = 15 ms); the valve fires when v_AK crosses 0 at 20 ms."""
    res = run_fired(half_wave(), 0.015, 0.022, t_end=0.03)
    assert res.events[0][0] == pytest.approx(0.02, abs=0.01 * 20e-6)


@pytest.mark.req("S-12")
def test_holding_current() -> None:
    ih = 20.0  # turn-off when UM sin(wt)/R = I_H on the falling half
    res = run_fired(half_wave(I_H_A=ih), 0.001, 0.003)
    t_off = next(t for t, i, s in res.events if not s)
    expected = (np.pi - np.arcsin(ih * R / UM)) / W
    assert t_off == pytest.approx(expected, abs=0.01 * 20e-6)


@pytest.mark.req("S-12")
def test_forward_voltage_marker_after_turn_off() -> None:
    """After turn-off at 10 ms the anode voltage is negative until the next cycle (20 ms)."""
    res = run_fired(half_wave(), 0.001, 0.003, t_end=0.025)
    fwd = [t for t, i, k in res.markers if k == "fwd"]
    assert fwd and fwd[0] == pytest.approx(0.02, abs=1e-7)
