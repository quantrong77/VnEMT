"""MATLAB ``.mat`` export/import (SPEC IO-07).

Each signal becomes a column vector named by a valid MATLAB identifier (``.`` and other
characters replaced by ``_``, prefixed with ``s_`` if needed, de-duplicated); ``t`` holds the
time, ``vnemt_names`` the original names, ``vnemt_units`` the units. Format version 5
(``scipy.io.savemat``), readable by MATLAB and Octave.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import scipy.io

from vnemt.results import Result


def _ident(name: str, used: set[str]) -> str:
    s = re.sub(r"\W", "_", name)
    if not re.match(r"[A-Za-z]", s):
        s = "s_" + s
    s = s[:60]
    base, k = s, 1
    while s in used or s in ("t", "vnemt_names", "vnemt_units"):
        k += 1
        s = f"{base}_{k}"
    used.add(s)
    return s


def write_mat(result: Result, path: str | Path) -> Path:
    p = Path(path).with_suffix(".mat")
    p.parent.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    data: dict[str, object] = {"t": np.asarray(result.time)[:, None]}
    names = list(result.signals)
    for n in names:
        data[_ident(n, used)] = np.asarray(result.signals[n])[:, None]
    data["vnemt_names"] = np.array(names, dtype=object)
    data["vnemt_units"] = np.array([result.units.get(n, "") for n in names], dtype=object)
    scipy.io.savemat(p, data, do_compression=True)
    return p


def read_mat(path: str | Path) -> Result:
    m = scipy.io.loadmat(Path(path), squeeze_me=True)
    names = [str(x) for x in np.atleast_1d(m["vnemt_names"])]
    units = [str(x) for x in np.atleast_1d(m["vnemt_units"])]
    used: set[str] = set()
    signals = {n: np.asarray(m[_ident(n, used)], dtype=float) for n in names}
    return Result(time=np.asarray(m["t"], dtype=float), signals=signals,
                  units=dict(zip(names, units, strict=True)), meta={"source_format": "MAT"})
