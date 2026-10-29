"""Waveform comparison between VnEMT and another program (SPEC IO-06, verification level V4).

The test waveform is linearly interpolated onto the time grid of the reference inside the
common (or requested) time window. Per signal pair:

* ``max_abs``: ``max |x_test - x_ref|``
* ``peak_ref``, ``peak_test``, ``peak_err_pct``: peak absolute values and their relative
  difference (% of ``peak_ref``)
* ``rms_err``: RMS of the difference; ``nrmse_pct``: ``rms_err`` in % of the reference
  peak-to-peak range
* ``t_cross_ref``, ``t_cross_test``, ``dt_cross``: first instants the signal crosses
  ``threshold`` upwards (if a threshold is given)
* ``t_rec_ref``, ``t_rec_test``, ``dt_rec``: recovery time after ``t_clear``: first instant
  from which the signal stays at or above ``recovery_frac`` (default 90 %) of its mean value
  in ``pre_window`` before the disturbance (if ``t_clear`` is given)

SPEC 10.1 V4 accepts peak and recovery-time deviations within +/- 5 %.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from vnemt.errors import VnEMTError
from vnemt.results import Result

FloatArray = NDArray[np.float64]


@dataclass
class Comparison:
    ref: str
    test: str
    max_abs: float
    peak_ref: float
    peak_test: float
    peak_err_pct: float
    rms_err: float
    nrmse_pct: float
    t_cross_ref: float = float("nan")
    t_cross_test: float = float("nan")
    dt_cross: float = float("nan")
    t_rec_ref: float = float("nan")
    t_rec_test: float = float("nan")
    dt_rec: float = float("nan")


def first_crossing(t: FloatArray, x: FloatArray, level: float) -> float:
    """First upward crossing of ``level`` (linear interpolation); nan if none."""
    i = np.flatnonzero((x[:-1] < level) & (x[1:] >= level))
    if not len(i):
        return float("nan")
    k = i[0]
    return float(t[k] + (level - x[k]) * (t[k + 1] - t[k]) / (x[k + 1] - x[k]))


def recovery_time(t: FloatArray, x: FloatArray, t_clear: float, pre: tuple[float, float],
                  frac: float = 0.9) -> float:
    """Time after ``t_clear`` from which ``x`` stays >= ``frac`` x pre-disturbance mean."""
    m = (t >= pre[0]) & (t < pre[1])
    if not np.any(m):
        raise VnEMTError("cửa sổ trước sự cố không có mẫu nào")
    level = frac * float(np.mean(x[m]))
    after = t >= t_clear
    tt, xx = t[after], x[after]
    below = np.flatnonzero(xx < level)
    if not len(below):
        return 0.0
    k = below[-1]
    if k == len(xx) - 1:
        return float("nan")  # not recovered within the record
    return float(tt[k + 1] - t_clear)


def compare(ref: Result, test: Result, pairs: Mapping[str, str] | Sequence[str] | None = None,
            t_range: tuple[float, float] | None = None, threshold: float | None = None,
            t_clear: float | None = None, pre_window: tuple[float, float] | None = None,
            recovery_frac: float = 0.9) -> list[Comparison]:
    """Compare signal pairs ``{ref_name: test_name}`` (default: common names)."""
    if pairs is None:
        names = [n for n in ref.signals if n in test.signals]
        if not names:
            raise VnEMTError("hai kết quả không có tên tín hiệu chung; hãy khai báo cặp tín hiệu")
        pairs = {n: n for n in names}
    elif not isinstance(pairs, Mapping):
        pairs = {n: n for n in pairs}
    t0 = max(ref.time[0], test.time[0])
    t1 = min(ref.time[-1], test.time[-1])
    if t_range is not None:
        t0, t1 = max(t0, t_range[0]), min(t1, t_range[1])
    if t1 <= t0:
        raise VnEMTError("hai kết quả không có khoảng thời gian chung")
    m = (ref.time >= t0) & (ref.time <= t1)
    t = ref.time[m]
    out: list[Comparison] = []
    for rn, tn in pairs.items():
        xr = ref[rn][m]
        xt = np.interp(t, test.time, test[tn])
        d = xt - xr
        pr, pt = float(np.max(np.abs(xr))), float(np.max(np.abs(xt)))
        span = float(np.ptp(xr)) or 1.0
        c = Comparison(rn, tn, float(np.max(np.abs(d))), pr, pt,
                       100.0 * (pt - pr) / pr if pr else float("nan"),
                       float(np.sqrt(np.mean(d**2))), 100.0 * float(np.sqrt(np.mean(d**2))) / span)
        if threshold is not None:
            c.t_cross_ref = first_crossing(t, xr, threshold)
            c.t_cross_test = first_crossing(t, xt, threshold)
            c.dt_cross = c.t_cross_test - c.t_cross_ref
        if t_clear is not None:
            pre = pre_window or (t0, t_clear)
            c.t_rec_ref = recovery_time(t, xr, t_clear, pre, recovery_frac)
            c.t_rec_test = recovery_time(t, xt, t_clear, pre, recovery_frac)
            c.dt_rec = c.t_rec_test - c.t_rec_ref
        out.append(c)
    return out


def to_markdown(rows: Sequence[Comparison]) -> str:
    cols = ["ref", "test", "max_abs", "peak_err_pct", "nrmse_pct", "dt_cross", "dt_rec"]
    lines = ["| " + " | ".join(cols) + " |", "|" + " --- |" * len(cols)]
    for r in rows:
        d = asdict(r)
        lines.append("| " + " | ".join(
            str(d[c]) if isinstance(d[c], str) else f"{d[c]:.6g}" for c in cols) + " |")
    return "\n".join(lines)


def to_csv(rows: Sequence[Comparison], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    cols = list(asdict(rows[0])) if rows else []
    text = [",".join(cols)] + [",".join(str(v) for v in asdict(r).values()) for r in rows]
    p.write_text("\n".join(text) + "\n", encoding="utf-8")
    return p
