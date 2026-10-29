"""Static AC filter branches sized from reactive power (SPEC section 6, F5-04 partial).

Each filter is three star-connected (grounded) phase branches. With ``U`` the line voltage
(rms), ``Q`` the three-phase reactive power delivered at the fundamental ``omega`` and ``h``
the tuning order:

* capacitor:      ``C = Q / (omega U^2)``
* single tuned:   series R-L-C; ``X_C (1 - 1/h^2) = U^2/Q`` so the branch delivers exactly
  ``Q`` at the fundamental; ``L = 1 / (h^2 omega^2 C)``; ``R = h omega L / q`` (quality
  factor ``q``, default 40)
* high pass (2nd order): C in series with ``L || R``; ``C`` and ``L`` as for the single-tuned
  branch, ``R = q h omega L`` (``q`` default 1.5). The fundamental Q differs from ``Q`` by
  less than 1 % for ``h >= 10``.
* double tuned ``(h, h2)``: two single-tuned branches ``(La, Ca)`` at ``h`` and ``(Lb, Cb)`` at
  ``h2``, each ``Q/2``, converted to the series ``C1-L1`` + parallel ``C2 || L2`` form::

      C1 = Ca + Cb                      L1 = La Lb / (La + Lb)
      C2 = Ca Cb (Ca + Cb)(La + Lb)^2 / (La Ca - Lb Cb)^2
      L2 = (La Ca - Lb Cb)^2 / ((Ca + Cb)^2 (La + Lb))

  with a damping resistor ``R = q w_p L2`` across the parallel part (``w_p`` its resonance,
  ``q`` default 40). The impedance minima are at ``h`` and ``h2``.
* C-type ``(h)``: ``C1`` in series with ``(L + C2) || R``; ``L``-``C2`` resonate at the
  fundamental (no fundamental loss in ``R``), so ``Q = omega C1 U^2`` exactly;
  ``L = 1/(omega^2 C1 (h^2 - 1))`` places the series resonance at ``h``; ``R = q h omega L``
  (``q`` default 2).

``switchable`` filters get a breaker per phase ``<id>_<a|b|c>_CB`` (opens at current zero),
closed initially unless ``closed`` is false (reactive power control, F5-05).

Reference: IEC TR 62001-1:2016, section 6; J. Arrillaga, N. R. Watson, *Power System
Harmonics*, 2nd ed., Wiley, 2003, ch. 9.
"""

from __future__ import annotations

import math

from vnemt.errors import CaseError
from vnemt.model.netlist import Element

Phases = tuple[str, str, str]


def _tuned(q_var: float, u2: float, w: float, h: float) -> tuple[float, float]:
    """``(L, C)`` of a series branch delivering ``q_var`` at the fundamental, tuned at ``h``."""
    xc = u2 / q_var * h * h / (h * h - 1.0)
    c = 1.0 / (w * xc)
    return 1.0 / (h * h * w * w * c), c


def filter_branches(id: str, bus: Phases, kind: str, Q_Mvar: float, U_kV: float, f_Hz: float,
                    h: float | None = None, q: float | None = None, h2: float | None = None,
                    switchable: bool = False, closed: bool = True) -> list[Element]:
    """Elements of a grounded-star filter ``<id>_<a|b|c>_<R|L|C...>``."""
    if Q_Mvar <= 0.0:
        raise CaseError(f"bộ lọc '{id}': Q_Mvar phải > 0")
    els: list[Element] = []
    if switchable:
        inner = tuple(f"{id}_{p}_in" for p in "abc")
        for p, b, n in zip("abc", bus, inner, strict=True):
            params: dict[str, float] = {"R_on_ohm": 1e-4, "R_off_ohm": 1e9, "open_at_zero": 1.0,
                                        "closed": 1.0 if closed else 0.0}
            els.append(Element(f"{id}_{p}_CB", "SW", (b, n), params))
        bus = inner  # type: ignore[assignment]
    return els + _filter(id, bus, kind, Q_Mvar, U_kV, f_Hz, h, q, h2)


def _filter(id: str, bus: Phases, kind: str, Q_Mvar: float, U_kV: float, f_Hz: float,
            h: float | None, q: float | None, h2: float | None) -> list[Element]:
    w = 2.0 * math.pi * f_Hz
    u2 = (U_kV * 1e3) ** 2
    q_var = Q_Mvar * 1e6
    els: list[Element] = []
    if kind == "capacitor":
        c = q_var / (w * u2)
        for p, node in zip("abc", bus, strict=True):
            els.append(Element(f"{id}_{p}_C", "C", (node, "gnd"), {"C_F": c}))
        return els
    if kind not in ("single_tuned", "high_pass", "double_tuned", "c_type"):
        raise CaseError(f"bộ lọc '{id}': loại '{kind}' chưa hỗ trợ")
    if h is None or h <= 1.0:
        raise CaseError(f"bộ lọc '{id}': cần bậc điều chỉnh h > 1")
    if kind == "double_tuned":
        if h2 is None or h2 <= 1.0 or h2 == h:
            raise CaseError(f"bộ lọc '{id}': lọc kép cần h2 > 1, khác h")
        la, ca = _tuned(q_var / 2, u2, w, h)
        lb, cb = _tuned(q_var / 2, u2, w, h2)
        c1, l1 = ca + cb, la * lb / (la + lb)
        d = la * ca - lb * cb
        c2 = ca * cb * (ca + cb) * (la + lb) ** 2 / d**2
        l2 = d**2 / ((ca + cb) ** 2 * (la + lb))
        r2 = (q if q is not None else 40.0) * l2 / math.sqrt(l2 * c2)
        for p, node in zip("abc", bus, strict=True):
            m1, m2 = f"{id}_{p}_1", f"{id}_{p}_2"
            els += [Element(f"{id}_{p}_C1", "C", (node, m1), {"C_F": c1}),
                    Element(f"{id}_{p}_L1", "L", (m1, m2), {"L_H": l1}),
                    Element(f"{id}_{p}_C2", "C", (m2, "gnd"), {"C_F": c2}),
                    Element(f"{id}_{p}_L2", "L", (m2, "gnd"), {"L_H": l2}),
                    Element(f"{id}_{p}_R", "R", (m2, "gnd"), {"R_ohm": r2})]
        return els
    if kind == "c_type":
        c1 = q_var / (w * u2)
        lc = 1.0 / (w * w * c1 * (h * h - 1.0))
        c2 = 1.0 / (w * w * lc)
        r = (q if q is not None else 2.0) * h * w * lc
        for p, node in zip("abc", bus, strict=True):
            m1, m2 = f"{id}_{p}_1", f"{id}_{p}_2"
            els += [Element(f"{id}_{p}_C1", "C", (node, m1), {"C_F": c1}),
                    Element(f"{id}_{p}_L", "L", (m1, m2), {"L_H": lc}),
                    Element(f"{id}_{p}_C2", "C", (m2, "gnd"), {"C_F": c2}),
                    Element(f"{id}_{p}_R", "R", (m1, "gnd"), {"R_ohm": r})]
        return els
    xc = u2 / q_var * h * h / (h * h - 1.0)
    c = 1.0 / (w * xc)
    lv = 1.0 / (h * h * w * w * c)
    for p, node in zip("abc", bus, strict=True):
        m1, m2 = f"{id}_{p}_1", f"{id}_{p}_2"
        if kind == "single_tuned":
            r = h * w * lv / (q if q is not None else 40.0)
            els += [Element(f"{id}_{p}_C", "C", (node, m1), {"C_F": c}),
                    Element(f"{id}_{p}_L", "L", (m1, m2), {"L_H": lv}),
                    Element(f"{id}_{p}_R", "R", (m2, "gnd"), {"R_ohm": r})]
        else:
            r = (q if q is not None else 1.5) * h * w * lv
            els += [Element(f"{id}_{p}_C", "C", (node, m1), {"C_F": c}),
                    Element(f"{id}_{p}_L", "L", (m1, "gnd"), {"L_H": lv}),
                    Element(f"{id}_{p}_R", "R", (m1, "gnd"), {"R_ohm": r})]
    return els
