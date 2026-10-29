"""Save and restore the complete solver state (SPEC S-08c, S-09).

A snapshot stores every field of :class:`SolverState` bit-exactly, plus the solver
fingerprint (netlist, ``dt``, CDA flag). Restoring into a solver with a different fingerprint
is refused, so a continued run reproduces an uninterrupted run exactly.
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np

from vnemt import __version__
from vnemt.core.solver import EmtSolver, SolverState
from vnemt.errors import VnEMTError

_ARRAYS = ("v", "i_b", "v_b", "sw_on", "armed", "sched_idx")


def save_snapshot(solver: EmtSolver, st: SolverState, path: str | Path) -> Path:
    """Write ``st`` to an HDF5 snapshot file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(p, "w") as f:
        f.attrs["kind"] = "vnemt_snapshot"
        f.attrs["vnemt_version"] = __version__
        f.attrs["fingerprint"] = solver.fingerprint()
        f.attrs["t"] = st.t
        f.attrs["step"] = st.step
        f.attrs["cda_left"] = st.cda_left
        for name in _ARRAYS:
            f.create_dataset(name, data=getattr(st, name))
    return p


def load_snapshot(solver: EmtSolver, path: str | Path) -> SolverState:
    """Read a snapshot written by :func:`save_snapshot` for the same circuit and ``dt``."""
    p = Path(path)
    if not p.is_file():
        raise VnEMTError(f"không tìm thấy file snapshot '{p}'")
    with h5py.File(p, "r") as f:
        if f.attrs.get("kind") != "vnemt_snapshot":
            raise VnEMTError(f"'{p}' không phải file snapshot của VnEMT")
        if f.attrs["fingerprint"] != solver.fingerprint():
            raise VnEMTError(
                f"snapshot '{p}' được tạo cho mạch hoặc bước thời gian khác; "
                "hãy chạy lại để tạo snapshot mới"
            )
        arrays = {name: np.asarray(f[name][()]) for name in _ARRAYS}
        return SolverState(
            t=float(f.attrs["t"]),
            step=int(f.attrs["step"]),
            cda_left=int(f.attrs["cda_left"]),
            v=arrays["v"].astype(float),
            i_b=arrays["i_b"].astype(float),
            v_b=arrays["v_b"].astype(float),
            sw_on=arrays["sw_on"].astype(bool),
            armed=arrays["armed"].astype(bool),
            sched_idx=arrays["sched_idx"].astype(np.int64),
        )
