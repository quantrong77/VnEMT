"""CSV waveform export (SPEC IO-07): first column time, header ``name [unit]``."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from vnemt.results import Result


def write_csv(result: Result, path: str | Path) -> Path:
    """Write all signals of ``result`` as columns, full float64 precision."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    header = ["t [s]"] + [f"{n} [{result.units.get(n, '')}]" for n in result.signals]
    table = np.column_stack([result.time, *result.signals.values()])
    np.savetxt(p, table, delimiter=",", header=",".join(header), comments="", fmt="%.17g",
               encoding="utf-8")
    return p


def read_csv(path: str | Path) -> Result:
    """Read a CSV written by :func:`write_csv` (header ``name [unit]``)."""
    p = Path(path)
    header = p.read_text(encoding="utf-8").splitlines()[0].split(",")
    table = np.atleast_2d(np.loadtxt(p, delimiter=",", skiprows=1))
    names, units = [], {}
    for h in header[1:]:
        name, _, unit = h.strip().partition(" [")
        names.append(name)
        units[name] = unit.rstrip("]")
    return Result(time=table[:, 0], signals={n: table[:, k + 1] for k, n in enumerate(names)},
                  units=units, meta={"source_format": "CSV"})
