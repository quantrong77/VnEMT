"""Control system interface (SPEC S-06).

Controllers are solved sequentially after the network at every regular grid step, in the
order given (like PSCAD/EMTDC): a controller sees the network solution of the step just
completed and the outputs of the controllers before it in the same step; outputs of later
controllers are one step old. Commands issued at grid time ``t`` (gate windows) act inside the
next step ``(t, t + dt]``. A controller with ``every = k`` runs every ``k`` grid steps
(multi-rate).

All controller state lives in ``SolverState.ctrl`` (``<id>.x`` state, ``<id>.y`` outputs), so
snapshots include it (SPEC S-09).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from vnemt.core.solver import EmtSolver, FloatArray, SolverState
from vnemt.errors import CaseError


@dataclass
class ControlIO:
    """Commands from controllers to the network for the next step."""

    solver: EmtSolver
    state: SolverState

    def fire(self, valve: int, t_on: float, t_off: float) -> None:
        self.solver.fire(self.state, valve, t_on, t_off)


class Controller(ABC):
    """A control block group with its own state vector and published outputs."""

    every: int = 1

    def __init__(self, id: str) -> None:
        self.id = id

    @abstractmethod
    def inputs(self) -> list[str]:
        """Names of the signals read (network signals or ``<controller>.<output>``)."""

    @abstractmethod
    def outputs(self) -> list[tuple[str, str]]:
        """Local output names and units; published as ``<id>.<name>``."""

    @abstractmethod
    def init_state(self) -> FloatArray:
        """Initial state vector."""

    def bind(self, solver: EmtSolver) -> None:
        """Resolve device indices etc. once the solver exists."""

    @abstractmethod
    def update(self, t: float, dt: float, x: FloatArray, u: FloatArray,
               io: ControlIO) -> FloatArray:
        """Advance the state ``x`` in place to time ``t`` and return the outputs.

        ``dt`` is the controller time step (``every`` grid steps).
        """


class ControlSystem:
    """Ordered list of controllers wired to the network signals."""

    def __init__(self, solver: EmtSolver, controllers: Sequence[Controller]) -> None:
        self.solver = solver
        self.controllers = list(controllers)
        ids = [c.id for c in self.controllers]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise CaseError(f"trùng mã khối điều khiển: {', '.join(sorted(dup))}",
                            path="controls")
        net = solver.signal_layout()
        self.n_net = len(net)
        self.layout = list(net)
        self._out_slice: dict[str, slice] = {}
        for c in self.controllers:
            c.bind(solver)
            start = len(self.layout)
            self.layout += [(f"{c.id}.{n}", u) for n, u in c.outputs()]
            self._out_slice[c.id] = slice(start - self.n_net, len(self.layout) - self.n_net)
        pos = {n: i for i, (n, _) in enumerate(self.layout)}
        self._in_idx: list[np.ndarray] = []
        for c in self.controllers:
            missing = [s for s in c.inputs() if s not in pos]
            if missing:
                raise CaseError(f"khối '{c.id}': tín hiệu vào không tồn tại: "
                                + ", ".join(missing), path="controls")
            self._in_idx.append(np.array([pos[s] for s in c.inputs()], dtype=np.int64))

    @property
    def n_out(self) -> int:
        return len(self.layout) - self.n_net

    def init(self, st: SolverState) -> None:
        for c in self.controllers:
            st.ctrl.setdefault(f"{c.id}.x", np.asarray(c.init_state(), dtype=float).copy())
            sl = self._out_slice[c.id]
            st.ctrl.setdefault(f"{c.id}.y", np.zeros(sl.stop - sl.start))

    def outputs(self, st: SolverState) -> FloatArray:
        if not self.controllers:
            return np.zeros(0)
        return np.concatenate([st.ctrl[f"{c.id}.y"] for c in self.controllers])

    def run(self, st: SolverState, net: FloatArray) -> None:
        """Run every due controller at the grid point ``st`` (network signals ``net``)."""
        io = ControlIO(self.solver, st)
        for c, idx in zip(self.controllers, self._in_idx, strict=True):
            if st.step % c.every:
                continue
            full = np.concatenate([net, self.outputs(st)])
            y = c.update(st.t, c.every * self.solver.dt, st.ctrl[f"{c.id}.x"], full[idx], io)
            st.ctrl[f"{c.id}.y"] = np.asarray(y, dtype=float)
