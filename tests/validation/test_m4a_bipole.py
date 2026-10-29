"""M4a acceptance: LCC bipole with electrodes (F2-03, F5-01), pole coupling on the Bergeron line
(F2-06), monopole with metallic return (F2-01)."""

from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest

import vnemt
from vnemt.io.case_loader import CaseFile, load_case
from vnemt.results import Result

I_BASE = 2000.0


def run(d: dict) -> Result:
    return vnemt.Case(CaseFile(data=d, path=None, sha256="")).run()


@pytest.fixture(scope="module")
def bipole(cases_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> tuple[dict, Path]:
    """Bipole data and a steady-state snapshot at 0.6 s."""
    d = copy.deepcopy(load_case(cases_dir / "m4a_bipole.yaml").data)
    snap = tmp_path_factory.mktemp("bipole") / "snap.h5"
    base = copy.deepcopy(d)
    base["case"]["solver"]["t_end_s"] = 0.6
    base["case"]["snapshot"] = {"t_s": 0.6, "file": str(snap)}
    run(base)
    d["case"]["init"] = {"mode": "snapshot", "file": str(snap)}
    return d, snap


def last(res: Result, name: str, span: float = 0.04) -> float:
    return float(np.mean(res[name][res.time > res.time[-1] - span]))


@pytest.mark.slow
@pytest.mark.req("F2-03")
@pytest.mark.req("F5-01")
def test_balanced_bipole_has_no_ground_current(bipole: tuple[dict, Path]) -> None:
    d = copy.deepcopy(bipole[0])
    d["case"]["solver"]["t_end_s"] = 0.8
    r = run(d)
    for p in ("RECP", "RECN"):
        assert last(r, f"{p}_CTRL.Id") == pytest.approx(1.0, abs=0.01)
    assert last(r, "RECP_DC.V") == pytest.approx(-last(r, "RECN_DC.V"), rel=1e-3)
    for end in ("ACR", "ACI"):
        assert abs(last(r, f"{end}_RE.I")) < 0.01 * I_BASE


@pytest.mark.slow
@pytest.mark.req("F2-03")
def test_unbalanced_bipole_ground_current_is_pole_difference(bipole: tuple[dict, Path]) -> None:
    d = copy.deepcopy(bipole[0])
    d["case"]["solver"]["t_end_s"] = 1.1
    d["events"] = [{"type": "setpoint", "station": "RECN", "param": "Id_ref_pu", "value": 0.8,
                    "t_s": 0.65, "ramp_s": 0.1}]
    r = run(d)
    ip, in_ = last(r, "RECP_Ls.I"), last(r, "RECN_Ls.I")
    assert in_ / I_BASE == pytest.approx(0.8, abs=0.01)
    assert ip / I_BASE == pytest.approx(1.0, abs=0.01)
    assert abs(last(r, "ACR_RE.I")) == pytest.approx(ip - in_, rel=0.02)


@pytest.mark.slow
@pytest.mark.req("F2-06")
@pytest.mark.req("F4-03")
def test_pole_to_ground_fault_induces_voltage_on_healthy_pole(bipole: tuple[dict, Path]) -> None:
    """Positive pole grounded at the rectifier end of the line: the travelling wave couples
    into the negative pole, whose voltage magnitude rises above its pre-fault value."""
    d = copy.deepcopy(bipole[0])
    d["case"]["solver"]["t_end_s"] = 0.66
    d["outputs"] = {"signals": ["INVN_POLE.V", "INVP_POLE.V", "RECN_POLE.V"],
                    "format": ["hdf5"]}
    d["events"] = [{"type": "dc_fault", "line": "DCL", "position": 0.0, "conductor": 0,
                    "r_ohm": 1.0, "t_s": 0.62, "duration_ms": 20}]
    r = run(d)
    pre = r.time < 0.62
    after = (r.time > 0.62) & (r.time < 0.64)
    v_pre = float(np.mean(np.abs(r["INVN_POLE.V"][pre])))
    assert float(np.min(np.abs(r["INVP_POLE.V"][after]))) < 0.2 * v_pre  # faulted pole collapses
    assert float(np.max(np.abs(r["INVN_POLE.V"][after]))) > 1.15 * v_pre  # induced overvoltage


@pytest.mark.slow
@pytest.mark.req("F2-01")
def test_monopole_metallic_return(cases_dir: Path) -> None:
    """Positive pole only; the second conductor is the metallic return between the neutral
    buses, grounded at the inverter end only: no current flows through the ground."""
    d = copy.deepcopy(load_case(cases_dir / "m4a_bipole.yaml").data)
    d["converter_stations"] = [s for s in d["converter_stations"] if s["pole"] == "positive"]
    for a in d["ac_systems"]:
        a["P_dc_MW"] = 1000
    d["dc_network"]["electrodes"] = {"ACI": 0.5}
    d["dc_network"]["lines"][0]["from"] = ["RECP", "neutral:ACR"]
    d["dc_network"]["lines"][0]["to"] = ["INVP", "neutral:ACI"]
    d["case"]["solver"]["t_end_s"] = 0.8
    d["outputs"] = {"signals": ["RECP_CTRL.Id", "ACI_RE.I", "DCL.k2.I", "INVP_CTRL.gamma_min"],
                    "format": ["hdf5"]}
    r = run(d)
    assert last(r, "RECP_CTRL.Id") == pytest.approx(1.0, abs=0.01)
    assert abs(last(r, "ACI_RE.I")) < 0.01 * I_BASE
    assert abs(last(r, "DCL.k2.I")) == pytest.approx(I_BASE, rel=0.01)  # current returns in the wire
