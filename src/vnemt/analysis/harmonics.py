"""Harmonic evaluation (SPEC F5-06).

The spectrum is taken over the last whole number of fundamental cycles of the record
(rectangular window, so integer harmonics fall exactly on FFT bins)::

    D_n = V_n / V_1 * 100 %          THD = sqrt(sum_{n=2..N} D_n^2)

Telephone interference: ``TIF = sqrt(sum (W_f V_f)^2) / V_rms`` and ``IT = sqrt(sum (W_f I_f)^2)``
(rms values) need the weighting factors ``W_f`` (combined C-message / TIF weighting). VnEMT has
no built-in table: the weights must be supplied by the user (frequency -> weight, from the
applicable standard, e.g. IEEE 519 or the project specification, IEC TR 62001-1 section 5).

Reference: IEC TR 62001-1:2016, section 5 (performance criteria); IEC 61000-4-7 (spectral
analysis on synchronised windows).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from vnemt.errors import VnEMTError
from vnemt.results import Result

FloatArray = NDArray[np.float64]


@dataclass
class Spectrum:
    orders: NDArray[np.int64]
    amplitude: FloatArray  # peak value of each harmonic order (index = order)
    cycles: int

    @property
    def fundamental(self) -> float:
        return float(self.amplitude[1])

    def dn_pct(self) -> FloatArray:
        out: FloatArray = 100.0 * self.amplitude / self.fundamental
        return out

    def thd_pct(self, n_max: int | None = None) -> float:
        d = self.dn_pct()[2:(n_max or len(self.amplitude) - 1) + 1]
        return float(np.sqrt(np.sum(d * d)))


def spectrum(t: FloatArray, x: FloatArray, f: float, n_max: int = 50) -> Spectrum:
    """Harmonic amplitudes (peak) of orders ``0..n_max`` over the last whole cycles."""
    dt = float(t[1] - t[0])
    per = 1.0 / (f * dt)
    cycles = math.floor((t[-1] - t[0]) * f + 1e-9)
    if cycles < 1 or abs(per - round(per)) > 1e-6:
        raise VnEMTError("phân tích sóng hài cần ít nhất một chu kỳ và số mẫu nguyên mỗi chu kỳ "
                         f"(hiện {per:.4g} mẫu/chu kỳ)")
    n = cycles * round(per)
    seg = np.asarray(x[-n:], dtype=float)
    c = np.fft.rfft(seg) / n
    orders = np.arange(n_max + 1)
    amp = np.abs(c[orders * cycles]) * 2.0
    amp[0] /= 2.0
    return Spectrum(orders, amp, cycles)


def harmonic_table(res: Result, signal: str, f: float, n_max: int = 50,
                   t_window: tuple[float, float] | None = None) -> dict[str, float]:
    """``{"V1": ..., "THD_pct": ..., "D5_pct": ...}`` of one signal."""
    t, x = res.time, res[signal]
    if t_window is not None:
        m = (t >= t_window[0]) & (t <= t_window[1])
        t, x = t[m], x[m]
    s = spectrum(t, x, f, n_max)
    row = {"V1": s.fundamental, "THD_pct": s.thd_pct()}
    d = s.dn_pct()
    for n in range(2, n_max + 1):
        row[f"D{n}_pct"] = float(d[n])
    return row


def compare_filters(with_f: Result, without_f: Result, signals: Sequence[str], f: float,
                    orders: Sequence[int] = (5, 7, 11, 13, 23, 25, 35, 37, 47, 49),
                    n_max: int = 50) -> list[dict[str, float | str]]:
    """Table of Dn and THD with and without filters for each signal (F5-06)."""
    rows: list[dict[str, float | str]] = []
    for s in signals:
        for label, res in (("có lọc", with_f), ("không lọc", without_f)):
            h = harmonic_table(res, s, f, n_max)
            row: dict[str, float | str] = {"signal": s, "case": label, "THD_pct": h["THD_pct"]}
            row.update({f"D{n}_pct": h[f"D{n}_pct"] for n in orders})
            rows.append(row)
    return rows


def tif(t: FloatArray, x: FloatArray, f: float, weights: Mapping[float, float] | None,
        n_max: int = 50, current: bool = False) -> float:
    """TIF of a voltage (dimensionless) or IT of a current (A) with user weights."""
    if not weights:
        raise VnEMTError("chưa có bảng trọng số TIF (tần số -> hệ số); VnEMT không có bảng mặc "
                         "định, hãy lấy từ tiêu chuẩn áp dụng hoặc đặc tính kỹ thuật của dự án")
    s = spectrum(t, x, f, n_max)
    fw = np.array(sorted(weights), dtype=float)
    w = np.interp(s.orders * f, fw, [weights[k] for k in sorted(weights)], left=0.0, right=0.0)
    rms = s.amplitude / math.sqrt(2.0)
    num = float(np.sqrt(np.sum((w[1:] * rms[1:]) ** 2)))
    if current:
        return num
    return num / float(np.sqrt(np.sum(rms[1:] ** 2)))
