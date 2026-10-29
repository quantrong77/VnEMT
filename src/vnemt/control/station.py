"""Station-level slow controls: converter transformer tap changer (F5-03) and reactive power
control by filter switching (F5-05).

Tap changer control (one per station, acting on all its converter transformer units)::

    rectifier:  keep alpha in [alpha_lo, alpha_hi]
    inverter:   keep Ud in [ud_ref - ud_band, ud_ref + ud_band]   (pu)

A deviation that lasts ``t_delay_s`` moves the tap by one step (``step_pct`` of the ratio);
two moves are at least ``t_min_s`` apart; the position stays in ``[steps_min, steps_max]``.
Both controls act only from ``t_enable_s`` on (released after start-up, like station
sequences do; before that the start-up transient would move taps and filters).
Raising the tap factor increases the transformer ratio ``a = U1 tap / U2`` and so lowers the
valve-side voltage: too large alpha (or Ud) -> tap up. The band must be wider than the effect
of one step to avoid hunting (about 2.7 deg of alpha per 1.25 % step at alpha = 15 deg).

Reactive power control (one per station end, switching the filter groups of all poles of
that end, in station order): the reactive power the end draws from the AC system,
``Q = 1.5 (v_beta i_alpha - v_alpha i_beta)`` with the bus voltages and the AC system currents
towards the bus (p-q theory, positive = drawn from the system), filtered with ``T_q_s``. If
``Q > band`` for ``t_delay_s`` the next open filter group of the station is switched in; if
``Q < -band`` the last closed one is switched out (breakers open at current zero). After a
switching the controller is locked for ``t_lock_s`` (anti-hunting); ``band`` should exceed half
the size of one group.

Reference: J. Arrillaga, *High Voltage Direct Current Transmission*, 2nd ed., IEE, 1998,
ch. 5 and 7; IEC TR 62001-1 (filter switching).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from vnemt.control.base import ControlIO, Controller
from vnemt.control.blocks import clarke, first_order
from vnemt.core.solver import EmtSolver, FloatArray


class TapChangerControl(Controller):
    """Outputs: ``step`` (tap position), ``factor`` (ratio factor)."""

    def __init__(self, id: str, signal: str, transformers: Sequence[str], role: str,
                 cfg: Mapping[str, Any]) -> None:
        super().__init__(id)
        self.sig, self.units, self.role = signal, list(transformers), role
        self.step_pct = float(cfg.get("step_pct", 1.25))
        lo, hi = cfg.get("steps", [-10, 10])
        self.smin, self.smax = int(lo), int(hi)
        self.t_delay = float(cfg.get("t_delay_s", 5.0))
        self.t_min = float(cfg.get("t_min_s", 5.0))
        self.t_enable = float(cfg.get("t_enable_s", 0.0))
        if role == "rectifier":
            self.lo, self.hi = (float(x) for x in cfg.get("alpha_band_deg", [12.5, 17.5]))
        else:
            ref, band = float(cfg["ud_ref_pu"]), float(cfg.get("ud_band_pu", 0.0125))
            self.lo, self.hi = ref - band, ref + band
        self._j: list[int] = []

    def inputs(self) -> list[str]:
        return [self.sig]

    def outputs(self) -> list[tuple[str, str]]:
        return [("step", "-"), ("factor", "-")]

    def init_state(self) -> FloatArray:
        return np.array([0.0, math.nan, -1e9])  # [step, t_out_of_band, t_last_move]

    def bind(self, solver: EmtSolver) -> None:
        self._j = [solver.transformer_index(u) for u in self.units]

    def update(self, t: float, dt: float, x: FloatArray, u: FloatArray,
               io: ControlIO) -> FloatArray:
        v = float(u[0])
        move = 1 if v > self.hi else (-1 if v < self.lo else 0)
        if t < self.t_enable:
            move = 0
        if move == 0:
            x[1] = math.nan
        elif math.isnan(x[1]):
            x[1] = t
        elif t - x[1] >= self.t_delay and t - x[2] >= self.t_min:
            k = int(x[0]) + move
            if self.smin <= k <= self.smax:
                x[0], x[2] = k, t
                for j in self._j:
                    io.set_tap(j, 1.0 + k * self.step_pct / 100.0)
            x[1] = math.nan
        return np.array([x[0], 1.0 + x[0] * self.step_pct / 100.0])


class ReactivePowerControl(Controller):
    """Outputs: ``Q`` [Mvar] drawn from the AC system (filtered), ``groups_on``."""

    def __init__(self, id: str, bus: Sequence[str], sys_currents: Sequence[str],
                 groups: Sequence[Sequence[str]], initially_on: Sequence[bool],
                 cfg: Mapping[str, Any]) -> None:
        super().__init__(id)
        self.bus, self.cur = list(bus), list(sys_currents)
        self.groups, self.on0 = [list(g) for g in groups], list(initially_on)
        self.band = float(cfg["band_Mvar"]) * 1e6
        self.t_delay = float(cfg.get("t_delay_s", 0.1))
        self.t_lock = float(cfg.get("t_lock_s", 0.5))
        self.t_q = float(cfg.get("T_q_s", 0.02))
        self.t_enable = float(cfg.get("t_enable_s", 0.0))
        self._j: list[list[int]] = []

    def inputs(self) -> list[str]:
        return self.bus + self.cur

    def outputs(self) -> list[tuple[str, str]]:
        return [("Q", "Mvar"), ("groups_on", "-")]

    def init_state(self) -> FloatArray:
        # [Q_f, Q_prev, t_out_of_band, t_last_switch, on flags per group]
        return np.array([0.0, 0.0, math.nan, -1e9] + [float(b) for b in self.on0])

    def bind(self, solver: EmtSolver) -> None:
        self._j = [[solver.switch_index(s) for s in g] for g in self.groups]

    def update(self, t: float, dt: float, x: FloatArray, u: FloatArray,
               io: ControlIO) -> FloatArray:
        va, vb = clarke(*(float(v) for v in u[0:3]))
        ia, ib = clarke(*(float(i) for i in u[3:6]))
        q = 1.5 * (vb * ia - va * ib)
        x[0] = first_order(float(x[0]), float(x[1]), q, self.t_q, dt)
        x[1] = q
        on = x[4:]
        want = 1 if x[0] > self.band else (-1 if x[0] < -self.band else 0)
        if want == 0 or t - x[3] < self.t_lock or t < self.t_enable:
            x[2] = math.nan
        elif math.isnan(x[2]):
            x[2] = t
        elif t - x[2] >= self.t_delay:
            k = (next((i for i, b in enumerate(on) if not b), None) if want > 0 else
                 next((i for i in range(len(on) - 1, -1, -1) if on[i]), None))
            if k is not None:
                for j in self._j[k]:
                    io.switch(j, want > 0, t)
                on[k] = 1.0 if want > 0 else 0.0
                x[3] = t
            x[2] = math.nan
        return np.array([x[0] / 1e6, float(np.sum(on))])
