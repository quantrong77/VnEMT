"""TC-03 and TC-09 (SPEC 10.2): inverter AC dips on the TC-02 system, multiple run.

TC-03 - commutation failures are counted (two criteria: valve t_q and gamma < gamma_cf) and
CFPREV reduces their number over the 10-30 % depth range; the link recovers to 90 % power
within 300 ms after the dip (VnEMT design target).
TC-09 - 50 fault cases (5 depths x 10 points on wave) from one snapshot give a complete metrics
table; the table does not depend on the number of worker processes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vnemt.studies.sweep import load_sweep, run_sweep

ROOT = Path(__file__).resolve().parents[2]
METRICS = ("cf_tq", "cf_gamma", "cf_episodes", "recovery_ms", "Id_max_pu", "Ud_max_pu",
           "Uac_min_pu", "Uac_max_pu")


@pytest.mark.slow
@pytest.mark.req("F4-08")
@pytest.mark.req("F1-L05")
def test_tc03_cf_counted_and_reduced_by_cfprev(tmp_path: Path) -> None:
    rows = run_sweep(ROOT / "cases/tc03_inv_dip.yaml", load_sweep(ROOT / "sweeps/tc03_dip.yaml"),
                     tmp_path)
    off = [r for r in rows if not r["converter_stations.1.control.cfprev"]]
    on = [r for r in rows if r["converter_stations.1.control.cfprev"]]
    assert len(off) == len(on) == 3
    assert all(r["cf_episodes"] >= 1 for r in off)  # 10-30 % dips fail without CFPREV

    def total(rs: list[dict]) -> int:
        return sum(r["cf_tq"] + r["cf_gamma"] for r in rs)

    assert total(on) < total(off)
    # VnEMT design target (inside the 100-300 ms range quoted in SPEC 7.4): 90 % power
    # recovery within 300 ms after clearing with the designed controls (CFPREV, inverter fast
    # release); without CFPREV the 10 % dip takes about 320 ms
    assert all(r["recovery_ms"] <= 300.0 for r in on), [r["recovery_ms"] for r in on]
    assert (tmp_path / "sweep.csv").is_file() and (tmp_path / "sweep.md").is_file()


@pytest.mark.slow
@pytest.mark.req("S-10")
def test_tc09_fifty_faults_from_snapshot(tmp_path: Path) -> None:
    sweep = load_sweep(ROOT / "sweeps/tc09_dip_pow.yaml")
    rows = run_sweep(ROOT / "cases/tc03_inv_dip.yaml", sweep, tmp_path / "par")
    assert len(rows) == 50
    for r in rows:
        assert set(METRICS) <= set(r)
        assert r["Id_max_pu"] > 0 and r["Uac_min_pu"] > 0
    # reproducible and independent of the number of processes (Q-02): rerun two cases serially
    sweep2 = {**sweep, "parameters": {"events.0.depth_pct": [10, 30], "events.0.t_s": [1.106]}}
    ser = run_sweep(ROOT / "cases/tc03_inv_dip.yaml", sweep2, tmp_path / "ser", workers=1)
    ref = {(r["events.0.depth_pct"], r["events.0.t_s"]): r for r in rows}
    for r in ser:
        p = ref[(r["events.0.depth_pct"], r["events.0.t_s"])]
        for m in METRICS:
            assert r[m] == p[m] or (r[m] != r[m] and p[m] != p[m])  # equal or both nan
