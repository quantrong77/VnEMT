"""Three-phase synchronous-reference-frame PLL (SPEC F1-L03, F1-V08).

Convention: the PLL angle ``theta`` is the phase of phase *a* written as a sine,
``v_a = V sin(theta)``. With the Clarke transform of :mod:`vnemt.control.blocks`
(``v_alpha = V sin theta``, ``v_beta = -V cos theta``) the normalised phase detector is::

    e = (v_alpha cos th_hat + v_beta sin th_hat) / V = sin(theta - th_hat)

A PI regulator gives the frequency deviation and the angle is integrated::

    omega = omega0 + Kp e + Ki int(e) dt,     th_hat(t + dt) = th_hat(t) + omega dt

so in steady state ``th_hat(t) = theta(t)`` exactly at the sampling instants. Default gains
place a second-order loop at ``f_n = 20 Hz``, ``zeta = 0.707``: ``Kp = 2 zeta w_n``,
``Ki = w_n^2``.

Reference: V. Kaura, V. Blasko, "Operation of a phase locked loop system under distorted
utility conditions", IEEE Trans. Ind. Appl. 33(1), 1997.
"""

from __future__ import annotations

import math

import numpy as np

from vnemt.control.base import ControlIO, Controller
from vnemt.control.blocks import clarke, pi_step, wrap_2pi
from vnemt.core.solver import FloatArray

# state layout
_TH, _I, _E, _W = 0, 1, 2, 3


class PllSrf(Controller):
    """SRF-PLL. Outputs: ``theta`` [rad, 0..2pi), ``omega`` [rad/s], ``f`` [Hz], ``Vm`` [V]."""

    def __init__(self, id: str, va: str, vb: str, vc: str, f0_Hz: float,
                 kp: float | None = None, ki: float | None = None,
                 theta0_deg: float = 0.0) -> None:
        super().__init__(id)
        self.sig = [va, vb, vc]
        self.w0 = 2.0 * math.pi * f0_Hz
        wn = 2.0 * math.pi * 20.0
        self.kp = 2.0 * 0.707 * wn if kp is None else kp
        self.ki = wn * wn if ki is None else ki
        self.theta0 = math.radians(theta0_deg)

    def inputs(self) -> list[str]:
        return self.sig

    def outputs(self) -> list[tuple[str, str]]:
        return [("theta", "rad"), ("omega", "rad/s"), ("f", "Hz"), ("Vm", "V")]

    def init_state(self) -> FloatArray:
        return np.array([self.theta0, 0.0, 0.0, self.w0])

    def update(self, t: float, dt: float, x: FloatArray, u: FloatArray,
               io: ControlIO) -> FloatArray:
        va, vb = clarke(float(u[0]), float(u[1]), float(u[2]))
        vm = math.hypot(va, vb)
        th = float(x[_TH])
        e = (va * math.cos(th) + vb * math.sin(th)) / vm if vm > 0.0 else 0.0
        dw, i_new = pi_step(float(x[_I]), float(x[_E]), e, self.kp, self.ki, dt)
        w = self.w0 + dw
        out = np.array([th, w, w / (2.0 * math.pi), vm])
        x[_I], x[_E], x[_W] = i_new, e, w
        x[_TH] = wrap_2pi(th + w * dt)
        return out
