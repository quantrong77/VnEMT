"""HDF5/CSV output, provenance and reproducibility (SPEC 9.2, Q-02, Q-03, IO-07)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

import vnemt
from vnemt.io.hdf5 import read_result


def test_hdf5_roundtrip_with_provenance(cases_dir: Path, tmp_path: Path) -> None:
    case = vnemt.load(cases_dir / "m0_rlc_series.yaml")
    res = case.run()
    p = res.export(tmp_path / "r.h5")
    back = read_result(p)
    assert back.names == res.names
    np.testing.assert_array_equal(back.time, res.time)
    for n in res.names:
        np.testing.assert_array_equal(back[n], res[n])
        assert back.units[n] == res.units[n]
    for key in ("vnemt_version", "numpy_version", "scipy_version", "case_sha256", "solver"):
        assert key in back.meta
    assert back.meta["solver"]["dt_us"] == 1
    assert back.meta["case_sha256"] == case.file.sha256


def test_csv_export(cases_dir: Path, tmp_path: Path) -> None:
    res = vnemt.load(cases_dir / "m0_rlc_series.yaml").run()
    p = res.export(tmp_path / "r.csv")
    table = np.loadtxt(p, delimiter=",", skiprows=1)
    assert table.shape == (len(res.time), 1 + len(res.names))
    np.testing.assert_array_equal(table[:, 1], res[res.names[0]])
    header = p.read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith("t [s],N3.V [V]")


def test_reproducible_bit_for_bit(cases_dir: Path) -> None:
    a = vnemt.load(cases_dir / "m0_rl_ac.yaml").run()
    b = vnemt.load(cases_dir / "m0_rl_ac.yaml").run()
    for n in a.names:
        np.testing.assert_array_equal(a[n], b[n])
