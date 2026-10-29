"""PSCAD/EMTDC result files ``.out`` + ``.inf`` (SPEC IO-03, IO-04) and ``.psout`` (IO-05).

Layout (PSCAD help, "EMTDC Output Files"; SPEC reference 16):

* ``<name>.inf``: one line per channel
  ``PGB(n) Output Desc="<desc>" Group="<group>" Max=<max> Min=<min> Units="<units>"``;
* ``<name>_01.out``, ``<name>_02.out`` ...: whitespace-separated columns, column 1 is the time,
  at most 10 channels per file. Channel ``n`` (1-based) is in file ``ceil(n/10)``, column
  ``(n - 1) mod 10 + 2``. Multiple runs use ``<name>_r<run:02>_<file:02>.out``.

Values are written as ``%.9E`` (relative rounding 5e-10). Opening the files in Enerplot must be
checked manually on a machine with Enerplot (TC-10); the automated tests check the structure and
the write/read round trip.

``.psout`` (PSCAD V5 binary) is read through the optional MHI package ``mhi.psout``.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np

from vnemt.errors import VnEMTError
from vnemt.results import Result

_CH_PER_FILE = 10
_INF_RE = re.compile(
    r'PGB\((\d+)\)\s+Output\s+Desc="([^"]*)"\s+Group="([^"]*)"\s+Max=\s*(\S+)\s+Min=\s*(\S+)'
    r'\s+Units="([^"]*)"')


def _out_name(base: Path, k: int, run: int | None) -> Path:
    tag = f"_r{run:02d}" if run is not None else ""
    return base.with_name(f"{base.name}{tag}_{k:02d}.out")


def write_pscad_out(result: Result, path: str | Path, group: str = "VnEMT",
                    run: int | None = None) -> Path:
    """Write ``<path>.inf`` and the ``.out`` files; returns the ``.inf`` path."""
    base = Path(path).with_suffix("")
    base.parent.mkdir(parents=True, exist_ok=True)
    names = list(result.signals)
    inf_lines = []
    for n, s in enumerate(names, start=1):
        x = np.asarray(result.signals[s], dtype=float)
        desc = s.replace('"', "'")
        inf_lines.append(
            f'PGB({n}) Output Desc="{desc}" Group="{group}" Max={np.max(x):.6E} '
            f'Min={np.min(x):.6E} Units="{result.units.get(s, "")}"')
    inf = base.with_suffix(".inf") if run is None else base.with_name(f"{base.name}_r{run:02d}.inf")
    inf.write_text("\n".join(inf_lines) + "\n", encoding="utf-8")
    t = np.asarray(result.time, dtype=float)
    for k in range(math.ceil(len(names) / _CH_PER_FILE)):
        chunk = names[k * _CH_PER_FILE:(k + 1) * _CH_PER_FILE]
        table = np.column_stack([t] + [np.asarray(result.signals[s], float) for s in chunk])
        np.savetxt(_out_name(base, k + 1, run), table, fmt="%16.9E", delimiter=" ")
    return inf


def read_pscad_out(path: str | Path) -> Result:
    """Read a ``.inf`` file and its ``.out`` files (single run or ``_r##`` run)."""
    inf = Path(path).with_suffix(".inf")
    if not inf.is_file():
        raise VnEMTError(f"không tìm thấy file '{inf}'")
    chans: dict[int, tuple[str, str]] = {}
    for line in inf.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _INF_RE.search(line)
        if m:
            chans[int(m.group(1))] = (m.group(2), m.group(6))
    if not chans:
        raise VnEMTError(f"'{inf}' không có dòng PGB(n) Output hợp lệ")
    stem = inf.with_suffix("")
    m_run = re.fullmatch(r"(.*)_r(\d+)", stem.name)
    base, run = (stem.with_name(m_run.group(1)), int(m_run.group(2))) if m_run else (stem, None)
    signals: dict[str, np.ndarray] = {}
    units: dict[str, str] = {}
    time: np.ndarray | None = None
    for k in range(1, math.ceil(max(chans) / _CH_PER_FILE) + 1):
        f = _out_name(base, k, run)
        if not f.is_file():
            raise VnEMTError(f"thiếu file kết quả PSCAD '{f}'")
        table = np.atleast_2d(np.loadtxt(f))
        if time is None:
            time = table[:, 0]
        for col in range(1, table.shape[1]):
            n = (k - 1) * _CH_PER_FILE + col
            if n in chans:
                desc, unit = chans[n]
                signals[desc] = table[:, col]
                units[desc] = unit
    assert time is not None
    order = [chans[n][0] for n in sorted(chans)]
    return Result(time=time, signals={s: signals[s] for s in order if s in signals},
                  units=units, meta={"source_format": "PSCAD .out/.inf"})


def read_psout(path: str | Path, run: int = 0) -> Result:
    """Read a PSCAD V5 ``.psout`` file (SPEC IO-05, priority M).

    Not implemented yet: the reader needs the MHI package ``mhi.psout`` and a sample file of
    the PSCAD version in use to be developed and tested against. Until then the user is told
    how to convert the file with MHI's PSOUT Reader.
    """
    try:
        import mhi.psout  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        raise VnEMTError(
            "đọc .psout cần gói 'mhi-psout' (cài bằng: uv pip install -e \".[pscad]\" trên "
            "Windows). Nếu không cài được, dùng PSOUT Reader của MHI để chuyển sang .out/.inf "
            "rồi đọc bằng vnemt"
        ) from None
    raise VnEMTError(
        f"đọc .psout ('{path}') chưa được triển khai: cần phát triển và kiểm thử với gói "
        "mhi-psout và file mẫu của đúng phiên bản PSCAD. Tạm thời hãy dùng PSOUT Reader của "
        "MHI để chuyển sang .out/.inf"
    )
