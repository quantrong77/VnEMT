"""COMTRADE (IEEE C37.111-1991/1999/2013, IEC 60255-24) export and import (SPEC IO-01, IO-02).

Writing (revisions 1999 and 2013):

* one sampling rate, time stamps in microseconds (``timemult = 1``) relative to the first
  sample; start and trigger time from the result metadata (``created_utc``) or 2000-01-01;
* analog channels: every signal except ``<switch>.on``; data format ``ASCII`` or ``BINARY``
  (int16), and for 2013 also ``BINARY32`` (int32) and ``FLOAT32``. Integer formats use
  ``x = a n + b`` with ``b = (max + min)/2`` and ``a = (max - min)/(2 n_max)``, so the
  quantisation error is at most ``a/2`` (int16: 0.0008 % of full scale);
* status (digital) channels: ``<switch>.on`` signals.

Reading accepts revisions 1991, 1999 and 2013, the four data formats, several sampling rates
and missing time stamps (time then follows the sampling rates). The ``.cfg`` file is read as
Latin-1; channel names are written as ASCII (diacritics removed).

Reference: IEEE Std C37.111-1999 and C37.111-2013 / IEC 60255-24:2013, sections 6-8.
"""

from __future__ import annotations

import datetime as dt
import math
import unicodedata
from pathlib import Path

import numpy as np

from vnemt.errors import VnEMTError
from vnemt.results import Result

FORMATS = {1999: ("ASCII", "BINARY"), 2013: ("ASCII", "BINARY", "BINARY32", "FLOAT32")}
_INT_MAX = {"ASCII": 32767, "BINARY": 32767, "BINARY32": 2147483647}


def _ascii(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).replace("đ", "d").replace("Đ", "D")
    return s.encode("ascii", "ignore").decode("ascii").replace(",", ";")


def _start_time(result: Result) -> dt.datetime:
    created = result.meta.get("created_utc")
    if isinstance(created, str):
        try:
            return dt.datetime.fromisoformat(created).replace(tzinfo=None)
        except ValueError:
            pass
    return dt.datetime(2000, 1, 1)


def _fmt_time(t: dt.datetime) -> str:
    return t.strftime("%d/%m/%Y,%H:%M:%S.%f")


def write_comtrade(result: Result, path: str | Path, rev: int = 1999, fmt: str = "BINARY",
                   station: str = "VnEMT", device: str = "vnemt", lf: float | None = None) -> Path:
    """Write ``<path>.cfg`` and ``<path>.dat``; returns the ``.cfg`` path."""
    fmt = fmt.upper()
    if rev not in FORMATS or fmt not in FORMATS[rev]:
        raise VnEMTError(f"COMTRADE: không hỗ trợ bản {rev} với dạng dữ liệu {fmt}; "
                         f"chọn trong {FORMATS}")
    cfg = Path(path).with_suffix(".cfg")
    cfg.parent.mkdir(parents=True, exist_ok=True)
    t = np.asarray(result.time, dtype=float)
    n = len(t)
    if n < 2:
        raise VnEMTError("COMTRADE: cần ít nhất 2 mẫu")
    step = float(np.median(np.diff(t)))
    names_d = [s for s in result.signals if s.endswith(".on")]
    names_a = [s for s in result.signals if not s.endswith(".on")]
    if lf is None:
        base = result.meta.get("base", {})
        lf = float(base.get("f_Hz", 50.0)) if isinstance(base, dict) else 50.0

    a_coef, b_coef, data_a = [], [], []
    for s in names_a:
        x = np.asarray(result.signals[s], dtype=float)
        if fmt == "FLOAT32":
            a, b = 1.0, 0.0
            q = x.astype(np.float32)
        else:
            nmax = _INT_MAX[fmt]
            lo, hi = float(np.min(x)), float(np.max(x))
            b = 0.5 * (hi + lo)
            a = (hi - lo) / (2 * nmax) if hi > lo else 1.0
            q = np.clip(np.round((x - b) / a), -nmax, nmax).astype(np.int64)
        a_coef.append(a)
        b_coef.append(b)
        data_a.append(q)

    start = _start_time(result)
    lines = [f"{_ascii(station)},{_ascii(device)},{rev}",
             f"{len(names_a) + len(names_d)},{len(names_a)}A,{len(names_d)}D"]
    for k, s in enumerate(names_a, start=1):
        unit = _ascii(result.units.get(s, ""))
        if fmt == "FLOAT32":
            x = data_a[k - 1]
            vmin, vmax = f"{float(np.min(x)):.7g}", f"{float(np.max(x)):.7g}"
        else:
            vmin, vmax = str(-_INT_MAX[fmt]), str(_INT_MAX[fmt])
        lines.append(f"{k},{_ascii(s)},,,{unit},{a_coef[k - 1]:.12g},{b_coef[k - 1]:.12g},0,"
                     f"{vmin},{vmax},1,1,P")
    for k, s in enumerate(names_d, start=1):
        lines.append(f"{k},{_ascii(s)},,,0")
    lines += [f"{lf:g}", "1", f"{1.0 / step:.10g},{n}", _fmt_time(start), _fmt_time(start),
              fmt, "1"]
    if rev == 2013:
        lines += ["+0h00,+0h00", "0,0"]
    cfg.write_text("\r\n".join(lines) + "\r\n", encoding="latin-1", newline="")

    ts = np.round((t - t[0]) * 1e6).astype(np.int64)
    digital = [np.asarray(result.signals[s]) > 0.5 for s in names_d]
    dat = cfg.with_suffix(".dat")
    if fmt == "ASCII":
        cols = [np.arange(1, n + 1), ts, *data_a, *[d.astype(np.int64) for d in digital]]
        table = np.column_stack(cols) if cols else np.zeros((n, 0))
        np.savetxt(dat, table, fmt="%d", delimiter=",", newline="\r\n")
    else:
        atype = {"BINARY": "<i2", "BINARY32": "<i4", "FLOAT32": "<f4"}[fmt]
        nw = math.ceil(len(names_d) / 16)
        dtype = np.dtype([("n", "<u4"), ("t", "<u4")]
                         + [(f"a{k}", atype) for k in range(len(names_a))]
                         + [(f"d{k}", "<u2") for k in range(nw)])
        rec = np.zeros(n, dtype=dtype)
        rec["n"] = np.arange(1, n + 1)
        rec["t"] = ts
        for k, q in enumerate(data_a):
            rec[f"a{k}"] = q
        for w in range(nw):
            word = np.zeros(n, dtype=np.uint16)
            for bit, d in enumerate(digital[16 * w:16 * (w + 1)]):
                word |= (d.astype(np.uint16) << bit)
            rec[f"d{w}"] = word
        rec.tofile(dat)
    return cfg


def read_comtrade(path: str | Path) -> Result:
    """Read a COMTRADE record (``.cfg`` + ``.dat``)."""
    cfg = Path(path).with_suffix(".cfg")
    if not cfg.is_file():
        raise VnEMTError(f"không tìm thấy file COMTRADE '{cfg}'")
    lines = [ln.strip() for ln in cfg.read_text(encoding="latin-1").splitlines()]
    it = iter(lines)
    head = next(it).split(",")
    rev = int(head[2]) if len(head) >= 3 and head[2].strip().isdigit() else 1991
    counts = next(it).split(",")
    n_a = int(counts[1].strip().rstrip("Aa"))
    n_d = int(counts[2].strip().rstrip("Dd"))
    names, units, a_c, b_c = [], [], [], []
    for _ in range(n_a):
        f = next(it).split(",")
        names.append(f[1].strip())
        units.append(f[4].strip())
        a_c.append(float(f[5]))
        b_c.append(float(f[6]))
    d_names = []
    for _ in range(n_d):
        f = next(it).split(",")
        d_names.append(f[1].strip())
    lf = float(next(it))
    nrates = int(next(it))
    rates = []
    for _ in range(max(nrates, 1)):
        f = next(it).split(",")
        rates.append((float(f[0]), int(f[1])))
    next(it)  # start time
    next(it)  # trigger time
    fmt = next(it).upper()
    timemult = 1.0
    if rev >= 1999:
        tm = next(it, "1").strip()
        timemult = float(tm) if tm else 1.0
    n_total = rates[-1][1]
    dat = cfg.with_suffix(".dat")
    if not dat.is_file():
        dat = cfg.with_suffix(".DAT")
    if fmt == "ASCII":
        raw = np.genfromtxt(dat, delimiter=",", dtype=float)
        raw = np.atleast_2d(raw)[:n_total]
        stamps = raw[:, 1]
        vals_a = [raw[:, 2 + k] for k in range(n_a)]
        vals_d = [raw[:, 2 + n_a + k] for k in range(n_d)]
    elif fmt in ("BINARY", "BINARY32", "FLOAT32"):
        atype = {"BINARY": "<i2", "BINARY32": "<i4", "FLOAT32": "<f4"}[fmt]
        nw = math.ceil(n_d / 16)
        dtype = np.dtype([("n", "<u4"), ("t", "<u4")] + [(f"a{k}", atype) for k in range(n_a)]
                         + [(f"d{k}", "<u2") for k in range(nw)])
        rec = np.fromfile(dat, dtype=dtype, count=n_total)
        stamps = rec["t"].astype(float)
        vals_a = [rec[f"a{k}"].astype(float) for k in range(n_a)]
        vals_d = [((rec[f"d{k // 16}"] >> (k % 16)) & 1).astype(float) for k in range(n_d)]
    else:
        raise VnEMTError(f"COMTRADE: dạng dữ liệu '{fmt}' không hợp lệ trong '{cfg}'")
    if nrates > 0 and rates[0][0] > 0:
        t = np.empty(len(stamps))
        t0, k0 = 0.0, 0
        for samp, end in rates:
            k = np.arange(k0, min(end, len(stamps)))
            t[k] = t0 + (k - k0) / samp
            if len(k):
                t0 = t[k[-1]] + 1.0 / samp
            k0 = end
    else:
        t = stamps * timemult * 1e-6
    signals = {nm: a_c[k] * vals_a[k] + b_c[k] for k, nm in enumerate(names)}
    signals.update({nm: vals_d[k] for k, nm in enumerate(d_names)})
    unit_map = dict(zip(names, units, strict=True)) | {nm: "-" for nm in d_names}
    meta = {"source_format": f"COMTRADE {rev} {fmt}", "line_frequency_Hz": lf}
    return Result(time=t, signals=signals, units=unit_map, meta=meta)
