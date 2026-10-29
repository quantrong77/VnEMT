"""Grid model, AC filters, 12-pulse station (F1-L02), LCC control helpers (F3-02)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from vnemt.components.filters import filter_branches
from vnemt.control import Epc6, PllSrf
from vnemt.control.lcc import LccControl, ramp, vdcol_limit
from vnemt.core import EmtSolver, simulate
from vnemt.errors import CaseError
from vnemt.model.grid import grid_from_case
from vnemt.model.netlist import Element, Netlist
from vnemt.systems.builder import _ac_system, _station, build_system

F = 50.0
W = 2 * np.pi * F


def phasor(t: np.ndarray, x: np.ndarray, t0: float) -> complex:
    n = 2 * round(1 / F / (t[1] - t[0]))
    m = t >= t0
    return complex(2 * np.mean(x[m][:n] * np.exp(-1j * (W * t[m][:n] - np.pi / 2))))


@pytest.mark.parametrize(("kind", "h", "tol"), [("capacitor", None, 1e-3),
                                                ("single_tuned", 11.0, 1e-3),
                                                ("high_pass", 24.0, 1e-2)])
def test_filter_fundamental_reactive_power(kind: str, h: float | None, tol: float) -> None:
    u_kv, q = 345.0, 150.0
    upk = u_kv * 1e3 * np.sqrt(2 / 3)
    els = [Element(f"V{p}", "V_ac", (p.upper(), "gnd"),
                   {"U_peak_V": upk, "f_Hz": F, "phase_deg": -120.0 * k})
           for k, p in enumerate("abc")]
    els += filter_branches("F", ("A", "B", "C"), kind, q, u_kv, F, h=h)
    res = simulate(EmtSolver(Netlist(els), dt=10e-6), 0.4, ["A.V", "Va.I"])
    v, i = phasor(res.time, res["A.V"], 0.3), phasor(res.time, res["Va.I"], 0.3)
    q_sim = -3 * 0.5 * (v * i.conjugate()).imag / 1e6  # Mvar delivered by the filter
    assert q_sim == pytest.approx(q, rel=tol)


def test_single_tuned_filter_resonates_at_h() -> None:
    els = filter_branches("F", ("A", "B", "C"), "single_tuned", 100.0, 345.0, F, h=11.0, q=40.0)
    p = {e.id.rsplit("_", 1)[1]: e for e in els if "_a_" in e.id}
    lc = p["L"].p("L_H") * p["C"].p("C_F")
    assert 1 / (2 * np.pi * np.sqrt(lc)) == pytest.approx(11 * F)
    assert p["R"].p("R_ohm") == pytest.approx(11 * W * p["L"].p("L_H") / 40.0)


def test_vdcol_and_ramp() -> None:
    pts = (0.4, 0.9, 0.55, 1.0)
    assert vdcol_limit(0.2, pts) == 0.55 and vdcol_limit(1.0, pts) == 1.0
    assert vdcol_limit(0.65, pts) == pytest.approx(0.775)
    assert vdcol_limit(0.1, None) == math.inf
    c = LccControl(Id_start_pu=0.1, Id_ref_pu=1.0, ramp_start_s=0.05, ramp_s=0.3)
    assert ramp(0.0, c) == 0.1 and ramp(0.2, c) == pytest.approx(0.55) and ramp(1.0, c) == 1.0


def _data(**over: object) -> dict:
    d: dict = {
        "base": {"S_MVA": 1000, "U_dc_kV": 500, "f_Hz": 50},
        "ac_systems": [{"id": "ACR", "U_kV": 345, "scr": 1000, "angle_deg": 85}],
        "converter_stations": [
            {"id": "REC", "type": "lcc_12pulse", "role": "rectifier", "ac_system": "ACR",
             "transformer": {"S_MVA": 603.73, "U1_kV": 345, "U2_kV": 213.4, "xk_pu": 0.18},
             "smoothing_reactor_H": 0.5},
            {"id": "INV", "type": "lcc_12pulse", "role": "inverter", "ac_system": "ACR",
             "transformer": {"S_MVA": 603.73, "U1_kV": 345, "U2_kV": 213.4, "xk_pu": 0.18},
             "smoothing_reactor_H": 0.5}],
        "dc_network": {"lines": [{"id": "DCL", "from": "REC", "to": "INV", "model": "pi",
                                  "R_ohm": 5.0, "L_H": 1.0, "C_F": 26e-6, "sections": 2}]},
    }
    d.update(over)
    return d


def test_grid_model_and_thevenin_impedance() -> None:
    g = grid_from_case(_data())
    r, lv = g.ac_systems["ACR"].impedance()
    z = 345e3**2 / (1000 * 1000e6)
    assert np.hypot(r, W * lv) == pytest.approx(z) and np.degrees(np.arctan2(W * lv, r)) == \
        pytest.approx(85.0)
    assert g.base is not None and g.base.I_A == pytest.approx(2000.0)
    els, ctrl = build_system(g)
    ids = {e.id for e in els}
    assert {"REC_Y1", "REC_D6", "INV_Y1", "REC_Ls", "DCL_L2"} <= ids
    assert [c.id for c in ctrl] == ["REC_PLL", "INV_PLL", "REC_CTRL", "INV_CTRL",
                                    "REC_EPCY", "REC_EPCD", "INV_EPCY", "INV_EPCD"]


def test_grid_model_errors_are_reported() -> None:
    d = _data()
    d["converter_stations"][1]["role"] = "rectifier"
    with pytest.raises(CaseError, match="cực .positive.: cần đúng một chỉnh lưu và một nghịch lưu"):
        grid_from_case(d)
    d = _data()
    d["converter_stations"][0]["ac_system"] = "X"
    with pytest.raises(CaseError, match="không có hệ AC 'X'"):
        grid_from_case(d)


@pytest.mark.req("F1-L02")
def test_twelve_pulse_cancels_5th_and_7th_harmonics() -> None:
    """Rectifier station on a stiff bus, ideal DC current 2 kA, alpha = 15 deg: both bridges
    give the same Ud (formula), and the line current has no 5th/7th (< 1 % of I1)."""
    g = grid_from_case(_data())
    els = _ac_system(g, "ACR")
    sel, valves, _ = _station(g, g.stations["REC"])
    els += sel + [Element("ID", "I_dc", ("gnd", "REC_POLE"), {"I_A": 2000.0, "ramp_s": 0.02}),
                  Element("RP", "R", ("REC_POLE", "gnd"), {"R_ohm": 1e6})]
    bus = [f"ACR_{p}.V" for p in "abc"]
    ctr = [PllSrf("PLL", bus[0], bus[1], bus[2], f0_Hz=F), Epc6("EY", "PLL", valves[:6], alpha_deg=15.0),
           Epc6("ED", "PLL", valves[6:], alpha_deg=15.0, offset_deg=30.0)]
    res = simulate(EmtSolver(Netlist(els), dt=20e-6), 0.2,
                   ["REC_DC.V", "REC_MID.V", "REC_TYa.w1.I", "REC_TDa.w1.I"], controllers=ctr)
    m = res.time > 0.16
    ud_y = np.mean((res["REC_DC.V"] - res["REC_MID.V"])[m])
    ud_d = np.mean(res["REC_MID.V"][m])
    xc = 0.18 * 213.4e3**2 / 603.73e6
    ud_formula = 3 * np.sqrt(2) / np.pi * 213.4e3 * np.cos(np.radians(15)) - 3 / np.pi * xc * 2000
    assert abs(ud_y - ud_formula) / ud_formula < 0.01
    assert abs(ud_d - ud_formula) / ud_formula < 0.01
    ia = (res["REC_TYa.w1.I"] + res["REC_TDa.w1.I"])[m][:2000]  # two whole cycles
    sp = np.abs(np.fft.rfft(ia))
    k = 2  # bin of the fundamental for two cycles
    for h in (5, 7):
        assert sp[h * k] / sp[k] < 0.01
    assert sp[11 * k] / sp[k] > 0.02  # characteristic 11th remains


def test_tc02_draft_case_validates_builds_and_runs(cases_dir: Path) -> None:
    """Smoke test only: TC-02 acceptance is not met yet (docs/design/M2.md section 9)."""
    import vnemt

    case = vnemt.load(cases_dir / "tc02_cigre_lcc.yaml")
    assert len(case.netlist().elements) > 150
    case.data["case"]["solver"]["t_end_s"] = 0.02
    res = case.run()
    assert res.time[-1] == pytest.approx(0.02)
