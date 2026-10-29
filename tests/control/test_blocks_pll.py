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
    for _ in range(1000):  # saturate at hi = 3
        y, i = pi_step(i, e_prev, 1.0, kp=2.0, ki=10.0, dt=dt, hi=3.0)
    assert y == 3.0 and i == pytest.approx(1.0)
    y, i = pi_step(i, 1.0, -1.0, kp=2.0, ki=10.0, dt=dt, hi=3.0)
    assert y < 0.0  # no windup memory


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
