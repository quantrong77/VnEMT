"""Event schedule (SPEC F4-01...F4-06) expanded into circuit elements, source modulations,
misfires and control set-point changes.

Fault elements carry ``origin = "event"``, are appended after the base circuit and are not
part of the snapshot fingerprint, so one steady-state snapshot serves every fault scenario
(S-09, S-10). Fault switches use ``R_off = 1e9`` ohm (SPEC 5.1.1), close at ``t_s`` and are
cleared at the first current zero after ``t_s + duration`` (breaker / arc extinction).

============  ================================================================================
type          expansion
============  ================================================================================
ac_fault      per faulted phase a switch to an internal node, then ``r_ohm`` (+ ``x_ohm`` as an
              inductance) to ground (``3ph``, ``1ph`` = phase a, ``2phg`` = a, b) or between
              phases a and b (``2ph``)
ac_dip        EMF of the AC system multiplied by ``1 - depth_pct/100`` during the dip
dc_fault      pole-to-ground (or ``kind: pole_pole``) fault at the DC line node closest to
              ``position`` (0 = from end); Bergeron lines have nodes at their ends only;
              ``conductor`` selects the faulted conductor
valve_short   switch across the valve
misfire       the valve's first gate window after ``t_s`` is dropped
setpoint      control set-point change (``param`` of station ``station``) with a ramp
============  ================================================================================
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from vnemt.errors import CaseError
from vnemt.model.grid import Grid
from vnemt.model.netlist import Element

PH = ("a", "b", "c")
_SW = {"R_on_ohm": 1e-4, "R_off_ohm": 1e9, "open_at_zero": 1.0}


@dataclass
class ExpandedEvents:
    elements: list[Element] = field(default_factory=list)
    modulations: dict[str, list[tuple[float, float, float]]] = field(default_factory=dict)
    misfires: dict[str, float] = field(default_factory=dict)
    setpoints: dict[str, list[tuple[float, str, float, float]]] = field(default_factory=dict)
    # station -> [(t_s, param, value, ramp_s)]
    first_time: float = math.inf


def _switch(eid: str, a: str, b: str, t0: float, t1: float) -> Element:
    return Element(eid, "SW", (a, b), {**_SW, "t_close_s": t0, "t_open_s": t1}, "event")


def _impedance(eid: str, a: str, b: str, ev: Mapping[str, Any], f: float) -> list[Element]:
    r = max(float(ev.get("r_ohm", 0.01)), 1e-4)
    x = float(ev.get("x_ohm", 0.0))
    if x <= 0.0:
        return [Element(f"{eid}_R", "R", (a, b), {"R_ohm": r}, "event")]
    mid = f"{eid}_M"
    return [Element(f"{eid}_R", "R", (a, mid), {"R_ohm": r}, "event"),
            Element(f"{eid}_L", "L", (mid, b), {"L_H": x / (2 * math.pi * f)}, "event")]


def _bus_nodes(ev: Mapping[str, Any], grid: Grid, k: int) -> tuple[list[str], float]:
    loc = ev.get("location")
    if isinstance(loc, list):
        return [str(n) for n in loc], float(ev.get("f_Hz", 50.0))
    if loc in grid.ac_systems:
        return [f"{loc}_{p}" for p in PH], grid.ac_systems[loc].f_Hz
    raise CaseError(f"không có hệ AC '{loc}' (hoặc khai báo danh sách nút)",
                    path=f"events[{k}].location")


def _dc_node(ev: Mapping[str, Any], grid: Grid, k: int, conductor: int = 0) -> str:
    line = next((ln for ln in grid.dc_lines if ln.id == ev.get("line")), None)
    if line is None:
        raise CaseError(f"không có đường dây DC '{ev.get('line')}'", path=f"events[{k}].line")
    if line.model == "bergeron":  # no internal nodes: the end closest to ``position``
        from vnemt.systems.builder import neutral_node

        ends = line.from_ends if float(ev.get("position", 0.0)) < 0.5 else line.to_ends
        if conductor >= len(ends):
            raise CaseError(f"đường dây '{line.id}' có {len(ends)} dây",
                            path=f"events[{k}].conductor")
        x = ends[conductor]
        return neutral_node(grid, x[8:]) if x.startswith("neutral:") else f"{x}_POLE"
    n = line.sections
    cand = [(0.0, f"{line.from_station}_POLE"), (1.0, f"{line.to_station}_POLE")]
    if line.model == "t":
        cand += [((s - 0.5) / n, f"{line.id}_T{s}") for s in range(1, n + 1)]
    else:
        cand += [(s / n, f"{line.id}_N{s}") for s in range(1, n)]
    pos = float(ev.get("position", 0.5))
    return min(cand, key=lambda c: abs(c[0] - pos))[1]


def expand_events(events: list[Mapping[str, Any]], grid: Grid,
                  valves: Mapping[str, tuple[str, str]] | None = None) -> ExpandedEvents:
    """Expand the ``events`` section. ``valves`` maps thyristor ids to (anode, cathode)."""
    out = ExpandedEvents()
    for k, ev in enumerate(events):
        typ = ev["type"]
        t0 = float(ev["t_s"])
        t1 = t0 + float(ev.get("duration_ms", 0.0)) * 1e-3
        out.first_time = min(out.first_time, t0)
        eid = f"EV{k + 1}"
        if typ == "ac_fault":
            nodes, f = _bus_nodes(ev, grid, k)
            kind = ev.get("kind", "3ph")
            if kind == "2ph":
                fa, fb = f"{eid}_Fa", f"{eid}_Fb"
                out.elements += [_switch(f"{eid}_Sa", nodes[0], fa, t0, t1),
                                 *_impedance(eid, fa, fb, ev, f),
                                 _switch(f"{eid}_Sb", fb, nodes[1], t0, t1)]
                continue
            phases = {"3ph": (0, 1, 2), "1ph": (0,), "2phg": (0, 1)}.get(kind)
            if phases is None:
                raise CaseError(f"loại sự cố '{kind}' không hợp lệ", path=f"events[{k}].kind")
            fn = f"{eid}_F"
            for i in phases:
                out.elements.append(_switch(f"{eid}_S{PH[i]}", nodes[i], fn, t0, t1))
            out.elements += _impedance(eid, fn, "gnd", ev, f)
        elif typ == "ac_dip":
            loc = ev.get("location")
            if loc not in grid.ac_systems:
                raise CaseError(f"không có hệ AC '{loc}'", path=f"events[{k}].location")
            fac = 1.0 - float(ev["depth_pct"]) / 100.0
            for p in PH:
                out.modulations.setdefault(f"{loc}_V{p}", []).append((t0, t1, fac))
        elif typ == "dc_fault":
            cond = int(ev.get("conductor", 0))
            node = _dc_node(ev, grid, k, cond)
            out.elements.append(_switch(f"{eid}_S", node, f"{eid}_F", t0, t1))
            if ev.get("kind", "pole_ground") == "pole_pole":  # to the other pole conductor
                other = _dc_node(ev, grid, k, 1 if cond == 0 else 0)
                out.elements += _impedance(eid, f"{eid}_F", other, ev, 50.0)
            else:
                out.elements += _impedance(eid, f"{eid}_F", "gnd", ev, 50.0)
        elif typ in ("valve_short", "misfire"):
            v = str(ev["valve"])
            if valves is not None and v not in valves:
                raise CaseError(f"không có van '{v}'", path=f"events[{k}].valve")
            if typ == "misfire":
                out.misfires[v] = t0
            else:
                assert valves is not None
                a, c = valves[v]
                out.elements.append(_switch(f"{eid}_S", a, c, t0, t1))
        elif typ == "setpoint":
            out.setpoints.setdefault(str(ev["station"]), []).append(
                (t0, str(ev["param"]), float(ev["value"]), float(ev.get("ramp_s", 0.0))))
        else:
            raise CaseError(f"loại sự kiện '{typ}' chưa hỗ trợ", path=f"events[{k}].type")
    return out
