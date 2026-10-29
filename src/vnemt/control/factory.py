"""Build controllers from the ``controls`` section of a validated case."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from vnemt.control.base import Controller
from vnemt.control.epc import Epc6
from vnemt.control.pll import PllSrf


def build_controllers(items: Sequence[Mapping[str, Any]]) -> list[Controller]:
    out: list[Controller] = []
    for c in items:
        ctl: Controller
        if c["type"] == "pll":
            va, vb, vc = c["inputs"]
            ctl = PllSrf(c["id"], va, vb, vc, f0_Hz=c["f0_Hz"], kp=c.get("kp"), ki=c.get("ki"),
                         theta0_deg=c.get("theta0_deg", 0.0))
        else:  # epc6 (schema guarantees the type)
            ctl = Epc6(c["id"], c["pll"], list(c["valves"]), alpha_deg=c.get("alpha_deg"),
                       alpha_signal=c.get("alpha_signal"), offset_deg=c.get("offset_deg", 0.0),
                       pulse_deg=c.get("pulse_deg", 120.0))
        ctl.every = int(c.get("every", 1))
        out.append(ctl)
    return out
