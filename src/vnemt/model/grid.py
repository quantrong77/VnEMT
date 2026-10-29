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
    ki_deg: float = 2400.0  # deg per (pu s): Ti = 25 ms (PI zero below crossover)
    T_id_s: float = 0.0012
    T_ud_up_s: float = 0.04
    T_ud_down_s: float = 0.01
    vdcol: tuple[float, float, float, float] | None = (0.4, 0.9, 0.55, 1.0)  # u_lo, u_hi, i_lo, i_hi
    fast_k: float = 1.0  # integral gain factor for large current errors (fast release)
    fast_e_pu: float = 0.05  # rectifier |error| above which fast_k applies
    gamma_ref_deg: float = 15.0
    margin_pu: float = 0.1
    kp_gamma: float = 0.7506  # deg per deg (CIGRE benchmark, to be checked)
    ki_gamma: float = 30.0  # 1/s: Ti = 25 ms (VnEMT; the benchmark uses about 54 ms)
    gamma_cf_deg: float = 7.2  # CF criterion: 360 f t_q with t_q = 400 us (illustrative)
    # force retard / restart after a DC line fault (F4-07)
    force_retard: bool = False  # enable for DC line fault studies (see docs/design/M3.md)
    fr_u_det: float = 0.25
    fr_t_det: float = 0.005
    fr_vac_min: float = 0.7
    fr_arm_ud: float = 0.8
    fr_alpha_deg: float = 140.0
    fr_t_deion: float = 0.15
    fr_n_restart: int = 3
    # commutation failure prevention (F4-08), VnEMT design values
    cfprev: bool = False
    cfprev_k_ab: float = 120.0  # deg per pu of alpha-beta voltage drop
    cfprev_k_0: float = 200.0  # deg per pu of zero-sequence voltage
    cfprev_u_th: float = 0.05
    cfprev_max_deg: float = 30.0
    cfprev_t_dec: float = 0.1


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
    pole: str = "positive"
    end: str = ""  # station end (shares the DC neutral bus); default: the AC system id

    @property
    def end_id(self) -> str:
        return self.end or self.ac_system

    @property
    def p_at_pole(self) -> bool:
        """Bridge cathode terminal (P) towards the pole line (rectifier +, inverter -)."""
        return (self.role == "rectifier") == (self.pole == "positive")


@dataclass(frozen=True)
class DcLine:
    """DC line. ``t``/``pi``: one conductor between two stations (lumped sections).
    ``bergeron``: N conductors between ``from_ends`` and ``to_ends`` (station ids or
    ``neutral:<end>``), per-km matrices (row-major) and length."""

    id: str
    from_station: str
    to_station: str
    model: str  # t | pi | bergeron
    R_ohm: float = 0.0
    L_H: float = 0.0
    C_F: float = 0.0
    sections: int = 1
    from_ends: tuple[str, ...] = ()
    to_ends: tuple[str, ...] = ()
    length_km: float = 0.0
    L_H_per_km: tuple[float, ...] = ()
    C_F_per_km: tuple[float, ...] = ()
    R_ohm_per_km: tuple[float, ...] = ()


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
    electrodes: dict[str, float] | None = None  # end -> electrode resistance; None: neutral = gnd

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
            pole=s.get("pole", "positive"),
            end=s.get("end", ""),
        )
    dcn = data.get("dc_network", {})
    ends = {s.end_id for s in sts.values()}
    elec = dcn.get("electrodes")
    if elec is not None:
        unknown = [e for e in elec if e not in ends]
        if unknown:
            raise CaseError(f"điện cực ở đầu không tồn tại: {', '.join(unknown)} "
                            f"(các đầu: {', '.join(sorted(ends))})", path="dc_network.electrodes")
        if not elec:
            raise CaseError("cần ít nhất một điện cực nối đất", path="dc_network.electrodes")

    def endpoint_ok(x: str) -> bool:
        if x.startswith("neutral:"):
            return elec is not None and x[len("neutral:"):] in ends
        return x in sts

    lines = []
    for ln in dcn.get("lines", []):
        fr = ln["from"] if isinstance(ln["from"], list) else [ln["from"]]
        to = ln["to"] if isinstance(ln["to"], list) else [ln["to"]]
        bad = [x for x in fr + to if not endpoint_ok(x)]
        if bad:
            raise CaseError(f"đường dây '{ln['id']}': đầu nối không hợp lệ {bad} (mã trạm, hoặc "
                            "'neutral:<đầu>' khi có mục electrodes)", path="dc_network.lines")
        model = ln.get("model", "pi")
        if model == "bergeron":
            if len(fr) != len(to):
                raise CaseError(f"đường dây '{ln['id']}': số dây hai đầu khác nhau",
                                path="dc_network.lines")

            def tup(v: Any) -> tuple[float, ...]:
                return tuple(float(x) for x in (v if isinstance(v, list) else [v]))

            lines.append(DcLine(ln["id"], fr[0], to[0], model, from_ends=tuple(fr),
                                to_ends=tuple(to), length_km=float(ln["length_km"]),
                                L_H_per_km=tup(ln["L_H_per_km"]),
                                C_F_per_km=tup(ln["C_F_per_km"]),
                                R_ohm_per_km=tup(ln.get("R_ohm_per_km", 0.0))))
        else:
            if len(fr) != 1 or len(to) != 1 or not all(x in sts for x in fr + to):
                raise CaseError(f"đường dây '{ln['id']}': mô hình '{model}' nối hai trạm, một dây",
                                path="dc_network.lines")
            lines.append(DcLine(ln["id"], fr[0], to[0], model, ln["R_ohm"], ln["L_H"],
                                ln["C_F"], ln.get("sections", 1)))
    for pole in sorted({s.pole for s in sts.values()}):
        roles = sorted(s.role for s in sts.values() if s.pole == pole)
        if roles != ["inverter", "rectifier"]:
            raise CaseError(f"cực '{pole}': cần đúng một chỉnh lưu và một nghịch lưu (MTDC ở M6)",
                            path="converter_stations")
    return Grid(acs, sts, lines, base, None if elec is None else dict(elec))
