"""Circuit-level netlist shared by all solvers.

This is the EMT-level view of the common grid data model (SPEC-phan-tich-luoi 2.1). From
v0.4 a bus-branch model (``model/grid.py``) will be expanded into a :class:`Netlist`, so the
netlist keeps node names as strings and holds no solver-specific data. All values are SI.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

ElementKind = Literal["R", "L", "C", "V_dc", "V_ac", "I_dc", "I_ac", "SW", "D", "T", "XF1"]
Param = float | tuple[float, ...]

GROUND_NAMES: frozenset[str] = frozenset({"0", "gnd", "GND", "ground"})


def is_ground(node: str) -> bool:
    """True if ``node`` names the reference (ground) node."""
    return node in GROUND_NAMES


@dataclass(frozen=True)
class Element:
    """One circuit element.

    Two-terminal elements have ``nodes = (k, m)``; for sources ``k`` is the positive terminal.
    Positive branch current flows from ``k`` to ``m`` through the element (for sources: from
    ``m`` to ``k`` inside the source, i.e. a positive source current is injected into ``k``).
    The single-phase transformer ``XF1`` has ``nodes = (k1, m1, k2, m2)`` (winding 1, winding 2;
    ``k`` is the dotted terminal).
    """

    id: str
    kind: ElementKind
    nodes: tuple[str, ...]
    params: Mapping[str, Param] = field(default_factory=dict)
    origin: str = "case"  # "event": generated from the event schedule (not in snapshots)

    def p(self, key: str, default: float = 0.0) -> float:
        """Scalar parameter."""
        v = self.params.get(key, default)
        if isinstance(v, tuple):
            raise TypeError(f"{self.id}.{key} is a list, expected a scalar")
        return float(v)

    def times(self, key: str) -> tuple[float, ...]:
        """Parameter given as a scalar or a list, returned as a tuple."""
        v = self.params.get(key)
        if v is None:
            return ()
        return v if isinstance(v, tuple) else (float(v),)


@dataclass
class Netlist:
    """Ordered list of elements; node order is the first-seen order (deterministic, Q-02)."""

    elements: list[Element]

    @property
    def nodes(self) -> list[str]:
        """Non-ground node names in first-seen order."""
        seen: dict[str, None] = {}
        for el in self.elements:
            for n in el.nodes:
                if not is_ground(n):
                    seen.setdefault(n, None)
        return list(seen)

    def base_nodes(self) -> set[str]:
        """Nodes used by non-event elements."""
        return {x for el in self.elements if el.origin != "event" for x in el.nodes
                if not is_ground(x)}

    def element(self, eid: str) -> Element:
        for el in self.elements:
            if el.id == eid:
                return el
        raise KeyError(eid)


def build_netlist(case: Mapping[str, Any]) -> Netlist:
    """Build a :class:`Netlist` from the ``circuit`` section of a validated case dict."""
    elements: list[Element] = []
    for raw in case.get("circuit", {}).get("elements", []):
        params: dict[str, Param] = {
            k: tuple(float(x) for x in v) if isinstance(v, list) else float(v)
            for k, v in raw.items()
            if k not in ("id", "type", "nodes")
        }
        nodes = tuple(str(n) for n in raw["nodes"])
        elements.append(Element(id=raw["id"], kind=raw["type"], nodes=nodes, params=params))
    return Netlist(elements)
