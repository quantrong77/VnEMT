"""Result exchange formats (IO-01...IO-04, IO-06, IO-07) and TC-10."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import vnemt
from vnemt.analysis.compare import compare, recovery_time, to_csv, to_markdown
from vnemt.cli import main
from vnemt.errors import VnEMTError
from vnemt.io import read
from vnemt.io.comtrade import read_comtrade, write_comtrade
from vnemt.io.pscad import read_psout, write_pscad_out
from vnemt.results import Result


def synthetic(n_signals: int = 3, n: int = 2001) -> Result:
    t = np.arange(n) * 50e-6
    sig = {f"S{k}.V": (1000.0 * (k + 1)) * np.sin(2 * np.pi * 50 * t + k) + 37.0 * k
           for k in range(n_signals)}
    sig["T1.on"] = (np.sin(2 * np.pi * 50 * t) > 0).astype(float)
    units = {s: "V" for s in sig} | {"T1.on": "-"}
    return Result(time=t, signals=sig, units=units, meta={"base": {"f_Hz": 50.0}})


@pytest.fixture(scope="module")
def tc01(cases_dir: Path) -> Result:
    return vnemt.load(cases_dir / "tc01_bridge6.yaml").run()


def full_scale_error(a: Result, b: Result) -> float:
    """Max deviation over all signals in % of each signal's full scale (peak-to-peak)."""
    worst = 0.0
    for n in a.signals:
        span = float(np.ptp(a[n])) or 1.0
        worst = max(worst, 100.0 * float(np.max(np.abs(a[n] - b[n]))) / span)
    return worst


# ------------------------------------------------------------------ COMTRADE
@pytest.mark.req("IO-01")
@pytest.mark.req("IO-02")
@pytest.mark.parametrize(("rev", "fmt", "tol_pct"), [
    (1999, "ASCII", 0.05), (1999, "BINARY", 0.05),
    (2013, "ASCII", 0.05), (2013, "BINARY", 0.05),
    (2013, "BINARY32", 1e-6), (2013, "FLOAT32", 1e-4),
])
def test_tc10_comtrade_roundtrip(tc01: Result, tmp_path: Path, rev: int, fmt: str,
                                 tol_pct: float) -> None:
    cfg = tc01.export(tmp_path / f"tc01_{rev}_{fmt}.cfg", rev=rev, fmt=fmt)
    back = read(cfg)
    np.testing.assert_allclose(back.time, tc01.time, atol=0.5e-6)
    assert set(back.signals) == set(tc01.signals)
    assert full_scale_error(tc01, back) < tol_pct
    text = cfg.read_text(encoding="latin-1").splitlines()
    assert text[0].endswith(f",{rev}") and fmt in text


def test_comtrade_status_channels_and_units(tmp_path: Path) -> None:
    r = synthetic()
    cfg = write_comtrade(r, tmp_path / "s", rev=1999, fmt="BINARY")
    head = cfg.read_text(encoding="latin-1").splitlines()
    assert head[1] == "4,3A,1D"
    back = read_comtrade(cfg)
    np.testing.assert_array_equal(back["T1.on"], r["T1.on"])
    assert back.units["S0.V"] == "V"


def test_comtrade_read_1991_ascii_with_two_rates_and_blank_stamps(tmp_path: Path) -> None:
    """Revision 1991 (no year, short channel lines, no timemult), two sampling rates,
    time stamps left blank (time follows the rates)."""
    (tmp_path / "old.cfg").write_text(
        "STATION,DEV\n2,1A,1D\n1,IA,A,,kA,0.01,0.5,0,-1000,1000\n1,TRIP,0\n50\n2\n"
        "1000,4\n500,6\n01/01/1995,00:00:00.000000\n01/01/1995,00:00:00.000000\nASCII\n",
        encoding="latin-1")
    (tmp_path / "old.dat").write_text(
        "1,,100,0\n2,,200,0\n3,,300,1\n4,,400,1\n5,,500,1\n6,,600,0\n", encoding="latin-1")
    r = read_comtrade(tmp_path / "old.cfg")
    np.testing.assert_allclose(r.time, [0, 1e-3, 2e-3, 3e-3, 4e-3, 6e-3])
    np.testing.assert_allclose(r["IA"], 0.01 * np.array([100, 200, 300, 400, 500, 600]) + 0.5)
    np.testing.assert_array_equal(r["TRIP"], [0, 0, 1, 1, 1, 0])
    assert r.units["IA"] == "kA"


def test_comtrade_rejects_bad_combination(tmp_path: Path) -> None:
    with pytest.raises(VnEMTError, match="FLOAT32"):
        write_comtrade(synthetic(), tmp_path / "x", rev=1999, fmt="FLOAT32")


# ------------------------------------------------------------------ PSCAD
@pytest.mark.req("IO-03")
@pytest.mark.req("IO-04")
def test_tc10_pscad_out_roundtrip(tc01: Result, tmp_path: Path) -> None:
    inf = tc01.export(tmp_path / "tc01.inf")
    assert (tmp_path / "tc01_01.out").is_file()
    back = read(inf)
    assert list(back.signals) == list(tc01.signals)
    assert full_scale_error(tc01, back) < 1e-6
    back2 = read(tmp_path / "tc01_01.out")
    assert list(back2.signals) == list(tc01.signals)


def test_pscad_channel_to_file_mapping_and_runs(tmp_path: Path) -> None:
    """23 channels: files _01 (1-10), _02 (11-20), _03 (21-23); column = (n-1) mod 10 + 2."""
    r = synthetic(n_signals=22, n=11)  # 22 analog + T1.on = 23 channels
    inf = write_pscad_out(r, tmp_path / "case", run=3)
    assert inf.name == "case_r03.inf"
    files = sorted(p.name for p in tmp_path.glob("case_r03_*.out"))
    assert files == ["case_r03_01.out", "case_r03_02.out", "case_r03_03.out"]
    third = np.loadtxt(tmp_path / "case_r03_03.out")
    assert third.shape == (11, 4)  # time + channels 21, 22, 23
    names = list(r.signals)
    np.testing.assert_allclose(third[:, 1], r[names[20]], rtol=1e-8)
    lines = inf.read_text(encoding="utf-8").splitlines()
    assert lines[20].startswith('PGB(21) Output Desc="S20.V" Group="VnEMT" Max=')
    assert list(read(inf).signals) == names


def test_psout_reports_missing_package(tmp_path: Path) -> None:
    with pytest.raises(VnEMTError, match="mhi-psout|PSOUT Reader"):
        read_psout(tmp_path / "x.psout")


# ------------------------------------------------------------------ MAT, CSV
@pytest.mark.req("IO-07")
@pytest.mark.parametrize("ext", [".mat", ".csv", ".h5"])
def test_mat_csv_hdf5_roundtrip(tmp_path: Path, ext: str) -> None:
    r = synthetic()
    back = read(r.export(tmp_path / f"s{ext}"))
    assert list(back.signals) == list(r.signals)
    for n in r.signals:
        np.testing.assert_array_equal(back[n], r[n])


# ------------------------------------------------------------------ compare
@pytest.mark.req("IO-06")
def test_compare_metrics_against_known_differences() -> None:
    t = np.linspace(0, 1, 10001)
    x = np.where(t < 0.3, 1.0, np.where(t < 0.4, 0.2, 1.0 - 0.8 * np.exp(-(t - 0.4) / 0.05)))
    ref = Result(time=t, signals={"P": x}, units={"P": "pu"})
    t2 = np.linspace(0, 1, 7001)  # different grid
    shifted = np.interp(t2 - 0.01, t, x, left=1.0)  # 10 ms later recovery
    test = Result(time=t2, signals={"Pm": 1.02 * shifted}, units={"Pm": "pu"})
    (c,) = compare(ref, test, {"P": "Pm"}, threshold=0.5, t_clear=0.4, pre_window=(0.0, 0.3))
    assert c.peak_err_pct == pytest.approx(2.0, rel=1e-3)
    # recovery to 90 %: 0.2 + 0.8 (1 - e^-x) = 0.9 -> x = ln(8)
    assert c.t_rec_ref == pytest.approx(0.05 * np.log(8), abs=2e-4)
    # upward crossing of 0.5: ref 0.2 + 0.8 (1 - e^-x) = 0.5; test is 1.02 x, 10 ms later
    x_ref = -np.log(1 - 0.3 / 0.8)
    x_test = -np.log(1 - (0.5 / 1.02 - 0.2) / 0.8)
    assert c.dt_cross == pytest.approx(0.01 + 0.05 * (x_test - x_ref), abs=2e-4)
    assert "P" in to_markdown([c])


def test_recovery_time_edge_cases() -> None:
    t = np.linspace(0, 1, 101)
    assert recovery_time(t, np.ones(101), 0.5, (0.0, 0.4)) == 0.0
    x = np.where(t < 0.5, 1.0, 0.1)
    assert np.isnan(recovery_time(t, x, 0.5, (0.0, 0.4)))


# ------------------------------------------------------------------ CLI
def test_cli_convert_and_compare(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    r = synthetic()
    h5 = r.export(tmp_path / "a.h5")
    assert main(["convert", str(h5), str(tmp_path / "a.cfg"), "--rev", "2013",
                 "--data-format", "ASCII"]) == 0
    assert main(["convert", str(tmp_path / "a.cfg"), str(tmp_path / "b.inf")]) == 0
    assert main(["compare", str(h5), str(tmp_path / "b.inf"), "--csv",
                 str(tmp_path / "cmp.csv")]) == 0
    out = capsys.readouterr().out
    assert "| S0.V | S0.V |" in out and (tmp_path / "cmp.csv").is_file()
    to_csv([], tmp_path / "empty.csv")
