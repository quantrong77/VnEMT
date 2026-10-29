"""Control blocks and SRF-PLL (SPEC section 6, S-06, F1-L03)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from vnemt.control import PllSrf
from vnemt.control.blocks import clarke, first_order, pi_step, rate_limit, wrap_2pi
from vnemt.core import EmtSolver, simulate
from vnemt.model.netlist import Element, Netlist


def test_first_order_step_response() -> None:
    T, dt = 0.01, 1e-4
    y, u_prev, ys = 0.0, 0.0, []
    for _ in range(1000):
        y = first_order(y, u_prev, 1.0, T, dt)
        u_prev = 1.0
        ys.append(y)
    # Tustin treats the input step as a ramp over the first sample: exact response delayed dt/2
    t = dt * np.arange(1, 1001) - dt / 2
    assert np.max(np.abs(np.array(ys) - (1 - np.exp(-t / T)))) < 1e-4


def test_pi_integrates_and_antiwindup_releases_immediately() -> None:
    dt, i, e_prev = 1e-3, 0.0, 0.0
    for _ in range(100):  # e = 1 for 0.1 s: I -> Ki * 0.1 (trapezoid, starts from e_prev = 0)
        y, i = pi_step(i, e_prev, 1.0, kp=2.0, ki=10.0, dt=dt)
        e_prev = 1.0
    assert i == pytest.approx(10.0 * (0.1 - dt / 2))
    assert y == pytest.approx(2.0 + i)
    for _ in range(1000):  # saturate at hi = 3: the integrator stops at hi - Kp e = 1
        y, i = pi_step(i, e_prev, 1.0, kp=2.0, ki=10.0, dt=dt, hi=3.0)
    assert y == 3.0 and i == pytest.approx(1.0)
    y, i = pi_step(i, 1.0, -1.0, kp=2.0, ki=10.0, dt=dt, hi=3.0)
    assert y < 0.0  # no windup memory


def test_pi_large_proportional_error_does_not_drag_integrator() -> None:
    """A large error that saturates the output through Kp alone must not move the
    integrator beyond its limits: when the error vanishes the output returns to I."""
    i = 160.0
    y, i = pi_step(i, 0.0, 2.0, kp=150.0, ki=3000.0, dt=2e-5, lo=95.0, hi=165.0)
    assert y == 165.0 and 95.0 <= i <= 165.0
    y, i = pi_step(i, 2.0, 0.0, kp=150.0, ki=3000.0, dt=2e-5, lo=95.0, hi=165.0)
    assert y == pytest.approx(i) and y > 150.0


def test_rate_limit_and_wrap() -> None:
    assert rate_limit(0.0, 10.0, rise=100.0, fall=50.0, dt=0.01) == pytest.approx(1.0)
    assert rate_limit(0.0, -10.0, rise=100.0, fall=50.0, dt=0.01) == pytest.approx(-0.5)
    assert wrap_2pi(-0.1) == pytest.approx(2 * math.pi - 0.1)


def test_clarke_convention() -> None:
    th = 0.7
    a, b, c = (math.sin(th - k * 2 * math.pi / 3) for k in range(3))
    al, be = clarke(a, b, c)
    assert al == pytest.approx(math.sin(th)) and be == pytest.approx(-math.cos(th))


@pytest.mark.req("F1-L03")
@pytest.mark.parametrize(("phase_deg", "f_src"), [(37.0, 50.0), (-120.0, 50.5)])
def test_pll_locks_to_phase_and_frequency(phase_deg: float, f_src: float) -> None:
    els = [Element(f"V{p}", "V_ac", (p, "gnd"),
                   {"U_peak_V": 100.0, "f_Hz": f_src, "phase_deg": phase_deg - 120 * k})
           for k, p in enumerate("abc")]
    els += [Element(f"R{p}", "R", (p, "gnd"), {"R_ohm": 1.0}) for p in "abc"]
    s = EmtSolver(Netlist(els), dt=50e-6)
    res = simulate(s, 0.5, ["PLL.theta", "PLL.f", "PLL.Vm"],
                   controllers=[PllSrf("PLL", "a.V", "b.V", "c.V", f0_Hz=50.0)])
    last = res.time > 0.4
    true = (2 * np.pi * f_src * res.time + np.radians(phase_deg)) % (2 * np.pi)
    err = np.angle(np.exp(1j * (res["PLL.theta"] - true)))[last]
    assert np.max(np.abs(np.degrees(err))) < 0.01
    assert np.max(np.abs(res["PLL.f"][last] - f_src)) < 1e-3
    assert res["PLL.Vm"][-1] == pytest.approx(100.0)


@pytest.mark.req("F1-L03")
def test_epc_fires_late_when_alpha_order_drops_within_a_step() -> None:
    """alpha order 60 -> 20 deg between two steps: the targets jump behind the PLL angle, the
    valves must still fire (late) in that cycle, never miss it."""
    from vnemt.control.base import ControlIO
    from vnemt.control.epc import Epc6

    fired: list[tuple[int, float]] = []

    class Io:
        def fire(self, j: int, t_on: float, t_off: float) -> None:
            fired.append((j, t_on))

    epc = Epc6("E", "PLL", [f"V{i}" for i in range(6)], alpha_signal="a")
    epc._idx = list(range(6))
    x = epc.init_state()
    w, dt = 2 * math.pi * 50, 20e-6
    io = Io()
    t = 0.0
    while t < 0.04:
        alpha = 60.0 if t < 0.0251 else 20.0
        th = wrap_2pi(w * t)
        epc.update(t, dt, x, np.array([th, w, alpha]), io)  # type: ignore[arg-type]
        t += dt
    for j in range(6):
        times = [tf for jj, tf in fired if jj == j and tf > 0.005]
        assert all(np.diff(times) < 1.2 / 50), (j, np.diff(times))
    _ = ControlIO  # interface used by the real solver
