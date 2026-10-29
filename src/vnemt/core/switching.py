"""Two-state switching devices: switch/breaker ``SW``, diode ``D``, thyristor ``T``.

SPEC S-11, S-12, S-13 (diode part). Each device is a resistive branch with ``G = 1/R_on`` (on)
or ``1/R_off`` (off). Diodes and thyristors in the on state also carry a forward drop ``V_f``:
``i = (v - V_f)/R_on``, i.e. a Norton term ``h = -V_f/R_on``.

Switching instants inside a step are located by linear interpolation of an indicator between
the two ends of the step (SPEC S-04):

==========================  =============================  ==================================
Device / state              Indicator                      Event when
==========================  =============================  ==================================
diode on                    branch current ``i``           ``i`` falls below 0
diode off                   ``v_AK - V_f``                 rises above 0
thyristor on                ``i - I_H``                    falls below 0
thyristor off, gated        ``v_AK - V_th``                > 0 inside the gate window
thyristor off, t < t_q      ``v_AK - V_th``                > 0 before ``t_off + t_q``
                                                           (re-conduction without gate: CF)
timed switch                ``t - t_cmd``                  command time reached (schedule or a
                                                           command from a controller)
breaker armed to open       branch current ``i``           ``i`` changes sign
saturable inductor          ``|i| - i_knee``               crosses zero (enters / leaves the
                                                           saturated segment)
==========================  =============================  ==================================

Saturable inductor ``LSAT`` (two-slope magnetising characteristic, symmetric): inductance
``L_H`` for ``|i| < I_knee_A`` and ``Lsat_H`` above. Within a segment ``di/dt = v/L`` so the
trapezoidal current integration needs no offset term; the branch is an inductor whose
conductance ``dt/(2L)`` is set by the segment ("on" = saturated).

Gate windows ``[fire_on, fire_off]`` of thyristors are set by the firing control
(:meth:`vnemt.core.solver.EmtSolver.fire`) and may start anywhere inside a step, so the firing
instant does not depend on the time grid (SPEC F1-L03).

A breaker with ``open_at_zero`` is *armed* at its open command time (a non-topological event)
and opens at the next current zero.

A switch that interrupts an inductor current should use ``R_off >= 1e9`` ohm: the residual
numerical oscillation after CDA is about ``4 i0 L^2 / (dt^2 R_off)`` (SPEC S-02, note 5.1.1).

Reference: A. M. Gole, I. T. Fernando, G. D. Irwin, O. B. Nayak, "Modeling of power
electronic apparatus: additional interpolation issues", IPST 1997.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray

from vnemt.errors import TopologyError
from vnemt.model.netlist import Element

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]

DEV_SWITCH, DEV_DIODE, DEV_THYRISTOR, DEV_SAT = 0, 1, 2, 3
R_ON_DEFAULT, R_OFF_DEFAULT = 1e-3, 1e6


@dataclass
class DeviceState:
    """Mutable switching bookkeeping, part of the solver state (snapshot, SPEC S-09)."""

    on: BoolArray  # conduction state
    armed: BoolArray  # breakers waiting for a current zero
    sched_idx: IntArray  # next schedule entry per switch
    fire_on: FloatArray  # gate window start (thyristors), -inf = none
    fire_off: FloatArray  # gate window end
    off_t: FloatArray  # last turn-off instant, -inf = never
    fwd_pending: BoolArray  # waiting for v_AK to become positive after turn-off
    cmd_t: FloatArray  # pending controller command time (switches), inf = none
    cmd_on: BoolArray  # pending command: close (True) / open (False)

    FIELDS: ClassVar[tuple[str, ...]] = (
        "on", "armed", "sched_idx", "fire_on", "fire_off", "off_t", "fwd_pending", "cmd_t",
        "cmd_on",
    )

    def copy(self) -> DeviceState:
        return DeviceState(**{f: getattr(self, f).copy() for f in self.FIELDS})


@dataclass
class Change:
    """A device whose conduction state changed."""

    id: str
    on: bool
    gated: bool = True  # False for a thyristor turning on without gate pulse (CF)


@dataclass
class SwitchSet:
    """Static description of all switching devices (indices into the branch arrays)."""

    ids: list[str]
    pos: IntArray  # branch index of each device
    dev: IntArray  # DEV_*
    g_on: FloatArray
    g_off: FloatArray
    vf: FloatArray
    vth: FloatArray
    ih: FloatArray
    tq: FloatArray
    open_at_zero: BoolArray
    initial_on: BoolArray
    # schedule: per device, sorted command times and target states (True = close)
    sched_t: list[FloatArray]
    sched_on: list[BoolArray]

    @classmethod
    def from_elements(cls, els: list[Element], pos: list[int], dt: float = 0.0) -> SwitchSet:
        g_on, g_off, sched_t, sched_on = [], [], [], []
        for el in els:
            if el.kind == "LSAT":
                lm, ls, ik = el.p("L_H"), el.p("Lsat_H"), el.p("I_knee_A")
                if not (0.0 < ls < lm and ik > 0.0):
                    raise TopologyError(f"cuộn cảm bão hòa '{el.id}': cần 0 < Lsat_H < L_H và "
                                        "I_knee_A > 0")
                g_on.append(dt / (2.0 * ls))
                g_off.append(dt / (2.0 * lm))
                sched_t.append(np.zeros(0))
                sched_on.append(np.zeros(0, dtype=bool))
                continue
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
        dev = {"SW": DEV_SWITCH, "D": DEV_DIODE, "T": DEV_THYRISTOR, "LSAT": DEV_SAT}
        return cls(
            ids=[e.id for e in els],
            pos=np.array(pos, dtype=np.int64),
            dev=np.array([dev[e.kind] for e in els], dtype=np.int64),
            g_on=np.array(g_on, dtype=float),
            g_off=np.array(g_off, dtype=float),
            vf=np.array([e.p("V_f_V") for e in els], dtype=float),
            vth=np.array([e.p("V_th_V") for e in els], dtype=float),
            ih=np.array([e.p("I_knee_A") if e.kind == "LSAT" else e.p("I_H_A") for e in els],
                        dtype=float),
            tq=np.array([e.p("t_q_s") for e in els], dtype=float),
            open_at_zero=np.array([bool(e.p("open_at_zero")) for e in els], dtype=bool),
            initial_on=np.array([e.kind == "SW" and bool(e.p("closed")) for e in els],
                                dtype=bool),
            sched_t=sched_t,
            sched_on=sched_on,
        )

    def __len__(self) -> int:
        return len(self.ids)

    def initial_state(self) -> DeviceState:
        n = len(self.ids)
        return DeviceState(
            on=self.initial_on.copy(),
            armed=np.zeros(n, dtype=bool),
            sched_idx=np.zeros(n, dtype=np.int64),
            fire_on=np.full(n, -np.inf),
            fire_off=np.full(n, -np.inf),
            off_t=np.full(n, -np.inf),
            fwd_pending=np.zeros(n, dtype=bool),
            cmd_t=np.full(n, np.inf),
            cmd_on=np.zeros(n, dtype=bool),
        )

    def conductance(self, on: BoolArray) -> FloatArray:
        out: FloatArray = np.where(on, self.g_on, self.g_off)
        return out

    def norton(self, on: BoolArray) -> FloatArray:
        """Constant term of each device branch (forward drop when on)."""
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
        ds: DeviceState,
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
        h = t1 - t0
        for j in range(n):
            dev = self.dev[j]
            if dev == DEV_DIODE:
                if ds.on[j]:
                    if i1[j] < 0.0:
                        lam[j] = _crossing(i0[j], i1[j])
                else:
                    a0, a1 = v0[j] - self.vf[j], v1[j] - self.vf[j]
                    if a1 > 0.0:
                        lam[j] = _crossing(-a0, -a1)
            elif dev == DEV_SAT:
                a0, a1 = abs(i0[j]) - self.ih[j], abs(i1[j]) - self.ih[j]
                if not ds.on[j] and a1 > 0.0:
                    lam[j] = _crossing(-a0, -a1)
                elif ds.on[j] and a1 < 0.0:
                    lam[j] = _crossing(a0, a1)
            elif dev == DEV_THYRISTOR:
                if ds.on[j]:
                    if i1[j] < self.ih[j]:
                        lam[j] = _crossing(i0[j] - self.ih[j], i1[j] - self.ih[j])
                    continue
                a0, a1 = v0[j] - self.vth[j], v1[j] - self.vth[j]
                if ds.fire_on[j] <= t1 and ds.fire_off[j] >= t0:
                    ls = max((ds.fire_on[j] - t0) / h, 0.0)
                    le = min((ds.fire_off[j] - t0) / h, 1.0)
                    a_s, a_e = a0 + ls * (a1 - a0), a0 + le * (a1 - a0)
                    if a_s > 0.0 and a_e > 0.0:
                        lam[j] = ls
                    elif a_s <= 0.0 < a_e:
                        lam[j] = ls + (le - ls) * _crossing(-a_s, -a_e)
                t_rec = ds.off_t[j] + self.tq[j]
                if self.tq[j] > 0.0 and t0 < t_rec and a1 > 0.0:
                    lc = _crossing(-a0, -a1)
                    if t0 + lc * h < t_rec:
                        lam[j] = min(lam[j], lc)
            else:
                if ds.on[j] and ds.armed[j] and i0[j] * i1[j] <= 0.0:
                    s = 1.0 if i0[j] > 0.0 else -1.0
                    lam[j] = _crossing(s * i0[j], s * i1[j])
                cmd = self.next_command(j, int(ds.sched_idx[j]))
                if cmd is not None and cmd[0] <= t1:
                    lam[j] = min(lam[j], max(cmd[0] - t0, 0.0) / h)
                if ds.cmd_t[j] <= t1:
                    lam[j] = min(lam[j], max(ds.cmd_t[j] - t0, 0.0) / h)
        return lam

    def apply(self, t: float, mask: BoolArray, ds: DeviceState) -> list[Change]:
        """Apply events for devices in ``mask`` at time ``t`` (``ds`` updated in place).

        Returns the devices whose conduction state changed.
        """
        changed: list[Change] = []
        eps = 1e-12
        for j in map(int, np.flatnonzero(mask)):
            new = bool(ds.on[j])
            gated = True
            if self.dev[j] in (DEV_DIODE, DEV_THYRISTOR, DEV_SAT):
                new = not ds.on[j]
                if new and self.dev[j] == DEV_THYRISTOR:
                    gated = bool(ds.fire_on[j] - eps <= t <= ds.fire_off[j] + eps)
            elif ds.cmd_t[j] <= t + 1e-15:  # command from a controller
                ds.cmd_t[j] = np.inf
                if ds.cmd_on[j]:
                    new, ds.armed[j] = True, False
                elif self.open_at_zero[j]:
                    ds.armed[j] = True
                else:
                    new = False
            else:
                cmd = self.next_command(j, int(ds.sched_idx[j]))
                if cmd is not None and cmd[0] <= t + 1e-15:
                    ds.sched_idx[j] += 1
                    if cmd[1]:
                        new, ds.armed[j] = True, False
                    elif self.open_at_zero[j]:
                        ds.armed[j] = True  # open at the next current zero
                    else:
                        new = False
                elif ds.armed[j]:  # current zero reached
                    new, ds.armed[j] = False, False
            if new != bool(ds.on[j]):
                ds.on[j] = new
                if not new:
                    ds.off_t[j] = t
                    ds.fwd_pending[j] = self.dev[j] == DEV_THYRISTOR
                else:
                    ds.fwd_pending[j] = False
                changed.append(Change(self.ids[j], new, gated))
        return changed


def _crossing(a0: float, a1: float) -> float:
    """Fraction at which an indicator falling from ``a0`` to ``a1 <= 0`` reaches zero
    (linear interpolation); 0 if it is already non-positive at the start."""
    if a0 <= 0.0:
        return 0.0
    return float(min(a0 / (a0 - a1), 1.0))
