"""Save and restore the complete simulation state (SPEC S-08c, S-09).

A snapshot stores every field of :class:`SolverState` bit-exactly (network, switching devices,
control states), plus the solver fingerprint (netlist, ``dt``, CDA flag). Restoring into a
solver with a different fingerprint is refused, so a continued run reproduces an
uninterrupted run exactly.
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np

from vnemt import __version__
from vnemt.core.solver import EmtSolver, SolverState
from vnemt.core.switching import DeviceState
from vnemt.errors import VnEMTError

_NET = ("v", "i_b", "v_b")


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
        for name in _NET:
            f.create_dataset(name, data=getattr(st, name))
        g = f.create_group("dev")
        for name in DeviceState.FIELDS:
            g.create_dataset(name, data=getattr(st.dev, name))
        c = f.create_group("ctrl")
        for name, arr in st.ctrl.items():
            c.create_dataset(name, data=arr)
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
        net = {name: np.asarray(f[name][()], dtype=float) for name in _NET}
        dev = DeviceState(**{name: np.asarray(f["dev"][name][()]) for name in DeviceState.FIELDS})
        ctrl = {name: np.asarray(f["ctrl"][name][()], dtype=float) for name in f["ctrl"]}
        # event elements (appended after the base circuit) start in their initial state
        n_v, n_b = len(solver.node_names), len(solver.branches)
        net["v"] = np.concatenate([net["v"], np.zeros(n_v - len(net["v"]))])
        net["i_b"] = np.concatenate([net["i_b"], np.zeros(n_b - len(net["i_b"]))])
        net["v_b"] = np.concatenate([net["v_b"], np.zeros(n_b - len(net["v_b"]))])
        init = solver.switches.initial_state()
        k = len(dev.on)
        dev = DeviceState(**{name: np.concatenate([getattr(dev, name), getattr(init, name)[k:]])
                             for name in DeviceState.FIELDS})
        return SolverState(
            t=float(f.attrs["t"]),
            step=int(f.attrs["step"]),
            cda_left=int(f.attrs["cda_left"]),
            dev=dev,
            ctrl=ctrl,
            **net,
        )
