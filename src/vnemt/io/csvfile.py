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
