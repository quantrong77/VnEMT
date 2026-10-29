"""Event schedule (F4-01...F4-06), source modulation, misfire, snapshots with event elements,
FRT metrics and sweep helpers (S-10)."""

from __future__ import annotations

import copy
import math
from pathlib import Path

import numpy as np
import pytest

import vnemt
from vnemt.analysis.frt import _episodes, lcc_frt_metrics
from vnemt.core import EmtSolver, simulate
from vnemt.errors import CaseError
from vnemt.io.case_loader import CaseFile, load_case, load_yaml
from vnemt.model.grid import grid_from_case
from vnemt.model.netlist import Element, Netlist
from vnemt.results import Result
from vnemt.studies.sweep import load_sweep, set_path
from vnemt.systems.events import expand_events

from .test_builder import _data


def run_data(d: dict) -> Result:
    return vnemt.Case(CaseFile(data=d, path=None, sha256="")).run()


# ------------------------------------------------------------------ expansion
@pytest.mark.req("F4-01")
def test_ac_fault_expansion_kinds() -> None:
    g = grid_from_case(_data())
    for kind, n_sw in (("3ph", 3), ("1ph", 1), ("2phg", 2), ("2ph", 2)):
        ev = expand_events([{"type": "ac_fault", "location": "ACR", "kind": kind,
                             "r_ohm": 0.5, "x_ohm": 3.0, "t_s": 0.1, "duration_ms": 50}], g)
        sws = [e for e in ev.elements if e.kind == "SW"]
        assert len(sws) == n_sw and all(e.origin == "event" for e in ev.elements)
        assert all(e.times("t_close_s") == (0.1,) and e.times("t_open_s")[0] == pytest.approx(0.15)
                   for e in sws)
        assert any(e.kind == "L" for e in ev.elements)
    with pytest.raises(CaseError, match="không có hệ AC 'X'"):
        expand_events([{"type": "ac_fault", "location": "X", "t_s": 0.1, "duration_ms": 1}], g)


@pytest.mark.req("F4-03")
def test_dc_fault_picks_nearest_line_node() -> None:
    g = grid_from_case(_data())  # pi line with 2 sections: nodes 0 / 0.5 / 1
    for pos, node in ((0.0, "REC_POLE"), (0.4, "DCL_N1"), (0.9, "INV_POLE")):
        ev = expand_events([{"type": "dc_fault", "line": "DCL", "position": pos, "t_s": 0.1,
                             "duration_ms": 10}], g)
        assert ev.elements[0].nodes[0] == node


@pytest.mark.req("F4-02")
@pytest.mark.req("F4-06")
def test_dip_setpoint_and_misfire_expansion() -> None:
    g = grid_from_case(_data())
    ev = expand_events([
        {"type": "ac_dip", "location": "ACR", "depth_pct": 30, "t_s": 0.2, "duration_ms": 100},
        {"type": "setpoint", "station": "REC", "param": "Id_ref_pu", "value": 0.8,
         "t_s": 0.5, "ramp_s": 0.1},
        {"type": "misfire", "valve": "INV_Y1", "t_s": 0.3},
    ], g, valves={"INV_Y1": ("a", "b")})
    assert ev.modulations["ACR_Va"] == [(0.2, pytest.approx(0.3), pytest.approx(0.7))]
    assert ev.setpoints == {"REC": [(0.5, "Id_ref_pu", 0.8, 0.1)]}
    assert ev.misfires == {"INV_Y1": 0.3} and ev.first_time == 0.2


# ------------------------------------------------------------------ solver level
@pytest.mark.req("F4-02")
def test_source_modulation_dips_amplitude() -> None:
    net = Netlist([Element("VS", "V_ac", ("A", "gnd"), {"U_peak_V": 100.0, "f_Hz": 50.0}),
                   Element("R1", "R", ("A", "gnd"), {"R_ohm": 1.0})])
    s = EmtSolver(net, dt=1e-4, modulations={"VS": [(0.02, 0.04, 0.6)]})
    r = simulate(s, 0.06, ["A.V"])
    for t0, t1, amp in ((0.0, 0.02, 100.0), (0.02, 0.04, 60.0), (0.04, 0.06, 100.0)):
        m = (r.time >= t0) & (r.time < t1 - 1e-9)
        assert np.max(np.abs(r["A.V"][m])) == pytest.approx(amp, rel=1e-3)


@pytest.mark.req("F4-04")
def test_misfire_drops_one_pulse(cases_dir: Path) -> None:
    d = copy.deepcopy(load_case(cases_dir / "tc01_bridge6.yaml").data)
    d["case"]["solver"]["t_end_s"] = 0.16
    d["outputs"] = {"signals": ["P.V"], "format": ["hdf5"]}
    normal = run_data(d)
    d["events"] = [{"type": "misfire", "valve": "T1", "t_s": 0.1}]
    mis = run_data(d)
    on = [t for t, i, s in normal.events if i == "T1" and s and 0.1 <= t < 0.12]
    on_mf = [t for t, i, s in mis.events if i == "T1" and s and 0.1 <= t < 0.12]
    assert len(on) == 1 and len(on_mf) == 0
    assert [m[1] for m in mis.markers if m[2] == "misfire"] == ["T1"]


@pytest.mark.req("F4-01")
@pytest.mark.req("S-09")
def test_fault_from_snapshot_matches_continuous_run(cases_dir: Path, tmp_path: Path) -> None:
    """Event elements are not in the snapshot: they are added in their initial state. The only
    difference to a run that carries the (open) fault branch from t = 0 is the 1e9 ohm leakage."""
    base = copy.deepcopy(load_case(cases_dir / "tc01_bridge6.yaml").data)
    base["outputs"] = {"signals": ["P.V", "La.I", "EV1_Sa.I"], "format": ["hdf5"]}
    fault = [{"type": "ac_fault", "location": ["A", "B", "C"], "kind": "1ph", "r_ohm": 2.0,
              "t_s": 0.12, "duration_ms": 20}]
    full = copy.deepcopy(base)
    full["case"]["solver"]["t_end_s"] = 0.16
    full["events"] = fault
    ref = run_data(full)
    snap = copy.deepcopy(base)
    snap["case"]["solver"]["t_end_s"] = 0.1
    snap["outputs"] = {"signals": ["P.V"], "format": ["hdf5"]}
    snap["case"]["snapshot"] = {"t_s": 0.1, "file": str(tmp_path / "s.h5")}
    run_data(snap)
    cont = copy.deepcopy(base)
    cont["case"]["solver"]["t_end_s"] = 0.16
    cont["case"]["init"] = {"mode": "snapshot", "file": str(tmp_path / "s.h5")}
    cont["events"] = fault
    res = run_data(cont)
    k0 = int(np.argmin(np.abs(ref.time - 0.1)))
    assert np.max(np.abs(res["EV1_Sa.I"])) > 1000.0  # the fault did happen
    for n in ("P.V", "La.I"):
        assert np.max(np.abs(res[n] - ref[n][k0:])) / np.max(np.abs(ref[n])) < 1e-4
    cont["events"][0]["t_s"] = 0.05
    with pytest.raises(CaseError, match="phải sau thời điểm snapshot"):
        run_data(cont)


# ------------------------------------------------------------------ metrics, sweep
def test_frt_metrics_on_synthetic_record() -> None:
    t = np.arange(0, 1.0, 1e-4)
    p_drop = (t >= 0.3) & (t < 0.5)
    ud = np.where(p_drop, 0.2, 1.0) * 5e5
    idc = np.full_like(t, 2000.0)
    cf = np.where(t > 0.31, 2.0, 0.0) + np.where(t > 0.6, 1.0, 0.0)
    vn = 230e3 * math.sqrt(2 / 3)
    sig = {"REC_DC.V": ud, "REC_Ls.I": idc, "INV_CTRL.cf_count": cf}
    for k, ph in enumerate("abc"):
        sig[f"ACI_{ph}.V"] = vn * np.sin(2 * np.pi * 50 * t - k * 2 * np.pi / 3)
    res = Result(time=t, signals=sig, units={}, markers=[(0.305, "INV_Y1", "cf")])
    m = lcc_frt_metrics(res, 0.3, 0.4, 2000.0, 5e5, 230.0,
                        criteria={"recovery_90pct_ms": 150, "max_cf": 1})
    assert m["cf_tq"] == 1 and m["cf_gamma"] == 3 and m["cf_episodes"] == 2
    # one-cycle average centred on its window: a 0.2 -> 1.0 step at 0.5 s reaches 90 % after
    # 0.875 of the window, i.e. 0.375 cycle (7.5 ms) after the step itself
    assert m["recovery_ms"] == pytest.approx(107.5, abs=0.2)
    assert m["Uac_min_pu"] == pytest.approx(1.0, rel=1e-3)
    assert m["pass"] is False and m["failed"] == "max_cf"
    assert _episodes([0.1, 0.12, 0.3], 0.04) == 2


def test_sweep_helpers(tmp_path: Path) -> None:
    d = {"events": [{"depth_pct": 10}], "a": {"b": 1}}
    set_path(d, "events.0.depth_pct", 30)
    set_path(d, "a.b", 2)
    assert d == {"events": [{"depth_pct": 30}], "a": {"b": 2}}
    with pytest.raises(CaseError, match="không tồn tại"):
        set_path(d, "events.3.x", 1)
    p = tmp_path / "s.yaml"
    p.write_text("sweep: {snapshot_t_s: 1, t_end_s: 2, parameters: {a: []}}", encoding="utf-8")
    with pytest.raises(CaseError, match="danh sách khác rỗng"):
        load_sweep(p)
    assert load_yaml("x: 1e-3") == {"x": 1e-3}


# ------------------------------------------------------------------ bipole structure
@pytest.mark.req("F2-03")
@pytest.mark.req("F4-03")
def test_bipole_orientation_and_pole_pole_fault(cases_dir: Path) -> None:
    from vnemt.systems.builder import build_system

    data = load_case(cases_dir / "m4a_bipole.yaml").data
    g = grid_from_case(data)
    els = {e.id: e for e in build_system(g)[0]}
    # cathode terminal P towards the pole for rectifier + and inverter -, else the neutral
    assert els["RECP_Y1"].nodes == ("RECP_Ya", "RECP_MID")  # anode a, cathode MID (upper)
    assert els["RECP_D1"].nodes[1] == "RECP_DC"
    assert els["RECN_D1"].nodes[1] == "RECN_MID" and els["RECN_Y1"].nodes[1] == "ACR_NEU"
    assert els["RECP_Ls"].nodes == ("RECP_DC", "RECP_POLE")
    assert els["RECN_Ls"].nodes == ("RECN_POLE", "RECN_DC")
    assert els["ACR_RE"].nodes == ("ACR_NEU", "gnd")
    assert els["DCL"].nodes == ("RECP_POLE", "RECN_POLE", "INVP_POLE", "INVN_POLE")
    ev = expand_events([{"type": "dc_fault", "line": "DCL", "position": 1.0, "kind": "pole_pole",
                         "r_ohm": 1.0, "t_s": 0.1, "duration_ms": 10}], g)
    assert ev.elements[0].nodes == ("INVP_POLE", "EV1_F")
    assert ev.elements[1].nodes == ("EV1_F", "INVN_POLE")
