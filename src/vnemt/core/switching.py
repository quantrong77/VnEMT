"""Two-state switching devices: timed switch/breaker ``SW`` and diode ``D`` (SPEC S-11, S-13).

Each device is a resistive branch with ``G = 1/R_on`` (on) or ``1/R_off`` (off). A diode in
the on state also carries a forward drop ``V_f``: ``i = (v - V_f)/R_on``, i.e. a Norton
term ``h = -V_f/R_on``.

Switching instants inside a step are located by linear interpolation of an indicator
between the two ends of the step (SPEC S-04):

========================  ==========================  =========================
Device / state            Indicator                   Event when
========================  ==========================  =========================
diode on                  branch current ``i``        ``i`` falls below 0
diode off                 ``v_AK - V_f``              rises above 0
timed switch              ``t - t_cmd``               command time reached
breaker armed to open     branch current ``i``        ``i`` changes sign
========================  ==========================  =========================

A breaker with ``open_at_zero`` is *armed* at its open command time (a non-topological event)
and opens at the next current zero.

A switch that interrupts an inductor current should use ``R_off >= 1e9`` ohm: the residual
numerical oscillation after CDA is about ``4 i0 L^2 / (dt^2 R_off)`` (SPEC S-02, note 5.1.1).

Reference: A. M. Gole, I. T. Fernando, G. D. Irwin, O. B. Nayak, "Modeling of power
electronic apparatus: additional interpolation issues", IPST 1997.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from vnemt.errors import TopologyError
from vnemt.model.netlist import Element

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]

DEV_SWITCH, DEV_DIODE = 0, 1
R_ON_DEFAULT, R_OFF_DEFAULT = 1e-3, 1e6


@dataclass
class SwitchSet:
    """Static description of all switching devices (indices into the branch arrays)."""

    ids: list[str]
    pos: IntArray  # branch index of each device
    dev: IntArray  # DEV_SWITCH / DEV_DIODE
    g_on: FloatArray
    g_off: FloatArray
    vf: FloatArray
    open_at_zero: BoolArray
    initial_on: BoolArray
    # schedule: per device, sorted command times and target states (True = close)
    sched_t: list[FloatArray]
    sched_on: list[BoolArray]

    @classmethod
    def from_elements(cls, els: list[Element], pos: list[int]) -> SwitchSet:
        g_on, g_off, sched_t, sched_on = [], [], [], []
        for el in els:
            r_on, r_off = el.p("R_on_ohm", R_ON_DEFAULT), el.p("R_off_ohm", R_OFF_DEFAULT)
            if not 0.0 < r_on < r_off:
                raise TopologyError(
                    f"khóa '{el.id}': cần 0 < R_on_ohm < R_off_ohm (nhận {r_on}, {r_off})"
                )
            g_on.append(1.0 / r_on)
            g_off.append(1.0 / r_off)
            cmds = [(t, True) for t in el.times("t_close_s")]
            cmds += [(t, False) for t in el.times("t_open_s")]
            cmds.sort(key=lambda c: (c[0], c[1]))
            sched_t.append(np.array([c[0] for c in cmds], dtype=float))
            sched_on.append(np.array([c[1] for c in cmds], dtype=bool))
        return cls(
            ids=[e.id for e in els],
            pos=np.array(pos, dtype=np.int64),
            dev=np.array([DEV_DIODE if e.kind == "D" else DEV_SWITCH for e in els],
                         dtype=np.int64),
            g_on=np.array(g_on, dtype=float),
            g_off=np.array(g_off, dtype=float),
            vf=np.array([e.p("V_f_V") for e in els], dtype=float),
            open_at_zero=np.array([bool(e.p("open_at_zero")) for e in els], dtype=bool),
            initial_on=np.array([e.kind == "SW" and bool(e.p("closed")) for e in els],
                                dtype=bool),
            sched_t=sched_t,
            sched_on=sched_on,
        )

    def __len__(self) -> int:
        return len(self.ids)

    def conductance(self, on: BoolArray) -> FloatArray:
        out: FloatArray = np.where(on, self.g_on, self.g_off)
        return out

    def norton(self, on: BoolArray) -> FloatArray:
        """History-like constant term of each device branch (forward drop when on)."""
        out: FloatArray = np.where(on, -self.g_on * self.vf, 0.0)
        return out

    def next_command(self, j: int, k: int) -> tuple[float, bool] | None:
        if k < len(self.sched_t[j]):
            return float(self.sched_t[j][k]), bool(self.sched_on[j][k])
        return None

    def event_fractions(
        self,
        t0: float,
        t1: float,
        on: BoolArray,
        armed: BoolArray,
        sched_idx: IntArray,
        i0: FloatArray,
        i1: FloatArray,
        v0: FloatArray,
        v1: FloatArray,
    ) -> FloatArray:
        """Fraction ``lambda`` in [0, 1] of the step (t0, t1] at which each device switches;
        ``inf`` where no event. ``i*``/``v*`` are device branch currents/voltages at the ends.
        """
        n = len(self.ids)
        lam = np.full(n, np.inf)
        for j in range(n):
            if self.dev[j] == DEV_DIODE:
                if on[j]:
                    if i1[j] < 0.0:
                        lam[j] = _crossing(i0[j], i1[j])
                else:
                    a0, a1 = v0[j] - self.vf[j], v1[j] - self.vf[j]
                    if a1 > 0.0:
                        lam[j] = _crossing(-a0, -a1)
                continue
            if on[j] and armed[j] and i0[j] * i1[j] <= 0.0:
                s = 1.0 if i0[j] > 0.0 else -1.0
                lam[j] = _crossing(s * i0[j], s * i1[j])
            cmd = self.next_command(j, int(sched_idx[j]))
            if cmd is not None and cmd[0] <= t1:
                lam[j] = min(lam[j], max(cmd[0] - t0, 0.0) / (t1 - t0))
        return lam

    def apply(
        self,
        t: float,
        mask: BoolArray,
        on: BoolArray,
        armed: BoolArray,
        sched_idx: IntArray,
    ) -> list[tuple[str, bool]]:
        """Apply events for devices in ``mask`` at time ``t`` (arrays updated in place).

        Returns the list of ``(id, new_state)`` for devices whose conduction state changed.
        """
        changed: list[tuple[str, bool]] = []
        for j in map(int, np.flatnonzero(mask)):
            new = bool(on[j])
            if self.dev[j] == DEV_DIODE:
                new = not on[j]
            else:
                cmd = self.next_command(j, int(sched_idx[j]))
                if cmd is not None and cmd[0] <= t + 1e-15:
                    sched_idx[j] += 1
                    if cmd[1]:
                        new, armed[j] = True, False
                    elif self.open_at_zero[j]:
                        armed[j] = True  # open at the next current zero
                    else:
                        new = False
                elif armed[j]:  # current zero reached
                    new, armed[j] = False, False
            if new != bool(on[j]):
                on[j] = new
                changed.append((self.ids[j], new))
        return changed


def _crossing(a0: float, a1: float) -> float:
    """Fraction at which an indicator falling from ``a0`` to ``a1 <= 0`` reaches zero
    (linear interpolation); 0 if it is already non-positive at the start."""
    if a0 <= 0.0:
        return 0.0
    return float(min(a0 / (a0 - a1), 1.0))
