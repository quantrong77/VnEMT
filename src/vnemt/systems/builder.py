"""Expand the system-level :class:`~vnemt.model.grid.Grid` into circuit elements and
controllers (SPEC 9.1; F1-L01, F1-L02, F1-L06; F3-01...F3-03).

Generated names (``<x>`` = phase a, b, c):

=====================  ===================================================================
AC system ``S``        EMF node ``S_E<x>``, bus ``S_<x>``; elements ``S_V<x>``, ``S_R<x>``,
                       ``S_L<x>``
Station ``K``          valve-side nodes ``K_Y<x>`` (Yy0) and ``K_D<x>`` (Yd1, 12-pulse);
                       valves ``K_Y1..6``, ``K_D1..6`` (firing order); converter DC terminal
                       ``K_DC``; pole node ``K_POLE``; smoothing reactor ``K_Ls`` (positive
                       current from rectifier to line, from line into inverter); filters
                       ``K_F<n>_...``; controllers ``K_PLL``, ``K_CTRL``, ``K_EPCY``,
                       ``K_EPCD``
DC line ``L``          series ``L_R<k>``, ``L_L<k>``, shunt ``L_C<k>``
=====================  ===================================================================

Poles and neutral: each station is one pole of one end. Without ``dc_network.electrodes``
the station neutrals are ground; otherwise every end has a neutral bus ``<end>_NEU``, with an
electrode resistance ``<end>_RE`` to ground where one is given (ground return, bipole) and
floating otherwise (metallic return through a line conductor ``neutral:<end>``).

Bridge orientation follows the current direction: the cathode terminal P points to the pole
for the positive-pole rectifier and the negative-pole inverter, and to the neutral for the two
others. The smoothing reactor current is measured in the direction of the converter current, so
``Id > 0`` at every station, and controls use ``Ud = sign(pole) (v_DC - v_neutral)``.

For a 12-pulse station the Yd1 bridge sees valve-side voltages lagging the AC bus by 30 deg,
hence its EPC uses ``offset_deg = +30``.
"""

from __future__ import annotations

import math

from vnemt.components.filters import filter_branches
from vnemt.components.transformer import three_phase_transformer
from vnemt.control.base import Controller
from vnemt.control.epc import Epc6
from vnemt.control.lcc import LccInverterControl, LccRectifierControl
from vnemt.control.pll import PllSrf
from vnemt.control.station import ReactivePowerControl, TapChangerControl
from vnemt.model.grid import ConverterStation, DcLine, Grid
from vnemt.model.netlist import Element
from vnemt.power_electronics.lcc_bridge import six_pulse_bridge

PH = ("a", "b", "c")


def _ac_system(grid: Grid, sid: str) -> list[Element]:
    a = grid.ac_systems[sid]
    r, lv = a.impedance()
    upk = a.U_pu * a.U_kV * 1e3 * math.sqrt(2.0 / 3.0)
    els: list[Element] = []
    for k, p in enumerate(PH):
        e, m, bus = f"{sid}_E{p}", f"{sid}_M{p}", f"{sid}_{p}"
        els += [
            Element(f"{sid}_V{p}", "V_ac", (e, "gnd"),
                    {"U_peak_V": upk, "f_Hz": a.f_Hz, "phase_deg": a.phase_deg - 120.0 * k}),
            Element(f"{sid}_R{p}", "R", (e, m), {"R_ohm": r}),
            Element(f"{sid}_L{p}", "L", (m, bus), {"L_H": lv}),
        ]
    return els


def neutral_node(grid: Grid, end: str) -> str:
    return "gnd" if grid.electrodes is None else f"{end}_NEU"


def _station(grid: Grid, st: ConverterStation) -> tuple[list[Element], list[str], list[str]]:
    """Elements, valve ids, and bridge prefixes of one station."""
    ac = grid.ac_systems[st.ac_system]
    bus = tuple(f"{st.ac_system}_{p}" for p in PH)
    tr = st.transformer
    k = st.id
    els: list[Element] = []
    bridges = ["Y"] if st.type == "lcc_6pulse" else ["Y", "D"]
    for b in bridges:
        els += three_phase_transformer(
            f"{k}_T{b}", bus, tuple(f"{k}_{b}{p}" for p in PH), tr.S_MVA, tr.U1_kV,  # type: ignore[arg-type]
            tr.U2_kV, tr.xk_pu, ac.f_Hz, winding2="y" if b == "Y" else "d",
            lv_neutral=f"{k}_YN", tap=tr.tap)
    # series connection: terminals from the neutral to the converter DC terminal
    dc = f"{k}_DC"
    neu = neutral_node(grid, st.end_id)
    nodes = [neu, f"{k}_MID", dc] if len(bridges) == 2 else [neu, dc]
    valves: list[str] = []
    for i, b in enumerate(bridges):
        lo, hi = nodes[i], nodes[i + 1]
        p, n = (hi, lo) if st.p_at_pole else (lo, hi)
        bel, ids = six_pulse_bridge(f"{k}_{b}", tuple(f"{k}_{b}{q}" for q in PH),  # type: ignore[arg-type]
                                    p, n, valve=st.valve, snubber=st.snubber)
        els += bel
        valves += ids
    pole = f"{k}_POLE"
    ls = (dc, pole) if st.p_at_pole else (pole, dc)
    els.append(Element(f"{k}_Ls", "L", ls, {"L_H": st.smoothing_reactor_H}))
    for i, f in enumerate(st.filters, start=1):
        els += filter_branches(f"{k}_F{i}", bus, f.kind, f.Q_Mvar, ac.U_kV, ac.f_Hz,  # type: ignore[arg-type]
                               h=f.h, q=f.q, h2=f.h2, switchable=f.switchable, closed=f.closed)
    return els, valves, bridges


def _endpoint(grid: Grid, x: str) -> str:
    return neutral_node(grid, x[len("neutral:"):]) if x.startswith("neutral:") else f"{x}_POLE"


def _dc_line(grid: Grid, ln: DcLine) -> list[Element]:
    if ln.model == "bergeron":
        nodes = tuple(_endpoint(grid, x) for x in ln.from_ends + ln.to_ends)
        n = len(ln.from_ends)
        params: dict[str, float | tuple[float, ...]] = {
            "length_km": ln.length_km,
            "L_H_per_km": ln.L_H_per_km if n > 1 else ln.L_H_per_km[0],
            "C_F_per_km": ln.C_F_per_km if n > 1 else ln.C_F_per_km[0],
            "R_ohm_per_km": ln.R_ohm_per_km if len(ln.R_ohm_per_km) > 1 else ln.R_ohm_per_km[0],
        }
        return [Element(ln.id, "LINE", nodes, params)]
    a, b = f"{ln.from_station}_POLE", f"{ln.to_station}_POLE"
    n = ln.sections
    els: list[Element] = []
    r, lv, c = ln.R_ohm / n, ln.L_H / n, ln.C_F / n
    node = a
    for s in range(1, n + 1):
        end = b if s == n else f"{ln.id}_N{s}"
        if ln.model == "t":  # R/2 L/2 - C - R/2 L/2
            mid = f"{ln.id}_T{s}"
            els += [Element(f"{ln.id}_R{s}a", "R", (node, f"{ln.id}_X{s}a"), {"R_ohm": r / 2}),
                    Element(f"{ln.id}_L{s}a", "L", (f"{ln.id}_X{s}a", mid), {"L_H": lv / 2}),
                    Element(f"{ln.id}_C{s}", "C", (mid, "gnd"), {"C_F": c}),
                    Element(f"{ln.id}_R{s}b", "R", (mid, f"{ln.id}_X{s}b"), {"R_ohm": r / 2}),
                    Element(f"{ln.id}_L{s}b", "L", (f"{ln.id}_X{s}b", end), {"L_H": lv / 2})]
        else:  # pi: C/2 - R L - C/2
            els += [Element(f"{ln.id}_C{s}a", "C", (node, "gnd"), {"C_F": c / 2}),
                    Element(f"{ln.id}_R{s}", "R", (node, f"{ln.id}_X{s}"), {"R_ohm": r}),
                    Element(f"{ln.id}_L{s}", "L", (f"{ln.id}_X{s}", end), {"L_H": lv}),
                    Element(f"{ln.id}_C{s}b", "C", (end, "gnd"), {"C_F": c / 2})]
        node = end
    return els


def build_system(grid: Grid, setpoints: dict[str, list[tuple[float, str, float, float]]]
                 | None = None) -> tuple[list[Element], list[Controller]]:
    """Circuit elements and ordered controllers of the whole system.

    ``setpoints`` maps a station id to its set-point changes (``setpoint`` events).
    """
    setpoints = setpoints or {}
    els: list[Element] = []
    for sid in grid.ac_systems:
        els += _ac_system(grid, sid)
    pll: list[Controller] = []
    ctrl: list[Controller] = []
    epc: list[Controller] = []
    slow: list[Controller] = []
    recs = {s.pole: s for s in grid.stations.values() if s.role == "rectifier"}
    stations = sorted(grid.stations.values(), key=lambda s: s.role != "rectifier")
    for st in stations:
        sel, _, bridges = _station(grid, st)
        els += sel
        assert grid.base is not None
        ib, ub = grid.base.I_A, grid.base.U_dc_kV * 1e3
        va, vb, vc = (f"{st.ac_system}_{p}.V" for p in PH)
        f = grid.ac_systems[st.ac_system].f_Hz
        pll.append(PllSrf(f"{st.id}_PLL", va, vb, vc, f0_Hz=f))
        id_sig, ud_sig = f"{st.id}_Ls.I", f"{st.id}_DC.V"
        neu = neutral_node(grid, st.end_id)
        ud_ref = None if neu == "gnd" else f"{neu}.V"
        sign = 1.0 if st.pole == "positive" else -1.0
        v_n = grid.ac_systems[st.ac_system].U_kV * 1e3 * math.sqrt(2.0 / 3.0)
        if st.role == "rectifier":
            ctrl.append(LccRectifierControl(f"{st.id}_CTRL", id_sig, ud_sig, ib, ub,
                                            st.control, vm_signal=f"{st.id}_PLL.Vm", V_n=v_n,
                                            setpoints=setpoints.get(st.id),
                                            ud_ref_signal=ud_ref, ud_sign=sign))
        else:
            rec = recs[st.pole]
            groups = [([f"{st.id}_{b}{i}" for i in range(1, 7)], 0.0 if b == "Y" else 30.0)
                      for b in bridges]
            ctrl.append(LccInverterControl(f"{st.id}_CTRL", id_sig, ud_sig,
                                           f"{rec.id}_CTRL.Id_ord", f"{st.id}_PLL", groups,
                                           ib, ub, st.control, bus=(va, vb, vc), V_n=v_n,
                                           ud_ref_signal=ud_ref, ud_sign=sign))
        for b in bridges:
            ids = [f"{st.id}_{b}{i}" for i in range(1, 7)]
            epc.append(Epc6(f"{st.id}_EPC{b}", f"{st.id}_PLL", ids,
                            alpha_signal=f"{st.id}_CTRL.alpha",
                            offset_deg=0.0 if b == "Y" else 30.0))
        if st.oltc is not None:
            sig = f"{st.id}_CTRL.alpha" if st.role == "rectifier" else f"{st.id}_CTRL.Ud"
            units = [f"{st.id}_T{b}{p}" for b in bridges for p in PH]
            slow.append(TapChangerControl(f"{st.id}_TAP", sig, units, st.role, st.oltc))
        if st.q_control is not None:
            # one reactive power control per end: all switchable groups of the end's poles
            sw = [(o.id, i, flt) for o in stations if o.end_id == st.end_id
                  for i, flt in enumerate(o.filters, start=1) if flt.switchable]
            breakers = [[f"{sid}_F{i}_{p}_CB" for p in PH] for sid, i, _ in sw]
            closed0: list[bool] = [flt.closed for _, _, flt in sw]
            slow.append(ReactivePowerControl(
                f"{st.id}_QC", [f"{st.ac_system}_{p}.V" for p in PH],
                [f"{st.ac_system}_L{p}.I" for p in PH], breakers, closed0, st.q_control))
    for ln in grid.dc_lines:
        els += _dc_line(grid, ln)
    for end, r in (grid.electrodes or {}).items():
        els.append(Element(f"{end}_RE", "R", (f"{end}_NEU", "gnd"), {"R_ohm": r}))
    return els, pll + ctrl + epc + slow
