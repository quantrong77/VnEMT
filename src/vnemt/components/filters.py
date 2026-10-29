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

Double-tuned filters (F5-04) and the switching logic (F5-05) come with M4.

Reference: IEC TR 62001-1:2016, section 6; J. Arrillaga, N. R. Watson, *Power System
Harmonics*, 2nd ed., Wiley, 2003, ch. 9.
"""

from __future__ import annotations

import math

from vnemt.errors import CaseError
from vnemt.model.netlist import Element

Phases = tuple[str, str, str]


def filter_branches(id: str, bus: Phases, kind: str, Q_Mvar: float, U_kV: float, f_Hz: float,
                    h: float | None = None, q: float | None = None) -> list[Element]:
    """Elements of a grounded-star filter ``<id>_<a|b|c>_<R|L|C>``."""
    if Q_Mvar <= 0.0:
        raise CaseError(f"bộ lọc '{id}': Q_Mvar phải > 0")
    w = 2.0 * math.pi * f_Hz
    u2 = (U_kV * 1e3) ** 2
    q_var = Q_Mvar * 1e6
    els: list[Element] = []
    if kind == "capacitor":
        c = q_var / (w * u2)
        for p, node in zip("abc", bus, strict=True):
            els.append(Element(f"{id}_{p}_C", "C", (node, "gnd"), {"C_F": c}))
        return els
    if kind not in ("single_tuned", "high_pass"):
        raise CaseError(f"bộ lọc '{id}': loại '{kind}' chưa hỗ trợ")
    if h is None or h <= 1.0:
        raise CaseError(f"bộ lọc '{id}': cần bậc điều chỉnh h > 1")
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
