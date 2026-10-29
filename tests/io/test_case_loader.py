"""Case schema validation and Vietnamese error messages (SPEC 9.1, Q-05)."""

from __future__ import annotations

from pathlib import Path

import pytest

import vnemt
from vnemt.errors import CaseError
from vnemt.io.case_loader import load_case, parse_case

MINIMAL = """
case:
  name: t
  solver: {dt_us: 10, t_end_s: 0.001}
circuit:
  elements:
    - {id: VS, type: V_dc, nodes: [A, gnd], U_V: 1}
    - {id: R1, type: R, nodes: [A, gnd], R_ohm: 1}
"""


def test_all_shipped_cases_are_valid(cases_dir: Path) -> None:
    files = sorted(cases_dir.glob("*.yaml"))
    assert files
    for f in files:
        load_case(f)


def test_minimal_case_parses_and_hashes() -> None:
    a, b = parse_case(MINIMAL), parse_case(MINIMAL)
    assert a.name == "t"
    assert a.sha256 == b.sha256 and len(a.sha256) == 64


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("R_ohm: 1}", "R_ohm: -1}", "circuit.elements[1].R_ohm: giá trị phải > 0"),
        ("R_ohm: 1}", "Rx: 1}", "thiếu khóa bắt buộc 'R_ohm'"),
        ("R_ohm: 1}", "R_ohm: 1, foo: 2}", "khóa không được hỗ trợ 'foo'"),
        ("dt_us: 10", "dt_us: 500", "case.solver.dt_us: giá trị phải ≤ 100"),
        ("type: R,", "type: Q,", "không hợp lệ"),
        ("nodes: [A, gnd], R_ohm", "nodes: [A], R_ohm", "cần ít nhất 2 phần tử"),
    ],
)
def test_schema_errors_are_vietnamese_with_key_path(old: str, new: str, expected: str) -> None:
    assert old in MINIMAL
    with pytest.raises(CaseError) as exc:
        parse_case(MINIMAL.replace(old, new))
    assert expected in str(exc.value)


def test_duplicate_ids_and_shorted_element() -> None:
    text = MINIMAL.replace("id: R1, type: R, nodes: [A, gnd]", "id: VS, type: R, nodes: [A, A]")
    with pytest.raises(CaseError) as exc:
        parse_case(text)
    msg = str(exc.value)
    assert "trùng mã 'VS'" in msg and "hai đầu trùng nút 'A'" in msg


def test_yaml_syntax_error_reports_line() -> None:
    with pytest.raises(CaseError, match="dòng"):
        parse_case("case: {name: t\n  solver: [")


def test_missing_file() -> None:
    with pytest.raises(CaseError, match="không tìm thấy"):
        load_case("khong_co.yaml")


def test_pending_sections_are_refused_at_run_time() -> None:
    case = vnemt.loads(MINIMAL + "events:\n  - {t_s: 0.1, type: ac_fault}\n")
    with pytest.raises(CaseError, match="M3"):
        case.run()


def test_unknown_output_signal() -> None:
    case = vnemt.loads(MINIMAL + "outputs: {signals: [B.V]}\n")
    with pytest.raises(CaseError, match="B.V"):
        case.run()


def test_switch_and_diode_elements() -> None:
    ok = MINIMAL + (
        "    - {id: S1, type: SW, nodes: [A, B], t_close_s: [0.1, 0.3], t_open_s: 0.2,"
        " open_at_zero: true}\n"
        "    - {id: D1, type: D, nodes: [B, gnd], V_f_V: 0.7, R_on_ohm: 0.001}\n"
    )
    case = vnemt.loads(ok)
    sw = case.netlist().element("S1")
    assert sw.times("t_close_s") == (0.1, 0.3) and sw.times("t_open_s") == (0.2,)
    with pytest.raises(CaseError, match="khóa không được hỗ trợ 'V_f_V'"):
        parse_case(ok.replace("t_open_s: 0.2,", "t_open_s: 0.2, V_f_V: 1,"))


def test_snapshot_init_requires_file() -> None:
    text = MINIMAL.replace("  solver:", "  init: {mode: snapshot}\n  solver:")
    with pytest.raises(CaseError, match="case.init: thiếu khóa bắt buộc 'file'"):
        parse_case(text)
