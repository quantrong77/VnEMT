"""Equidistant pulse control (EPC) for a six-pulse thyristor bridge (SPEC F1-L03).

Angles follow IEC 60633: alpha is measured from the natural commutation instant. For a bridge
fed by phase voltages ``v_a = V sin(theta)`` (PLL convention, :mod:`vnemt.control.pll`) and the
valve numbering in firing order (1 a+, 2 c-, 3 b+, 4 a-, 5 c+, 6 b-), valve ``k`` (k = 1..6)
has its natural commutation at ``theta = 30 deg + (k - 1) 60 deg`` (rising zero of the
commutating line voltage ``v_ac, v_bc, v_ba, v_ca, v_cb, v_ab``). ``offset_deg`` adds the
phase shift of the converter transformer (e.g. -30 deg for the Y/D bridge of a 12-pulse
group, so both bridges together give 12 pulses 30 deg apart).

Valve ``k`` is fired when the PLL angle, extrapolated with the PLL frequency inside the next
step, reaches::

    theta_k = 30 deg + offset + alpha + (k - 1) 60 deg

so the firing instant is computed exactly inside the step and handed to the solver as an
off-grid gate window of width ``pulse_deg`` (S-04); the pulse spacing does not depend on
``dt``.

At the first run (deblocking) every valve whose gate window is already open, i.e. whose
target angle was passed less than ``pulse_deg`` ago, is gated immediately for the remainder of
its window; otherwise a whole valve group could stay without gate pulses for up to 60 deg.

Reference: J. Arrillaga, *High Voltage Direct Current Transmission*, 2nd ed., IEE, 1998,
ch. 5 (firing control); IEC 60633.
"""

from __future__ import annotations

import math

import numpy as np

from vnemt.control.base import ControlIO, Controller
from vnemt.control.blocks import wrap_2pi
from vnemt.core.solver import EmtSolver, FloatArray
from vnemt.errors import CaseError


class Epc6(Controller):
    """EPC firing six valves (ids in firing order). Output: ``alpha`` order [deg].

    The alpha order is the constant ``alpha_deg`` or the signal ``alpha_signal`` [deg].
    """

    def __init__(self, id: str, pll: str, valves: list[str], alpha_deg: float | None = None,
                 alpha_signal: str | None = None, offset_deg: float = 0.0,
                 pulse_deg: float = 120.0) -> None:
        super().__init__(id)
        if len(valves) != 6:
            raise CaseError(f"khối EPC '{id}': cần đúng 6 van theo thứ tự kích", path="controls")
        if (alpha_deg is None) == (alpha_signal is None):
            raise CaseError(f"khối EPC '{id}': khai báo đúng một trong alpha_deg, alpha_signal",
                            path="controls")
        self.pll = pll
        self.valves = valves
        self.alpha_deg = alpha_deg
        self.alpha_signal = alpha_signal
        self.offset = math.radians(offset_deg)
        self.pulse = math.radians(pulse_deg)
        self._idx: list[int] = []

    def inputs(self) -> list[str]:
        sig = [f"{self.pll}.theta", f"{self.pll}.omega"]
        return sig + ([self.alpha_signal] if self.alpha_signal else [])

    def outputs(self) -> list[tuple[str, str]]:
        return [("alpha", "deg")]

    def init_state(self) -> FloatArray:
        return np.zeros(1)  # [deblocked flag]

    def bind(self, solver: EmtSolver) -> None:
        self._idx = [solver.switch_index(v) for v in self.valves]

    def update(self, t: float, dt: float, x: FloatArray, u: FloatArray,
               io: ControlIO) -> FloatArray:
        theta, omega = float(u[0]), float(u[1])
        alpha_deg = float(u[2]) if self.alpha_signal else float(self.alpha_deg or 0.0)
        alpha = math.radians(alpha_deg)
        tol = 1e-9 * omega * dt
        start = x[0] == 0.0
        x[0] = 1.0
        for k, j in enumerate(self._idx):
            target = math.radians(30.0) + self.offset + alpha + k * math.pi / 3.0
            phi = wrap_2pi(theta - target)  # angle already travelled past the target
            if start and tol <= phi < self.pulse:
                io.fire(j, t, t + (self.pulse - phi) / omega)
                continue
            if phi < tol:
                t_fire = t
            else:
                tau = (2.0 * math.pi - phi) / omega
                if tau > dt * (1.0 + 1e-9):
                    continue
                t_fire = t + tau
            io.fire(j, t_fire, t_fire + self.pulse / omega)
        return np.array([alpha_deg])
