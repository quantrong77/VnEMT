"""Three-phase two-winding transformer from three single-phase units ``XF1`` (SPEC section 6,
F1-L02, F5-02 partial: fixed tap; saturation and OLTC dynamics come with M4).

Per unit ``k`` (phase a, b, c), winding 1 is star-connected (phase ``k`` to the HV neutral).
Winding 2 is

* ``"y"``: star, phase ``k`` to the LV neutral, ratio ``a = U1/U2``;
* ``"d"``: delta, across LV phases ``k`` and ``k+1`` (a-b, b-c, c-a), ratio
  ``a = (U1/sqrt3)/U2``. The LV line voltage ``v_ab`` is then in phase with the HV phase
  voltage ``v_a``, i.e. it lags the HV line voltage by 30 deg (vector group Yd1).

Leakage reactance ``x_k`` [pu on ``S``, ``U1``] referred to winding 1:
``L_k = x_k U1^2 / (S omega)``. The tap multiplies the HV rated voltage (``U1 * tap``).

Reference: H. W. Dommel, *EMTP Theory Book*, ch. 6; IEC 60076-1 (vector groups).
"""

from __future__ import annotations

import math

from vnemt.errors import CaseError
from vnemt.model.netlist import Element

Phases = tuple[str, str, str]


def three_phase_transformer(
    id: str,
    hv: Phases,
    lv: Phases,
    S_MVA: float,
    U1_kV: float,
    U2_kV: float,
    xk_pu: float,
    f_Hz: float,
    winding2: str = "y",
    hv_neutral: str = "gnd",
    lv_neutral: str = "gnd",
    tap: float = 1.0,
    Lm_pu: float | None = None,
) -> list[Element]:
    """Elements ``<id>a``, ``<id>b``, ``<id>c`` (type XF1) of a Yy0 or Yd1 transformer."""
    if winding2 not in ("y", "d"):
        raise CaseError(f"MBA '{id}': winding2 phải là 'y' hoặc 'd', nhận '{winding2}'")
    if min(S_MVA, U1_kV, U2_kV, xk_pu, tap) <= 0.0:
        raise CaseError(f"MBA '{id}': S_MVA, U1_kV, U2_kV, xk_pu, tap phải > 0")
    u1 = U1_kV * 1e3 * tap
    u2 = U2_kV * 1e3
    w = 2.0 * math.pi * f_Hz
    zb = u1 * u1 / (S_MVA * 1e6)
    params: dict[str, float] = {
        "U1_V": u1 / math.sqrt(3.0),
        "U2_V": u2 if winding2 == "d" else u2 / math.sqrt(3.0),
        "L_k_H": xk_pu * zb / w,
    }
    if Lm_pu is not None:
        params["Lm_H"] = Lm_pu * zb / w
    els = []
    for k, ph in enumerate("abc"):
        k2, m2 = (lv[k], lv[(k + 1) % 3]) if winding2 == "d" else (lv[k], lv_neutral)
        els.append(Element(f"{id}{ph}", "XF1", (hv[k], hv_neutral, k2, m2), dict(params)))
    return els
