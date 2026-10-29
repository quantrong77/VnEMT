"""Time loop: run an :class:`EmtSolver` and record the requested signals."""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from vnemt.core.snapshot import save_snapshot
from vnemt.core.solver import EmtSolver, SolverState
from vnemt.errors import CaseError
from vnemt.results import Result


def simulate(
    solver: EmtSolver,
    t_end: float,
    signals: Sequence[str] | None = None,
    decimate: int = 1,
    start: SolverState | None = None,
    snapshot: tuple[float, str | Path] | None = None,
) -> Result:
    """Run to ``t_end`` and return recorded signals and switching events.

    Parameters
    ----------
    solver : EmtSolver
        Prepared solver.
    t_end : float
        End time in seconds.
    signals : sequence of str, optional
        Signal names to record; ``None`` records everything.
    decimate : int
        Record grid steps whose index is a multiple of ``decimate`` (the start point is
        always recorded), so a run continued from a snapshot samples the same instants.
    start : SolverState, optional
        Initial state (e.g. from a snapshot); default is the zero state.
    snapshot : (t_s, path), optional
        Save a snapshot at the first grid point with ``t >= t_s``.
    """
    layout = solver.signal_layout()
    pos = {name: i for i, (name, _) in enumerate(layout)}
    names = [n for n, _ in layout] if signals is None else list(signals)
    unknown = [n for n in names if n not in pos]
    if unknown:
        raise CaseError(
            "tín hiệu không tồn tại: "
            + ", ".join(unknown)
            + ". Tên hợp lệ có dạng <nút>.V, <phần tử>.I, <phần tử>.V, <khóa>.on",
            path="outputs.signals",
        )
    sel = np.array([pos[n] for n in names], dtype=np.int64)

    st = start if start is not None else solver.initial_state()
    last_step = math.floor(t_end / solver.dt + 1e-9)
    if last_step < st.step:
        raise CaseError(f"t_end = {t_end} s nhỏ hơn thời điểm bắt đầu {st.t} s",
                        path="case.solver.t_end_s")
    n_rec = last_step // decimate - st.step // decimate + 1
    t = np.empty(n_rec)
    data = np.empty((n_rec, len(names)))
    t[0], data[0] = st.t, solver.probe(st)[sel]
    n_ev0 = len(solver.events)
    snap_step = math.ceil(snapshot[0] / solver.dt - 1e-9) if snapshot else -1
    if snapshot and snap_step <= st.step:
        save_snapshot(solver, st, snapshot[1])
    r = 1
    for k in range(st.step + 1, last_step + 1):
        st = solver.step(st)
        if k % decimate == 0:
            t[r], data[r] = st.t, solver.probe(st)[sel]
            r += 1
        if k == snap_step and snapshot:
            save_snapshot(solver, st, snapshot[1])
    units = dict(layout)
    return Result(
        time=t[:r],
        signals={name: data[:r, j].copy() for j, name in enumerate(names)},
        units={n: units[n] for n in names},
        events=[(e.t, e.id, e.on) for e in solver.events[n_ev0:]],
    )
