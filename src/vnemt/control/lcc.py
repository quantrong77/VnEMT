"""LCC pole controls: constant current (CC), constant extinction angle (CEA), current margin
and VDCOL (SPEC F3-01, F3-02, F3-03).

Per-unit quantities use the DC base (``I_base = S/U_dc``, ``U_base = U_dc``).

Rectifier::

    Id_ref(t)  ramp from Id_start to Id_ref (start-up)
    Id_ord     = min(Id_ref(t), VDCOL(Ud_f))
    alpha      = PI(Id_f - Id_ord)  in [alpha_min, alpha_max]        (more current -> more alpha)

Inverter (current order received from the rectifier, ideal telecom)::

    alpha_cc   = PI(Id_f - (Id_ord - margin)) in [alpha_min, alpha_max]
    cos(beta)  = cos(gamma_ref) - sqrt2 Xc Id / U_LL          (predictive CEA)
    alpha_g    = 180 deg - beta + corr,  d corr/dt = Ki_g (gamma_min - gamma_ref)  (feedback)
    alpha      = min(alpha_cc, alpha_g)

In normal operation the inverter current error is positive (Id = Id_ord > Id_ord - margin), so
``alpha_cc`` rises to its upper limit and CEA governs; when the rectifier loses current control
(low rectifier AC voltage) the inverter CC takes over (mode shift, F3-01).

Mode coupling without windup: the upper limit of the inverter CC integrator tracks
``alpha_g + 5 deg`` (so CC can take over within a few degrees), and the gamma feedback
correction integrates only while CEA is the selected mode.

``gamma_min`` is the smallest measured extinction angle of the station's valves over their
latest commutations (solver markers ``fwd`` minus turn-off instants, F1-L04). ``U_LL`` is the
valve-side line voltage from the PLL amplitude of the AC bus and the transformer ratio.

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
    ``Ud`` [pu]."""

    def __init__(self, id: str, id_signal: str, ud_signal: str, vm_signal: str,
                 id_ord_signal: str, valves: list[str], I_base: float, U_base: float,
                 c: LccControl, xc_ohm: float, ratio: float, f_Hz: float) -> None:
        super().__init__(id, id_signal, ud_signal, I_base, U_base, c)
        self.vm_sig, self.ord_sig = vm_signal, id_ord_signal
        self.valves = valves
        self.xc, self.ratio, self.f = xc_ohm, ratio, f_Hz
        self._sw: list[int] = []
        self._mk = 0  # markers already scanned (not state: the solver log restarts with it)

    # state: measurement (4) + [I_cc, e_prev, corr, n_measured] + gamma per valve
    def inputs(self) -> list[str]:
        return [self.id_sig, self.ud_sig, self.vm_sig, self.ord_sig]

    def outputs(self) -> list[tuple[str, str]]:
        return [("alpha", "deg"), ("alpha_cc", "deg"), ("alpha_g", "deg"),
                ("gamma_min", "deg"), ("Id_ord", "pu"), ("Id", "pu"), ("Ud", "pu")]

    def init_state(self) -> FloatArray:
        head = [0.0, 0.0, 0.0, 0.0, self.c.alpha_max_deg, 0.0, 0.0, 0.0]
        return np.array(head + [math.nan] * len(self.valves))

    def bind(self, solver: EmtSolver) -> None:
        self._sw = [solver.switch_index(v) for v in self.valves]
        self._pos = {v: k for k, v in enumerate(self.valves)}

    def _scan_gamma(self, x: FloatArray, io: ControlIO) -> None:
        marks = io.solver.markers
        for t_m, vid, kind in marks[self._mk:]:
            k = self._pos.get(vid)
            if k is not None and kind == "fwd":
                off = io.state.dev.off_t[self._sw[k]]
                x[8 + k] = 360.0 * self.f * (t_m - off)
                x[7] += 1.0
        self._mk = len(marks)

    def update(self, t: float, dt: float, x: FloatArray, u: FloatArray,
               io: ControlIO) -> FloatArray:
        idf, udf = self._measure(x, float(u[0]), float(u[1]), dt)
        c = self.c
        id_ord = float(u[3]) - c.margin_pu
        self._scan_gamma(x, io)
        g = x[8:]
        gmin = float(np.nanmin(g)) if x[7] >= len(self.valves) else math.nan
        u_ll = float(u[2]) * math.sqrt(1.5) * self.ratio  # phase peak -> line rms, valve side
        id_a = max(idf, 0.0) * self.ib
        cosb = math.cos(math.radians(c.gamma_ref_deg)) - (
            math.sqrt(2.0) * self.xc * id_a / u_ll if u_ll > 0.0 else 0.0)
        beta = math.degrees(math.acos(min(max(cosb, -1.0), 1.0)))
        a_g = 180.0 - beta + float(x[6])
        e = idf - id_ord
        hi = min(c.alpha_max_deg, max(a_g + 5.0, c.alpha_min_deg))
        a_cc, x[4] = pi_step(float(x[4]), float(x[5]), e, c.kp_deg, c.ki_deg, dt,
                             c.alpha_min_deg, hi)
        x[5] = e
        if a_g <= a_cc and not math.isnan(gmin):  # CEA selected: gamma feedback active
            x[6] = min(max(x[6] + c.ki_gamma * (gmin - c.gamma_ref_deg) * dt, -10.0), 10.0)
        alpha = min(max(min(a_cc, a_g), c.alpha_min_deg), c.alpha_max_deg)
        return np.array([alpha, a_cc, a_g, gmin, id_ord, idf, udf])
