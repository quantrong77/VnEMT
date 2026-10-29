"""System-level grid data model shared by the EMT core and the phasor core (v0.4).

SPEC-phan-tich-luoi 2.1: one data model for every analysis. These dataclasses hold equipment
data in engineering form (kV, MVA, pu on equipment base) exactly as the user gives it; the
EMT builder (:mod:`vnemt.systems.builder`) expands them into a circuit :class:`Netlist`, and
the phasor core will read the same objects for load flow and short circuit.

Thevenin AC system (SPEC section 6): ``|Z| = U^2 / (SCR * P_dc)`` at impedance angle
``angle_deg`` (``R = |Z| cos phi``, ``X = |Z| sin phi``); the source EMF is ``U_pu * U_kV``
(line, rms) at ``phase_deg`` (phase *a*, sine reference).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from vnemt.errors import CaseError


@dataclass(frozen=True)
class AcSystem:
    id: str
    U_kV: float
    f_Hz: float
    scr: float
    angle_deg: float
    P_dc_MW: float
    U_pu: float = 1.0
    phase_deg: float = 0.0

    def impedance(self) -> tuple[float, float]:
        """``(R_ohm, L_H)`` of the Thevenin impedance per phase."""
        z = (self.U_kV * 1e3) ** 2 / (self.scr * self.P_dc_MW * 1e6)
        phi = math.radians(self.angle_deg)
        return z * math.cos(phi), z * math.sin(phi) / (2.0 * math.pi * self.f_Hz)


@dataclass(frozen=True)
class ConverterTransformer:
    """Per six-pulse bridge (12-pulse stations have one Yy0 and one Yd1 unit)."""

    S_MVA: float
    U1_kV: float
    U2_kV: float
    xk_pu: float
    tap: float = 1.0

    def commutating_reactance(self, f_Hz: float) -> float:
        """Leakage reactance referred to the valve side [ohm]."""
        return self.xk_pu * (self.U2_kV * 1e3) ** 2 / (self.S_MVA * 1e6)


@dataclass(frozen=True)
class AcFilter:
    kind: str  # capacitor | single_tuned | high_pass
    Q_Mvar: float
    h: float | None = None
    q: float | None = None


@dataclass(frozen=True)
class LccControl:
    """Station control settings (pu on the DC base)."""

    Id_ref_pu: float = 1.0
    Id_start_pu: float = 0.1
    ramp_start_s: float = 0.05
    ramp_s: float = 0.3
    alpha_min_deg: float = 5.0
    alpha_max_deg: float = 165.0
    alpha_start_deg: float = 90.0
    kp_deg: float = 60.0  # deg per pu current error
    ki_deg: float = 1200.0  # deg per (pu s): Ti = 50 ms
    T_id_s: float = 0.0012
    T_ud_up_s: float = 0.04
    T_ud_down_s: float = 0.01
    vdcol: tuple[float, float, float, float] | None = (0.4, 0.9, 0.55, 1.0)  # u_lo, u_hi, i_lo, i_hi
    gamma_ref_deg: float = 15.0
    margin_pu: float = 0.1
    ki_gamma: float = 20.0  # 1/s, feedback correction of predictive CEA


@dataclass(frozen=True)
class ConverterStation:
    id: str
    type: str  # lcc_6pulse | lcc_12pulse
    role: str  # rectifier | inverter
    ac_system: str
    transformer: ConverterTransformer
    smoothing_reactor_H: float
    filters: tuple[AcFilter, ...] = ()
    control: LccControl = LccControl()
    valve: Mapping[str, float] = field(default_factory=dict)
    snubber: tuple[float, float] | None = None


@dataclass(frozen=True)
class DcLine:
    id: str
    from_station: str
    to_station: str
    model: str  # t | pi
    R_ohm: float
    L_H: float
    C_F: float
    sections: int = 1


@dataclass(frozen=True)
class DcBase:
    S_MVA: float
    U_dc_kV: float

    @property
    def I_A(self) -> float:
        return self.S_MVA * 1e6 / (self.U_dc_kV * 1e3)


@dataclass
class Grid:
    ac_systems: dict[str, AcSystem]
    stations: dict[str, ConverterStation]
    dc_lines: list[DcLine]
    base: DcBase | None

    @property
    def empty(self) -> bool:
        return not (self.ac_systems or self.stations or self.dc_lines)


def grid_from_case(data: Mapping[str, Any]) -> Grid:
    """Build the grid model from the ``ac_systems``, ``converter_stations`` and
    ``dc_network`` sections of a validated case."""
    b = data.get("base", {})
    base = DcBase(b["S_MVA"], b["U_dc_kV"]) if "S_MVA" in b and "U_dc_kV" in b else None
    f_default = b.get("f_Hz", 50.0)
    acs: dict[str, AcSystem] = {}
    for a in data.get("ac_systems", []):
        acs[a["id"]] = AcSystem(id=a["id"], U_kV=a["U_kV"], f_Hz=a.get("f_Hz", f_default),
                                scr=a["scr"], angle_deg=a["angle_deg"],
                                P_dc_MW=a.get("P_dc_MW", base.S_MVA if base else 0.0),
                                U_pu=a.get("U_pu", 1.0), phase_deg=a.get("phase_deg", 0.0))
        if acs[a["id"]].P_dc_MW <= 0.0:
            raise CaseError(f"hệ AC '{a['id']}': cần P_dc_MW hoặc base.S_MVA để tính SCR",
                            path="ac_systems")
    sts: dict[str, ConverterStation] = {}
    for s in data.get("converter_stations", []):
        if s["ac_system"] not in acs:
            raise CaseError(f"trạm '{s['id']}': không có hệ AC '{s['ac_system']}'",
                            path="converter_stations")
        if base is None:
            raise CaseError("trạm chuyển đổi cần base.S_MVA và base.U_dc_kV", path="base")
        ctl = dict(s.get("control", {}))
        if "vdcol" in ctl:
            v = ctl["vdcol"]
            ctl["vdcol"] = None if v is None else (v["u_low"], v["u_high"], v["i_low"],
                                                  v.get("i_high", 1.0))
        v = s.get("valve", {})
        sn = v.get("snubber")
        sts[s["id"]] = ConverterStation(
            id=s["id"], type=s["type"], role=s["role"], ac_system=s["ac_system"],
            transformer=ConverterTransformer(**s["transformer"]),
            smoothing_reactor_H=s["smoothing_reactor_H"],
            filters=tuple(AcFilter(f["type"], f["Q_Mvar"], f.get("h"), f.get("q"))
                          for f in s.get("filters", [])),
            control=LccControl(**ctl),
            valve={k: float(x) for k, x in v.items() if k != "snubber"},
            snubber=(sn["R_ohm"], sn["C_F"]) if sn else None,
        )
    lines = []
    for ln in data.get("dc_network", {}).get("lines", []):
        for end in (ln["from"], ln["to"]):
            if end not in sts:
                raise CaseError(f"đường dây '{ln['id']}': không có trạm '{end}'",
                                path="dc_network.lines")
        lines.append(DcLine(ln["id"], ln["from"], ln["to"], ln.get("model", "pi"),
                            ln["R_ohm"], ln["L_H"], ln["C_F"], ln.get("sections", 1)))
    roles = sorted(s.role for s in sts.values())
    if sts and roles != ["inverter", "rectifier"]:
        raise CaseError("phiên bản này hỗ trợ liên kết hai trạm: một chỉnh lưu, một nghịch lưu "
                        "(MTDC ở M6)", path="converter_stations")
    return Grid(acs, sts, lines, base)
