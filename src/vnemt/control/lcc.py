"""LCC pole controls: constant current (CC), constant extinction angle (CEA), current margin
and VDCOL (SPEC F3-01, F3-02, F3-03).

Per-unit quantities use the DC base (``I_base = S/U_dc``, ``U_base = U_dc``).

Rectifier::

    Id_ref(t)  ramp from Id_start to Id_ref (start-up)
    Id_ord     = min(Id_ref(t), VDCOL(Ud_f))
    alpha      = PI(Id_f - Id_ord)  in [alpha_min, alpha_max]        (more current -> more alpha)

Inverter (current order received from the rectifier, ideal telecom), structure of the CIGRE
benchmark: two PI regulators and minimum-alpha (maximum-beta) selection::

    alpha_cc   = PI_cc(Id_f - (Id_ord - margin))
    alpha_g    = PI_g(gamma_min - gamma_ref)              (closed-loop CEA)
    alpha      = min(alpha_cc, alpha_g)  in [alpha_min, alpha_max]

In normal operation the inverter current error is positive (Id = Id_ord > Id_ord - margin), so
``alpha_cc`` lies above ``alpha_g`` and CEA governs; when the rectifier loses current control
(low rectifier AC voltage) the inverter CC takes over (mode shift, F3-01). The regulator that
is not selected tracks the selected output by back-calculation (``I = alpha - Kp e``), so the
mode change is bumpless and neither integrator winds up. Until every valve has reported an
extinction angle (start-up) only the CC regulator acts.

``gamma_min`` is the smallest extinction angle of the station's valves over their latest
commutations, measured as defined in IEC 60633: from the end of conduction (turn-off instant
of the valve) to the zero crossing of its commutating voltage. The crossing is located with the
PLL angle: for valve ``j`` (0-based, firing order) of a bridge with offset ``phi_b`` it is at
``theta = 30 deg + phi_b + (j + 2) 60 deg + 180 deg``. The first positive crossing of the
actual valve voltage is not used: in a 12-pulse station on a weak bus the commutation notches
of the other bridge cut it short (about 30 deg - mu) whatever the firing angle, which would make
a CEA regulator run away. That actual reverse-voltage time is still measured for F1-L04 and
commutation failure detection (:mod:`vnemt.analysis.lcc`, thyristor ``t_q``).

VDCOL (four points)::

    i_lim = i_lo                                 for Ud_f <= u_lo
          = i_lo + (i_hi - i_lo)(Ud_f - u_lo)/(u_hi - u_lo)
          = i_hi                                 for Ud_f >= u_hi

``Ud_f`` is filtered with separate time constants for rising and falling voltage.

Reference: M. Szechtman, T. Wess, C. V. Thio, "A benchmark model for HVDC system studies",
IEE Conf. AC and DC Power Transmission, 1991; J. Arrillaga, *High Voltage Direct Current
Transmission*, 2nd ed., IEE, 1998, ch. 5.
"""

from __future__ import annotations

import math

import numpy as np

from vnemt.control.base import ControlIO, Controller
from vnemt.control.blocks import first_order, pi_step
from vnemt.core.solver import EmtSolver, FloatArray
from vnemt.model.grid import LccControl


def vdcol_limit(ud: float, pts: tuple[float, float, float, float] | None) -> float:
    """Current order limit [pu] for the filtered DC voltage ``ud`` [pu]."""
    if pts is None:
        return math.inf
    u_lo, u_hi, i_lo, i_hi = pts
    if ud <= u_lo:
        return i_lo
    if ud >= u_hi:
        return i_hi
    return i_lo + (i_hi - i_lo) * (ud - u_lo) / (u_hi - u_lo)


def ramp(t: float, c: LccControl) -> float:
    """Start-up current reference [pu]."""
    if t <= c.ramp_start_s:
        return c.Id_start_pu
    if c.ramp_s <= 0.0 or t >= c.ramp_start_s + c.ramp_s:
        return c.Id_ref_pu
    return c.Id_start_pu + (c.Id_ref_pu - c.Id_start_pu) * (t - c.ramp_start_s) / c.ramp_s


# common measurement state: [Id_f, Id_in_prev, Ud_f, Ud_in_prev]
_IDF, _IDP, _UDF, _UDP = 0, 1, 2, 3


class _LccBase(Controller):
    def __init__(self, id: str, id_signal: str, ud_signal: str, I_base: float, U_base: float,
                 c: LccControl) -> None:
        super().__init__(id)
        self.id_sig, self.ud_sig = id_signal, ud_signal
        self.ib, self.ub, self.c = I_base, U_base, c

    def _measure(self, x: FloatArray, id_a: float, ud_v: float, dt: float) -> tuple[float, float]:
        i, u = id_a / self.ib, ud_v / self.ub
        x[_IDF] = first_order(x[_IDF], x[_IDP], i, self.c.T_id_s, dt)
        tu = self.c.T_ud_up_s if u > x[_UDF] else self.c.T_ud_down_s
        x[_UDF] = first_order(x[_UDF], x[_UDP], u, tu, dt)
        x[_IDP], x[_UDP] = i, u
        return float(x[_IDF]), float(x[_UDF])


class LccRectifierControl(_LccBase):
    """Outputs: ``alpha`` [deg], ``Id_ord``, ``Id``, ``Ud`` [pu]."""

    # state: measurement (4) + [I_cc, e_prev]
    def inputs(self) -> list[str]:
        return [self.id_sig, self.ud_sig]

    def outputs(self) -> list[tuple[str, str]]:
        return [("alpha", "deg"), ("Id_ord", "pu"), ("Id", "pu"), ("Ud", "pu")]

    def init_state(self) -> FloatArray:
        return np.array([0.0, 0.0, 0.0, 0.0, self.c.alpha_start_deg, 0.0])

    def update(self, t: float, dt: float, x: FloatArray, u: FloatArray,
               io: ControlIO) -> FloatArray:
        idf, udf = self._measure(x, float(u[0]), float(u[1]), dt)
        c = self.c
        id_ord = min(ramp(t, c), vdcol_limit(udf, c.vdcol))
        e = idf - id_ord
        alpha, x[4] = pi_step(float(x[4]), float(x[5]), e, c.kp_deg, c.ki_deg, dt,
                              c.alpha_min_deg, c.alpha_max_deg)
        x[5] = e
        return np.array([alpha, id_ord, idf, udf])


class LccInverterControl(_LccBase):
    """Outputs: ``alpha``, ``alpha_cc``, ``alpha_g``, ``gamma_min`` [deg], ``Id_ord``, ``Id``,
    ``Ud`` [pu], ``mode`` (0 = CEA, 1 = CC)."""

    def __init__(self, id: str, id_signal: str, ud_signal: str, id_ord_signal: str,
                 pll: str, bridges: list[tuple[list[str], float]], I_base: float,
                 U_base: float, c: LccControl) -> None:
        super().__init__(id, id_signal, ud_signal, I_base, U_base, c)
        self.ord_sig = id_ord_signal
        self.pll = pll
        self.valves = [v for vs, _ in bridges for v in vs]
        # commutating-voltage reversal angle of each valve
        self._rev = np.array([math.radians(30.0 + off + (j + 2) * 60.0 + 180.0)
                              for vs, off in bridges for j in range(len(vs))])
        self._sw: list[int] = []

    # state: measurement (4) + [I_cc, e_cc_prev, I_g, e_g_prev, n_measured]
    #        + gamma per valve + last turn-off instant per valve
    def inputs(self) -> list[str]:
        return [self.id_sig, self.ud_sig, self.ord_sig, f"{self.pll}.theta",
                f"{self.pll}.omega"]

    def outputs(self) -> list[tuple[str, str]]:
        return [("alpha", "deg"), ("alpha_cc", "deg"), ("alpha_g", "deg"),
                ("gamma_min", "deg"), ("Id_ord", "pu"), ("Id", "pu"), ("Ud", "pu"),
                ("mode", "-")]

    def init_state(self) -> FloatArray:
        a0 = self.c.alpha_start_deg
        n = len(self.valves)
        head = [0.0, 0.0, 0.0, 0.0, a0, 0.0, a0, 0.0, 0.0]
        return np.array(head + [math.nan] * n + [-1e9] * n)

    def bind(self, solver: EmtSolver) -> None:
        self._sw = [solver.switch_index(v) for v in self.valves]

    def _update_gamma(self, x: FloatArray, t: float, theta: float, omega: float,
                      io: ControlIO) -> None:
        n = len(self.valves)
        gam, last = x[9:9 + n], x[9 + n:9 + 2 * n]
        for k, j in enumerate(self._sw):
            off = io.state.dev.off_t[j]
            if off > last[k]:
                last[k] = off
                th_off = theta - omega * (t - off)
                g = math.remainder(self._rev[k] - th_off, 2.0 * math.pi)
                gam[k] = math.degrees(g)
                x[8] += 1.0

    def update(self, t: float, dt: float, x: FloatArray, u: FloatArray,
               io: ControlIO) -> FloatArray:
        idf, udf = self._measure(x, float(u[0]), float(u[1]), dt)
        c = self.c
        lo, hi = c.alpha_min_deg, c.alpha_max_deg
        id_ord = float(u[2]) - c.margin_pu
        self._update_gamma(x, t, float(u[3]), float(u[4]), io)
        g = x[9:9 + len(self.valves)]
        gmin = float(np.nanmin(g)) if x[8] >= len(self.valves) else math.nan
        e_cc = idf - id_ord
        a_cc, i_cc = pi_step(float(x[4]), float(x[5]), e_cc, c.kp_deg, c.ki_deg, dt, lo, hi)
        if math.isnan(gmin):
            alpha, a_g, mode = a_cc, math.nan, 1.0
            x[6] = alpha  # gamma regulator waits at the current output
        else:
            e_g = gmin - c.gamma_ref_deg
            a_g, i_g = pi_step(float(x[6]), float(x[7]), e_g, c.kp_gamma, c.ki_gamma, dt,
                               lo, hi)
            if a_g <= a_cc:
                alpha, mode = a_g, 0.0
                i_cc = min(max(alpha - c.kp_deg * e_cc, lo), hi)
            else:
                alpha, mode = a_cc, 1.0
                i_g = min(max(alpha - c.kp_gamma * e_g, lo), hi)
            x[6], x[7] = i_g, e_g
        x[4], x[5] = i_cc, e_cc
        return np.array([alpha, a_cc, a_g, gmin, id_ord, idf, udf, mode])
