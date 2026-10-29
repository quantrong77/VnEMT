"""Discrete control blocks (SPEC section 6, "Điều khiển"), pure functions on scalars.

Integrations use the trapezoidal (Tustin) rule with the controller step ``dt``, matching the
network discretisation.

=================  ==========================================================================
Block              Discrete equation
=================  ==========================================================================
PI                 ``I_k = I_{k-1} + Ki dt (e_k + e_{k-1})/2``; ``y = Kp e_k + I_k``, clamped
                   to ``[lo, hi]``; anti-windup by conditional integration: while ``e`` drives the
                   output into a limit the integrator rises at most until ``Kp e + I``
                   reaches it and is never pulled back; ``I_k`` stays in ``[lo, hi]``
first order        ``y_k = ((2T - dt) y_{k-1} + dt (u_k + u_{k-1})) / (2T + dt)`` (1/(1+sT))
rate limiter       ``y_k = y_{k-1} + clip(u_k - y_{k-1}, -fall dt, rise dt)``
Clarke             ``v_alpha = (2/3)(a - (b + c)/2)``, ``v_beta = (b - c)/sqrt3``
                   (amplitude invariant; ``a = V sin th`` gives ``alpha = V sin th``,
                   ``beta = -V cos th``)
=================  ==========================================================================

Reference: PSCAD/EMTDC Continuous System Model Functions (CSMF) manual; K. J. Astrom,
T. Hagglund, *PID Controllers*, ISA, 1995 (anti-windup by clamping).
"""

from __future__ import annotations

import math


def pi_step(i_prev: float, e_prev: float, e: float, kp: float, ki: float, dt: float,
            lo: float = -math.inf, hi: float = math.inf) -> tuple[float, float]:
    """One PI step; returns ``(y, I_new)``."""
    i_new = i_prev + ki * dt * 0.5 * (e + e_prev)
    y_free = kp * e + i_new
    if y_free > hi and ki * e > 0.0:  # integrate only up to the limit, never pull back
        i_new = max(i_prev, hi - kp * e)
    elif y_free < lo and ki * e < 0.0:
        i_new = min(i_prev, lo - kp * e)
    i_new = min(max(i_new, lo), hi)
    y = min(max(kp * e + i_new, lo), hi)
    return y, i_new


def first_order(y_prev: float, u_prev: float, u: float, T: float, dt: float) -> float:
    """Low-pass ``1/(1 + sT)`` (Tustin); ``T = 0`` passes ``u`` through."""
    if T <= 0.0:
        return u
    return ((2.0 * T - dt) * y_prev + dt * (u + u_prev)) / (2.0 * T + dt)


def rate_limit(y_prev: float, u: float, rise: float, fall: float, dt: float) -> float:
    """Limit the rate of change to ``+rise`` / ``-fall`` per second."""
    return y_prev + min(max(u - y_prev, -fall * dt), rise * dt)


def clarke(a: float, b: float, c: float) -> tuple[float, float]:
    """Amplitude-invariant abc -> alpha-beta."""
    return (2.0 / 3.0) * (a - 0.5 * (b + c)), (b - c) / math.sqrt(3.0)


def wrap_2pi(x: float) -> float:
    """Angle wrapped to ``[0, 2 pi)``."""
    y = math.fmod(x, 2.0 * math.pi)
    return y + 2.0 * math.pi if y < 0.0 else y
