"""Saturable inductor (two-slope), transformer taps and controller switch commands (F5-02)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from vnemt.control.base import ControlIO, Controller
from vnemt.core import EmtSolver, simulate
from vnemt.core.solver import FloatArray
from vnemt.errors import TopologyError
from vnemt.model.netlist import Element, Netlist

F = 50.0
W = 2 * math.pi * F


@pytest.mark.req("F5-02")
def test_two_slope_inductor_peak_current_from_flux() -> None:
    """v = Um sin(wt) switched at a zero: lambda = (Um/w)(1 - cos wt), peak 2 Um/w.
    i = lambda/Lm below the knee, i_k + (lambda - lambda_k)/Lsat above."""
    um, lm, ls, ik = 100.0, 1.0, 0.01, 0.4
    net = Netlist([Element("VS", "V_ac", ("A", "gnd"), {"U_peak_V": um, "f_Hz": F}),
                   Element("LM", "LSAT", ("A", "gnd"), {"L_H": lm, "Lsat_H": ls, "I_knee_A": ik})])
    res = simulate(EmtSolver(net, dt=10e-6), 0.06, ["LM.I", "LM.on"])
    lam = um / W * (1 - np.cos(W * res.time))
    lk = lm * ik
    exact = np.where(lam <= lk, lam / lm, ik + (lam - lk) / ls)
    assert np.max(res["LM.I"]) == pytest.approx(ik + (2 * um / W - lk) / ls, rel=2e-3)
    assert np.max(np.abs(res["LM.I"] - exact)) / np.max(exact) < 3e-3
    # enters and leaves saturation once per cycle
    ev = [(round(t, 4), s) for t, i, s in res.events if i == "LM"]
    assert [s for _, s in ev] == [True, False, True, False, True, False]


def test_saturable_parameters_validated() -> None:
    net = Netlist([Element("VS", "V_dc", ("A", "gnd"), {"U_V": 1.0}),
                   Element("LM", "LSAT", ("A", "gnd"), {"L_H": 0.1, "Lsat_H": 0.2, "I_knee_A": 1})])
    with pytest.raises(TopologyError, match="Lsat_H < L_H"):
        EmtSolver(net, dt=1e-5)


class _Script(Controller):
    """Applies one action at ``t_act``."""

    def __init__(self, act: str, target: str, value: float, t_act: float) -> None:
        super().__init__("SCR")
        self.act, self.target, self.value, self.t_act = act, target, value, t_act
        self._j = -1

    def inputs(self) -> list[str]:
        return []

    def outputs(self) -> list[tuple[str, str]]:
        return []

    def init_state(self) -> FloatArray:
        return np.zeros(1)

    def bind(self, solver: EmtSolver) -> None:
        self._j = (solver.transformer_index(self.target) if self.act == "tap"
                   else solver.switch_index(self.target))

    def update(self, t: float, dt: float, x: FloatArray, u: FloatArray,
               io: ControlIO) -> FloatArray:
        if t >= self.t_act and not x[0]:
            x[0] = 1.0
            if self.act == "tap":
                io.set_tap(self._j, self.value)
            else:
                io.switch(self._j, bool(self.value), t + 1e-4)
        return np.zeros(0)


def _xf_net() -> Netlist:
    return Netlist([
        Element("VS", "V_ac", ("A", "gnd"), {"U_peak_V": 1000.0, "f_Hz": F}),
        Element("T1", "XF1", ("A", "gnd", "B", "gnd"), {"U1_V": 4.0, "U2_V": 1.0, "L_k_H": 0.01}),
        Element("RL", "R", ("B", "gnd"), {"R_ohm": 50.0}),
    ])


@pytest.mark.req("F5-02")
def test_tap_change_scales_secondary_voltage() -> None:
    res = simulate(EmtSolver(_xf_net(), dt=20e-6), 0.3, ["B.V", "T1.w1.I", "T1.w2.I"],
                   controllers=[_Script("tap", "T1", 1.1, 0.1)])

    def amp(t0: float, t1: float) -> float:
        m = (res.time > t0) & (res.time < t1)
        return float(np.max(np.abs(res["B.V"][m])))

    a0, a1 = 4.0, 4.4
    exact = [1000.0 * a / math.hypot(a * a * 50.0, W * 0.01) * 50.0 for a in (a0, a1)]
    assert amp(0.05, 0.1) == pytest.approx(exact[0], rel=2e-3)
    assert amp(0.25, 0.3) == pytest.approx(exact[1], rel=2e-3)
    after = res.time > 0.1
    np.testing.assert_allclose(res["T1.w2.I"][after], -a1 * res["T1.w1.I"][after], atol=1e-6)


def test_controller_switch_command() -> None:
    net = Netlist([Element("VS", "V_dc", ("A", "gnd"), {"U_V": 10.0}),
                   Element("S1", "SW", ("A", "B"), {"R_off_ohm": 1e9}),
                   Element("RL", "R", ("B", "gnd"), {"R_ohm": 1.0})])
    res = simulate(EmtSolver(net, dt=1e-4), 0.02, ["RL.I"],
                   controllers=[_Script("switch", "S1", 1.0, 0.01)])
    assert res.events[0][1] == "S1" and res.events[0][0] == pytest.approx(0.0101)
    assert res["RL.I"][-1] == pytest.approx(10.0, rel=1e-3)
    assert np.max(np.abs(res["RL.I"][res.time < 0.01])) < 1e-6
