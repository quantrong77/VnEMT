"""CLI acceptance for milestone M0: ``vnemt run`` on the RLC case, ``vnemt validate``."""

from __future__ import annotations

from pathlib import Path

import pytest

from vnemt.cli import main


def test_run_rlc_case_writes_outputs(cases_dir: Path, tmp_path: Path,
                                     capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["run", str(cases_dir / "m0_rlc_series.yaml"), "-o", str(tmp_path), "--plot"])
    assert code == 0
    for ext in (".h5", ".csv", ".png"):
        assert (tmp_path / f"m0_rlc_series{ext}").is_file()
    assert "m0_rlc_series" in capsys.readouterr().out


def test_validate_directory(cases_dir: Path) -> None:
    assert main(["validate", str(cases_dir)]) == 0


def test_validate_reports_invalid_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("case: {name: x, solver: {dt_us: 0, t_end_s: 1}}\n", encoding="utf-8")
    assert main(["validate", str(bad)]) == 1
    assert "dt_us" in capsys.readouterr().out


def test_run_error_is_reported_not_raised(tmp_path: Path,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", str(tmp_path / "none.yaml")]) == 1
    assert "không tìm thấy" in capsys.readouterr().err
