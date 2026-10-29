"""TC-04 (SPEC 10.2): LCC bipole with tap changers, filter switching and harmonic table
(F5-02...F5-06).

* F5-03: rectifier AC voltage +5 %: alpha leaves its 12.5-17.5 deg band, the tap changers step
  up and bring alpha back into the band (delays shortened to 0.1 s / 0.15 s, see the case).
* F5-05: both poles' current order 1.0 -> 0.6 pu: the stations would export several hundred
  Mvar; the reactive power controls of both ends switch filter groups out until Q is back
  inside +/-200 Mvar.
* F5-06: harmonic table at the rectifier AC bus with the AC filters and with the tuned filters
  replaced by capacitors of the same fundamental Mvar (same operating point, no tuned
  filtering).
"""

from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest

import vnemt
from vnemt.analysis.harmonics import compare_filters
from vnemt.io.case_loader import CaseFile, load_case
from vnemt.results import Result

F = 50.0
BAND_Q = 200.0


def run(d: dict) -> Result:
    return vnemt.Case(CaseFile(data=d, path=None, sha256="")).run()


def mean_last(r: Result, name: str, span: float = 0.1) -> float:
    return float(np.mean(r[name][r.time > r.time[-1] - span]))


@pytest.fixture(scope="module")
def tc04(cases_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> tuple[dict, str]:
    d = copy.deepcopy(load_case(cases_dir / "tc04_bipole_oltc.yaml").data)
    snap = str(tmp_path_factory.mktemp("tc04") / "snap.h5")
    base = copy.deepcopy(d)
    base["case"]["solver"]["t_end_s"] = 0.6
    base["case"]["snapshot"] = {"t_s": 0.6, "file": snap}
    run(base)
    d["case"]["init"] = {"mode": "snapshot", "file": snap}
    return d, snap


@pytest.mark.slow
@pytest.mark.req("F5-03")
@pytest.mark.req("F5-02")
def test_tc04_tap_changer_brings_alpha_back_into_band(tc04: tuple[dict, str]) -> None:
    d = copy.deepcopy(tc04[0])
    d["case"]["solver"]["t_end_s"] = 1.9
    d["events"] = [{"type": "ac_dip", "location": "ACR", "depth_pct": -5, "t_s": 0.8,
                    "duration_ms": 5000}]
    r = run(d)
    pre = (r.time > 0.7) & (r.time < 0.8)
    assert 12.5 <= float(np.mean(r["RECP_CTRL.alpha"][pre])) <= 17.5
    assert float(np.max(r["RECP_CTRL.alpha"][(r.time > 0.8) & (r.time < 1.0)])) > 17.5
    assert r["RECP_TAP.step"][-1] >= 2 and r["RECN_TAP.step"][-1] >= 2
    for st in ("RECP", "RECN"):
        a = r[f"{st}_CTRL.alpha"][r.time > 1.8]  # back in band within 1 s
        assert 12.5 <= float(np.min(a)) and float(np.max(a)) <= 17.5


@pytest.mark.slow
@pytest.mark.req("F5-05")
def test_tc04_filter_switching_keeps_station_q_in_band(tc04: tuple[dict, str]) -> None:
    d = copy.deepcopy(tc04[0])
    d["case"]["solver"]["t_end_s"] = 2.0
    d["events"] = [{"type": "setpoint", "station": s, "param": "Id_ref_pu", "value": 0.6,
                    "t_s": 0.8, "ramp_s": 0.05} for s in ("RECP", "RECN")]
    r = run(d)
    for qc in ("RECP_QC", "INVP_QC"):
        assert float(np.min(r[f"{qc}.Q"][(r.time > 0.85) & (r.time < 1.0)])) < -BAND_Q
        assert r[f"{qc}.groups_on"][-1] < r[f"{qc}.groups_on"][0]
        assert abs(mean_last(r, f"{qc}.Q")) <= BAND_Q
    assert mean_last(r, "INVP_CTRL.Ud") < 1.0  # no lasting DC overvoltage
    assert mean_last(r, "RECP_CTRL.Id") == pytest.approx(0.6, abs=0.02)


@pytest.mark.slow
@pytest.mark.req("F5-06")
@pytest.mark.req("F5-04")
def test_tc04_harmonic_table_with_and_without_filters(tc04: tuple[dict, str],
                                                      cases_dir: Path, tmp_path: Path) -> None:
    sig = ["ACR_a.V"]
    d = copy.deepcopy(tc04[0])
    d["case"]["solver"]["t_end_s"] = 0.7
    d["outputs"] = {"signals": sig, "format": ["hdf5"]}
    with_f = run(d)
    nf = copy.deepcopy(load_case(cases_dir / "tc04_bipole_oltc.yaml").data)
    for st in nf["converter_stations"]:
        st["filters"] = [{"type": "capacitor", "Q_Mvar": f["Q_Mvar"],
                          **({"switchable": True, "closed": f.get("closed", True)}
                             if f.get("switchable") else {})} for f in st["filters"]]
    nf["case"]["solver"]["t_end_s"] = 0.7
    nf["outputs"] = {"signals": sig, "format": ["hdf5"]}
    without_f = run(nf)
    rows = compare_filters(_last_cycles(with_f), _last_cycles(without_f), sig, F)
    w, wo = rows[0], rows[1]
    # tuned orders are filtered; above ~20th a plain capacitor also has a low impedance, so
    # D23, D25 are not lower with the high-pass filter (the capacitor's drawback is the risk
    # of low-order resonance, see the frequency scan)
    for n in (11, 13):
        assert w[f"D{n}_pct"] < 0.5 * wo[f"D{n}_pct"]
    assert w["THD_pct"] < wo["THD_pct"]
    assert w["D11_pct"] < 1.0  # tuned 11th filters leave < 1 % of the fundamental
    from vnemt.studies.sweep import to_markdown, write_table

    write_table(rows, tmp_path / "tc04_harmonics.csv")
    assert "có lọc" in to_markdown(rows)


def _last_cycles(r: Result, cycles: int = 4) -> Result:
    m = r.time > r.time[-1] - cycles / F - 1e-9
    return Result(time=r.time[m], signals={k: v[m] for k, v in r.signals.items()},
                  units=r.units)
