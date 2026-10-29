"""Six-pulse Graetz bridge built from thyristor valves (SPEC F1-L01, S-12, S-14).

Valve numbering follows the firing order (IEC 60633 / textbook convention)::

    1: a -> P     3: b -> P     5: c -> P      (upper group, anode at the AC terminal)
    4: N -> a     6: N -> b     2: N -> c      (lower group)

so valves fire in the sequence 1, 2, 3, 4, 5, 6 every 60 degrees and valve ``k`` commutates
the current from valve ``k - 2`` of the same group.

Ideal relations used for verification (constant DC current ``I_d``, commutating line voltage
``U_LL`` rms behind a commutating reactance ``X_c`` per phase):

    U_d  = (3 sqrt2 / pi) U_LL cos(alpha) - (3 / pi) X_c I_d
    cos(alpha + mu) = cos(alpha) - sqrt2 X_c I_d / U_LL
    gamma = 180 deg - alpha - mu,  i.e.  cos(gamma) = cos(beta) + sqrt2 X_c I_d / U_LL

Reference: J. Arrillaga, *High Voltage Direct Current Transmission*, 2nd ed., IEE, 1998,
ch. 2; E. W. Kimbark, *Direct Current Transmission*, vol. 1, Wiley, 1971, ch. 3.
"""

from __future__ import annotations

from collections.abc import Mapping

from vnemt.model.netlist import Element, Param

FIRING_ORDER = (1, 2, 3, 4, 5, 6)
# (anode, cathode) in terms of AC terminal letter or "P"/"N"
_VALVE_NODES = {1: ("a", "P"), 2: ("N", "c"), 3: ("b", "P"),
                4: ("N", "a"), 5: ("c", "P"), 6: ("N", "b")}


def six_pulse_bridge(
    prefix: str,
    ac: tuple[str, str, str],
    p: str,
    n: str,
    valve: Mapping[str, Param] | None = None,
    snubber: tuple[float, float] | None = None,
) -> tuple[list[Element], list[str]]:
    """Elements of a six-pulse bridge and the valve ids in firing order.

    Parameters
    ----------
    prefix : str
        Valve ids are ``<prefix>1`` ... ``<prefix>6``.
    ac : (a, b, c)
        AC terminal nodes.
    p, n : str
        DC positive and negative terminals.
    valve : mapping, optional
        Thyristor parameters (``R_on_ohm``, ``R_off_ohm``, ``V_f_V``, ``t_q_s`` ...).
    snubber : (R_ohm, C_F), optional
        Series RC snubber across every valve (SPEC S-14).
    """
    term = {"a": ac[0], "b": ac[1], "c": ac[2], "P": p, "N": n}
    els: list[Element] = []
    ids: list[str] = []
    for k in FIRING_ORDER:
        an, ca = (term[x] for x in _VALVE_NODES[k])
        vid = f"{prefix}{k}"
        els.append(Element(vid, "T", (an, ca), dict(valve or {})))
        if snubber is not None:
            mid = f"{vid}_sn"
            els.append(Element(f"{vid}_Rs", "R", (an, mid), {"R_ohm": snubber[0]}))
            els.append(Element(f"{vid}_Cs", "C", (mid, ca), {"C_F": snubber[1]}))
        ids.append(vid)
    return els, ids
