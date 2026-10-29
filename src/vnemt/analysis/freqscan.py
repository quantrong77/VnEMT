"""Frequency scan of the network impedance seen from a three-phase bus (SPEC F5-07, G-12).

Phasor-domain nodal analysis of the netlist at each frequency:

* R, L, C as their admittances; transformers ``XF1`` as ``Gamma/(j w)`` (coupled windings)
  plus the magnetising inductance (unsaturated);
* ideal voltage sources short-circuited (their node is the reference), Norton sources reduce to
  their resistance, current sources open;
* switches and valves at their conductance in the initial state of the case (thyristors and
  diodes off), saturable inductors unsaturated;
* Bergeron lines as the exact long-line pi of each mode (``Zc sinh(gl)``, ``tanh(gl/2)/Zc``),
  ``g = sqrt((R' + j w L')(j w C'))``.

The positive-sequence impedance is ``V_a / I_a`` for the balanced injection ``I_a = 1``,
``I_b = a^2``, ``I_c = a`` at the bus nodes. Resonances between filters and the AC network
appear as peaks (parallel) and minima (series).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import scipy.sparse as sp
from numpy.typing import NDArray
from scipy.sparse.linalg import spsolve

from vnemt.core.lines import modal_parameters
from vnemt.core.switching import R_OFF_DEFAULT, R_ON_DEFAULT
from vnemt.errors import VnEMTError
from vnemt.model.netlist import Netlist, is_ground

ComplexArray = NDArray[np.complex128]


def _admittance_entries(net: Netlist, w: float,
                        idx: dict[str, int]) -> tuple[list[int], list[int], list[complex]]:
    rows: list[int] = []
    cols: list[int] = []
    vals: list[complex] = []

    def stamp(a: str, b: str, y: complex) -> None:
        ia, ib = idx.get(a, -1), idx.get(b, -1)
        for p, q, s in ((ia, ia, 1), (ib, ib, 1), (ia, ib, -1), (ib, ia, -1)):
            if p >= 0 and q >= 0:
                rows.append(p)
                cols.append(q)
                vals.append(s * y)

    def stamp_pair(n1: tuple[str, str], n2: tuple[str, str], y12: complex) -> None:
        """Mutual admittance between branches n1 and n2 (current in 1 from voltage of 2)."""
        for (p, sp_), (q, sq) in (((n1[0], 1), (n2[0], 1)), ((n1[0], 1), (n2[1], -1)),
                                  ((n1[1], -1), (n2[0], 1)), ((n1[1], -1), (n2[1], -1))):
            ip, iq = idx.get(p, -1), idx.get(q, -1)
            if ip >= 0 and iq >= 0:
                rows.append(ip)
                cols.append(iq)
                vals.append(sp_ * sq * y12)

    jw = 1j * w
    for el in net.elements:
        k = el.kind
        if k == "R":
            stamp(el.nodes[0], el.nodes[1], 1.0 / el.p("R_ohm"))
        elif k == "L" or k == "LSAT":
            stamp(el.nodes[0], el.nodes[1], 1.0 / (jw * el.p("L_H")))
        elif k == "C":
            stamp(el.nodes[0], el.nodes[1], jw * el.p("C_F"))
        elif k in ("V_dc", "V_ac") and el.p("R_ohm") > 0.0:
            stamp(el.nodes[0], el.nodes[1], 1.0 / el.p("R_ohm"))
        elif k == "SW":
            r = (el.p("R_on_ohm", R_ON_DEFAULT) if el.p("closed")
                 else el.p("R_off_ohm", R_OFF_DEFAULT))
            stamp(el.nodes[0], el.nodes[1], 1.0 / r)
        elif k in ("D", "T"):
            stamp(el.nodes[0], el.nodes[1], 1.0 / el.p("R_off_ohm", R_OFF_DEFAULT))
        elif k == "XF1":
            a = el.p("U1_V") / el.p("U2_V")
            g = 1.0 / (jw * el.p("L_k_H"))
            w1, w2 = (el.nodes[0], el.nodes[1]), (el.nodes[2], el.nodes[3])
            stamp(*w1, g)
            stamp(*w2, a * a * g)
            stamp_pair(w1, w2, -a * g)
            stamp_pair(w2, w1, -a * g)
            if el.p("Lm_H") > 0.0:
                stamp(*w1, 1.0 / (jw * el.p("Lm_H")))
        elif k == "LINE":
            T, zc, tau, rmod = modal_parameters(el)
            n = len(zc)
            length = el.p("length_km")
            lp = zc * tau / length  # modal L' = Zc sqrt(L' C') = Zc tau / length
            cp = tau / (zc * length)  # modal C' = sqrt(L' C') / Zc
            ser, sh = np.zeros(n, complex), np.zeros(n, complex)
            for j in range(n):
                z = rmod[j] / length + jw * lp[j]
                y = jw * cp[j]
                gl = np.sqrt(z * y) * length
                zcj = np.sqrt(z / y)
                ser[j] = 1.0 / (zcj * np.sinh(gl))
                sh[j] = np.tanh(gl / 2.0) / zcj
            ys = T @ np.diag(ser) @ T.T
            yh = T @ np.diag(sh) @ T.T
            kn, mn = el.nodes[:n], el.nodes[n:]
            for a in range(n):
                for b in range(n):
                    yab = complex(ys[a, b] + yh[a, b])
                    for side in (kn, mn):  # self/mutual at each end (to ground)
                        stamp_pair((side[a], "gnd"), (side[b], "gnd"), yab)
                    stamp_pair((kn[a], "gnd"), (mn[b], "gnd"), -complex(ys[a, b]))
                    stamp_pair((mn[a], "gnd"), (kn[b], "gnd"), -complex(ys[a, b]))
    return rows, cols, vals


def positive_sequence_impedance(net: Netlist, bus: Sequence[str],
                                freqs: Sequence[float]) -> ComplexArray:
    """``Z+(f)`` seen from the three-phase bus ``bus = (a, b, c)``."""
    shorted = {el.nodes[0] if is_ground(el.nodes[1]) else el.nodes[1] for el in net.elements
               if el.kind in ("V_dc", "V_ac") and el.p("R_ohm") <= 0.0}
    nodes = [n for n in net.nodes if n not in shorted]
    idx = {n: i for i, n in enumerate(nodes)}
    missing = [b for b in bus if b not in idx]
    if missing:
        raise VnEMTError(f"quét tần số: không có nút {missing} (hoặc nút bị nguồn áp áp đặt)")
    a = np.exp(2j * np.pi / 3)
    inj = np.zeros(len(nodes), complex)
    for k, b in enumerate(bus):
        inj[idx[b]] = (1.0, a * a, a)[k]
    out = np.zeros(len(freqs), complex)
    for i, f in enumerate(freqs):
        r, c, v = _admittance_entries(net, 2 * np.pi * f, idx)
        Y = sp.csc_matrix((v, (r, c)), shape=(len(nodes), len(nodes)))
        out[i] = complex(spsolve(Y, inj)[idx[bus[0]]])
    return out
