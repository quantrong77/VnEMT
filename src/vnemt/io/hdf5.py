"""HDF5 result storage (SPEC-v0.1 section 9.2, Q-03).

Layout::

    /time                 float64 [s]
    /signals/<name>       float64, attribute ``unit``
    attributes on /       vnemt_version, python/numpy/scipy versions, case_sha256,
                          solver (JSON), created_utc, ... (``Result.meta``)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from vnemt.results import Result


def _attr(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def write_result(result: Result, path: str | Path) -> Path:
    """Write ``result`` to an HDF5 file (overwrites)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(p, "w") as f:
        f.create_dataset("time", data=result.time)
        f["time"].attrs["unit"] = "s"
        g = f.create_group("signals")
        for name, data in result.signals.items():
            ds = g.create_dataset(name, data=data)
            ds.attrs["unit"] = result.units.get(name, "")
        f.attrs["signal_order"] = json.dumps(list(result.signals))
        for key, value in result.meta.items():
            f.attrs[key] = _attr(value)
    return p


def read_result(path: str | Path) -> Result:
    """Read an HDF5 file written by :func:`write_result`."""
    with h5py.File(Path(path), "r") as f:
        order = json.loads(f.attrs["signal_order"])
        signals = {n: np.asarray(f["signals"][n][()]) for n in order}
        units = {n: str(f["signals"][n].attrs.get("unit", "")) for n in order}
        meta: dict[str, Any] = {}
        for k, v in f.attrs.items():
            if k == "signal_order":
                continue
            if isinstance(v, str) and v[:1] in "{[":
                try:
                    v = json.loads(v)
                except json.JSONDecodeError:
                    pass
            meta[k] = v.item() if isinstance(v, np.generic) else v
        return Result(time=np.asarray(f["time"][()]), signals=signals, units=units, meta=meta)
