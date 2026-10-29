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

Fault handling (F4-07, F4-08):

* rectifier force retard: a DC line fault is detected when the raw DC voltage stays below
  ``fr_u_det`` for ``fr_t_det`` while the rectifier AC voltage is above ``fr_vac_min`` (an AC
  fault at the rectifier also collapses Ud but lowers the AC voltage); detection is armed once
  Ud has exceeded ``fr_arm_ud`` (not during start-up). Alpha is forced to ``fr_alpha_deg`` for
  the de-ionisation time ``fr_t_deion``, then the current order restarts with the start-up
  ramp, at most ``fr_n_restart`` times;
* inverter CFPREV: from the instantaneous alpha-beta magnitude and the zero-sequence voltage
  of the inverter AC bus (pu of the rated phase peak ``V_n``)::

      d   = K_ab max(0, 1 - |v_ab|/V_n - u_th) + K_0 |v_0|/V_n
      da  = d if d > da else da + (d - da) dt / T_dec,  limited to da_max
      alpha_inverter = min(alpha_cc, alpha_g) - da

  i.e. the inverter fires earlier as soon as the AC voltage dips, before the gamma loop reacts;
* commutation failure count (second criterion besides the thyristor ``t_q``): a commutation is
  counted as failed when the measured gamma (IEC 60633) is below ``gamma_cf_deg``, or when the
  outgoing valve still conducts after its commutating voltage has reversed.

Fast release: the integral gain of a current regulator is multiplied by ``fast_k`` while the
current error is large (rectifier: ``|e| > fast_e_pu``; inverter: ``e > fast_e_pu``, i.e. the
current is above the inverter order and CC should hand over to CEA). Around the operating
point (``e`` near 0) the linear gains, and so the small-signal stability, are unchanged; the
regulators no longer crawl back from their limits after a fault (recovery, start-up).

Set-point changes (``setpoint`` events) of ``Id_ref_pu`` ramp linearly from the previous value.

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
from vnemt.control.blocks import clarke, first_order, pi_step
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


def ramp(t: float, c: LccControl, ref: float | None = None, t_start: float | None = None
         ) -> float:
    """Start-up (or restart) current reference [pu] towards ``ref`` (default ``Id_ref_pu``)."""
    ref = c.Id_ref_pu if ref is None else ref
    t_start = c.ramp_start_s if t_start is None else t_start
    if t <= t_start:
        return c.Id_start_pu
    if c.ramp_s <= 0.0 or t >= t_start + c.ramp_s:
        return ref
    return c.Id_start_pu + (ref - c.Id_start_pu) * (t - t_start) / c.ramp_s


def scheduled(t: float, base: float, changes: list[tuple[float, float, float]]) -> float:
    """Value of a set-point with ramped changes ``(t_s, value, ramp_s)`` sorted by time."""
    v = base
    for ts, val, rs in changes:
        if t < ts:
            break
        v = val if rs <= 0.0 or t >= ts + rs else v + (val - v) * (t - ts) / rs
    return v


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
    """Outputs: ``alpha`` [deg], ``Id_ord``, ``Id``, ``Ud`` [pu], ``retard`` (1 while forced),
    ``restarts``."""

    def __init__(self, id: str, id_signal: str, ud_signal: str, I_base: float, U_base: float,
                 c: LccControl, vm_signal: str | None = None, V_n: float = 1.0,
                 setpoints: list[tuple[float, str, float, float]] | None = None) -> None:
        super().__init__(id, id_signal, ud_signal, I_base, U_base, c)
        self.vm_sig, self.vn = vm_signal, V_n
        self.id_changes = sorted((ts, v, r) for ts, prm, v, r in (setpoints or [])
                                 if prm == "Id_ref_pu")

    # state: measurement (4) + [I_cc, e_prev, retard, t_retard_end, t_low, n_restart, armed,
    #        t_restart]
    def inputs(self) -> list[str]:
        return [self.id_sig, self.ud_sig] + ([self.vm_sig] if self.vm_sig else [])

    def outputs(self) -> list[tuple[str, str]]:
        return [("alpha", "deg"), ("Id_ord", "pu"), ("Id", "pu"), ("Ud", "pu"),
                ("retard", "-"), ("restarts", "-")]

    def init_state(self) -> FloatArray:
        return np.array([0.0, 0.0, 0.0, 0.0, self.c.alpha_start_deg, 0.0,
                         0.0, 0.0, math.nan, 0.0, 0.0, -1.0])

    def _force_retard(self, t: float, x: FloatArray, ud_raw: float, udf: float,
                      vac: float) -> None:
        c = self.c
        if udf > c.fr_arm_ud:
            x[10] = 1.0
        if x[6] == 0.0:
            if c.force_retard and x[10] and ud_raw < c.fr_u_det and vac > c.fr_vac_min:
                if math.isnan(x[8]):
                    x[8] = t
                elif t - x[8] >= c.fr_t_det:
                    x[6], x[7], x[8] = 1.0, t + c.fr_t_deion, math.nan
            else:
                x[8] = math.nan
        elif t >= x[7] and x[9] < c.fr_n_restart:
            x[6], x[9], x[11], x[10] = 0.0, x[9] + 1.0, t, 0.0
            x[4] = c.alpha_start_deg

    def update(self, t: float, dt: float, x: FloatArray, u: FloatArray,
               io: ControlIO) -> FloatArray:
        idf, udf = self._measure(x, float(u[0]), float(u[1]), dt)
        c = self.c
        vac = float(u[2]) / self.vn if self.vm_sig else 1.0
        self._force_retard(t, x, float(u[1]) / self.ub, udf, vac)
        ref = scheduled(t, c.Id_ref_pu, self.id_changes)
        id_ref = ramp(t, c, ref) if x[11] < 0.0 else ramp(t, c, ref, float(x[11]))
        id_ord = min(id_ref, vdcol_limit(udf, c.vdcol))
        e = idf - id_ord
        if x[6]:
            alpha = c.fr_alpha_deg
            x[4] = alpha
        else:
            ki = c.ki_deg * (c.fast_k if abs(e) > c.fast_e_pu else 1.0)
            alpha, x[4] = pi_step(float(x[4]), float(x[5]), e, c.kp_deg, ki, dt,
                                  c.alpha_min_deg, c.alpha_max_deg)
        x[5] = e
        return np.array([alpha, id_ord, idf, udf, x[6], x[9]])


class LccInverterControl(_LccBase):
    """Outputs: ``alpha``, ``alpha_cc``, ``alpha_g``, ``gamma_min`` [deg], ``Id_ord``, ``Id``,
    ``Ud`` [pu], ``mode`` (0 = CEA, 1 = CC), ``cf_count``, ``dalpha`` [deg] (CFPREV)."""

    def __init__(self, id: str, id_signal: str, ud_signal: str, id_ord_signal: str,
                 pll: str, bridges: list[tuple[list[str], float]], I_base: float,
                 U_base: float, c: LccControl, bus: tuple[str, str, str] | None = None,
                 V_n: float = 1.0) -> None:
        super().__init__(id, id_signal, ud_signal, I_base, U_base, c)
        self.ord_sig = id_ord_signal
        self.pll = pll
        self.bus, self.vn = bus, V_n
        self.valves = [v for vs, _ in bridges for v in vs]
        # commutating-voltage reversal angle of each valve
        self._rev = np.array([math.radians(30.0 + off + (j + 2) * 60.0 + 180.0)
                              for vs, off in bridges for j in range(len(vs))])
        self._sw: list[int] = []

    # state: measurement (4) + [I_cc, e_cc_prev, I_g, e_g_prev, n_measured, cf_count, dalpha]
    #        + gamma, last turn-off instant and CF flag per valve
    _H = 11

    def inputs(self) -> list[str]:
        sig = [self.id_sig, self.ud_sig, self.ord_sig, f"{self.pll}.theta",
               f"{self.pll}.omega"]
        return sig + (list(self.bus) if self.bus else [])

    def outputs(self) -> list[tuple[str, str]]:
        return [("alpha", "deg"), ("alpha_cc", "deg"), ("alpha_g", "deg"),
                ("gamma_min", "deg"), ("Id_ord", "pu"), ("Id", "pu"), ("Ud", "pu"),
                ("mode", "-"), ("cf_count", "-"), ("dalpha", "deg")]

    def init_state(self) -> FloatArray:
        a0 = self.c.alpha_start_deg
        n = len(self.valves)
        head = [0.0, 0.0, 0.0, 0.0, a0, 0.0, a0, 0.0, 0.0, 0.0, 0.0]
        return np.array(head + [math.nan] * n + [-1e9] * n + [0.0] * n)

    def bind(self, solver: EmtSolver) -> None:
        self._sw = [solver.switch_index(v) for v in self.valves]

    def _update_gamma(self, x: FloatArray, t: float, theta: float, omega: float,
                      io: ControlIO) -> None:
        n, h = len(self.valves), self._H
        gam, last, flag = x[h:h + n], x[h + n:h + 2 * n], x[h + 2 * n:h + 3 * n]
        on = io.state.dev.on
        for k, j in enumerate(self._sw):
            off = io.state.dev.off_t[j]
            if off > last[k]:
                last[k] = off
                th_off = theta - omega * (t - off)
                g = math.degrees(math.remainder(self._rev[k] - th_off, 2.0 * math.pi))
                gam[k] = g
                x[8] += 1.0
                if g < self.c.gamma_cf_deg and not flag[k]:
                    x[9] += 1.0  # extinction margin too small: commutation failure
                flag[k] = 0.0
            elif on[j] and not flag[k] and x[8] >= n:
                phi = math.remainder(theta - self._rev[k], 2.0 * math.pi)
                if 0.0 < phi < 0.5 * math.pi:  # still conducting after voltage reversal
                    x[9] += 1.0
                    flag[k] = 1.0

    def _cfprev(self, x: FloatArray, u: FloatArray, dt: float) -> float:
        c = self.c
        if not (c.cfprev and self.bus):
            return 0.0
        a, b, cc = (float(v) for v in u[5:8])
        va, vb = clarke(a, b, cc)
        v0 = abs(a + b + cc) / 3.0
        d = (c.cfprev_k_ab * max(0.0, 1.0 - math.hypot(va, vb) / self.vn - c.cfprev_u_th)
             + c.cfprev_k_0 * v0 / self.vn)
        da = float(x[10])
        da = d if d > da else da + (d - da) * dt / c.cfprev_t_dec
        x[10] = min(da, c.cfprev_max_deg)
        return float(x[10])

    def update(self, t: float, dt: float, x: FloatArray, u: FloatArray,
               io: ControlIO) -> FloatArray:
        idf, udf = self._measure(x, float(u[0]), float(u[1]), dt)
        c = self.c
        lo, hi = c.alpha_min_deg, c.alpha_max_deg
        id_ord = float(u[2]) - c.margin_pu
        self._update_gamma(x, t, float(u[3]), float(u[4]), io)
        g = x[self._H:self._H + len(self.valves)]
        gmin = float(np.nanmin(g)) if x[8] >= len(self.valves) else math.nan
        dalpha = self._cfprev(x, u, dt)
        e_cc = idf - id_ord
        ki_cc = c.ki_deg * (c.fast_k if e_cc > c.fast_e_pu else 1.0)
        a_cc, i_cc = pi_step(float(x[4]), float(x[5]), e_cc, c.kp_deg, ki_cc, dt, lo, hi)
        if math.isnan(gmin):
            alpha, a_g, mode = a_cc, math.nan, 1.0
            x[6] = alpha  # gamma regulator waits at the current output
        else:
            # measured gamma limited for control: a failed commutation (gamma < 0) must not
            # throw the regulator to alpha_min through the proportional term
            e_g = min(max(gmin, 0.0), c.gamma_ref_deg + 45.0) - c.gamma_ref_deg
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
        alpha = min(max(alpha - dalpha, lo), hi)
        return np.array([alpha, a_cc, a_g, gmin, id_ord, idf, udf, mode, x[9], dalpha])
