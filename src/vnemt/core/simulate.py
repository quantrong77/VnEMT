"""Time loop: run an :class:`EmtSolver` and record the requested signals."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from vnemt.core.solver import EmtSolver
from vnemt.errors import CaseError
from vnemt.results import Result


def simulate(
    solver: EmtSolver,
    t_end: float,
    signals: Sequence[str] | None = None,
    decimate: int = 1,
) -> Result:
    """Run from the zero initial state to ``t_end`` and return recorded signals.

    Parameters
    ----------
    solver : EmtSolver
        Prepared solver.
    t_end : float
        End time in seconds.
    signals : sequence of str, optional
        Signal names to record; ``None`` records everything.
    decimate : int
        Record every ``decimate``-th step (t = 0 always recorded).
    """
    layout = solver.signal_layout()
    pos = {name: i for i, (name, _) in enumerate(layout)}
    names = [n for n, _ in layout] if signals is None else list(signals)
    unknown = [n for n in names if n not in pos]
    if unknown:
        raise CaseError(
            "tín hiệu không tồn tại: "
            + ", ".join(unknown)
            + ". Tên hợp lệ có dạng <nút>.V, <phần tử>.I, <phần tử>.V",
            path="outputs.signals",
        )
    sel = np.array([pos[n] for n in names], dtype=np.int64)

    n_steps = math.floor(t_end / solver.dt + 1e-9)
    n_rec = n_steps // decimate + 1
    t = np.empty(n_rec)
    data = np.empty((n_rec, len(names)))
    st = solver.initial_state()
    t[0], data[0] = st.t, solver.probe(st)[sel]
    r = 1
    for k in range(1, n_steps + 1):
        st = solver.step(st)
        if k % decimate == 0:
            t[r], data[r] = st.t, solver.probe(st)[sel]
            r += 1
    units = dict(layout)
    return Result(
        time=t[:r],
        signals={name: data[:r, j].copy() for j, name in enumerate(names)},
        units={n: units[n] for n in names},
    )
