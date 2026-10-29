"""Fixed-step nodal EMT solver (Dommel method) for linear networks.

Every branch ``b`` between nodes ``k`` and ``m`` obeys ``i_b = G_b * v_b + h_b`` with
``v_b = v_k - v_m`` (SPEC S-01). Trapezoidal discretisation (SPEC S-02)::

    R:  G = 1/R        h = 0
    L:  G = dt/(2L)    h(t+dt) = i(t) + G v(t)
    C:  G = 2C/dt      h(t+dt) = -i(t) - G v(t)

A voltage source with internal resistance ``R > 0`` becomes a Norton branch
(``G = 1/R``, ``h = -G U(t)``). An ideal source (``R`` absent or 0) must have one grounded
terminal; its other node is a known-voltage node and the network is partitioned as in
Dommel (1969)::

    G_uu v_u = J_u - (A h)_u - G_uk v_k

Start-up (SPEC S-08a, zero initial state): with ``cda`` enabled the first step is done as
two backward-Euler half steps (Critical Damping Adjustment, SPEC S-02). Backward Euler with
step dt/2 has the same branch conductances as the trapezoidal rule with step dt, so ``G``
is factorised only once, and the start needs neither ``v_L(0)`` nor ``i_C(0)``. With
``cda`` disabled the trapezoidal rule is used from t = 0 assuming ``v_L(0) = 0`` and
``i_C(0) = 0``.

References
----------
H. W. Dommel, "Digital computer solution of electromagnetic transients in single- and
multiphase networks", IEEE Trans. PAS-88(4), 1969.
J. R. Marti, J. Lin, "Suppression of numerical oscillations in the EMTP", IEEE Trans.
Power Systems 4(2), 1989 (CDA).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp
from numpy.typing import NDArray
from scipy.sparse.linalg import splu

from vnemt.errors import SolverError, TopologyError
from vnemt.model.netlist import Element, Netlist, is_ground

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

# Branch kind codes (kept as integers for Numba in M1).
K_R, K_L, K_C, K_VN = 0, 1, 2, 3


@dataclass
class _Sources:
    """Vectorised time functions ``a * ramp(t) * (1 or sin(2 pi f t + phi))``."""

    amp: FloatArray
    freq: FloatArray  # 0 => DC
    phase: FloatArray  # rad
    ramp: FloatArray  # s, 0 => step

    @classmethod
    def from_elements(cls, els: list[Element], amp_key: dict[str, str]) -> _Sources:
        amp = np.array([el.p(amp_key[el.kind]) for el in els], dtype=float)
        freq = np.array([el.p("f_Hz") for el in els], dtype=float)
        phase = np.deg2rad(np.array([el.p("phase_deg") for el in els], dtype=float))
        ramp = np.array([el.p("ramp_s") for el in els], dtype=float)
        return cls(amp, freq, phase, ramp)

    def __call__(self, t: float) -> FloatArray:
        with np.errstate(divide="ignore", invalid="ignore"):
            r = np.where(self.ramp > 0.0, np.minimum(t / self.ramp, 1.0), 1.0)
        wave = np.where(self.freq > 0.0, np.sin(2.0 * np.pi * self.freq * t + self.phase), 1.0)
        out: FloatArray = self.amp * r * wave
        return out


_AMP_KEY = {"V_dc": "U_V", "V_ac": "U_peak_V", "I_dc": "I_A", "I_ac": "I_peak_A"}


@dataclass
class SolverState:
    """Complete solver state at time ``t`` (serialisable; basis for snapshots, SPEC S-09)."""

    t: float
    step: int
    v: FloatArray  # all non-ground node voltages
    i_b: FloatArray  # branch currents k->m
    v_b: FloatArray  # branch voltages
    h: FloatArray  # history terms for the next step
    extra: dict[str, float] = field(default_factory=dict)


class EmtSolver:
    """Linear Dommel solver for a :class:`Netlist`.

    Parameters
    ----------
    netlist : Netlist
        Circuit to solve (SI units).
    dt : float
        Time step in seconds.
    cda : bool
        Start with two backward-Euler half steps (see module docstring).
    """

    def __init__(self, netlist: Netlist, dt: float, cda: bool = True) -> None:
        if dt <= 0:
            raise SolverError(f"bước thời gian dt phải > 0, nhận được {dt}")
        self.netlist = netlist
        self.dt = dt
        self.cda = cda
        self.node_names = netlist.nodes
        self.node_index = {n: i for i, n in enumerate(self.node_names)}
        self._build()

    # ------------------------------------------------------------------ setup
    def _idx(self, node: str) -> int:
        return -1 if is_ground(node) else self.node_index[node]

    def _build(self) -> None:
        dt = self.dt
        branches: list[Element] = []
        kinds: list[int] = []
        g: list[float] = []
        ideal_v: list[Element] = []
        isrc: list[Element] = []

        def add(el: Element, kind: int, gb: float) -> None:
            branches.append(el)
            kinds.append(kind)
            g.append(gb)

        for el in self.netlist.elements:
            if el.kind == "R":
                add(el, K_R, 1.0 / el.p("R_ohm"))
            elif el.kind == "L":
                add(el, K_L, dt / (2.0 * el.p("L_H")))
            elif el.kind == "C":
                add(el, K_C, 2.0 * el.p("C_F") / dt)
            elif el.kind in ("V_dc", "V_ac"):
                if el.p("R_ohm") > 0.0:
                    add(el, K_VN, 1.0 / el.p("R_ohm"))
                else:
                    ideal_v.append(el)
            else:
                isrc.append(el)

        self.branches = branches
        self.kind: IntArray = np.array(kinds, dtype=np.int64)
        self.g: FloatArray = np.array(g, dtype=float)
        self.bk: IntArray = np.array([self._idx(e.nodes[0]) for e in branches], dtype=np.int64)
        self.bm: IntArray = np.array([self._idx(e.nodes[1]) for e in branches], dtype=np.int64)
        self.branch_index = {e.id: i for i, e in enumerate(branches)}
        vn = [e for e in branches if e.kind in ("V_dc", "V_ac")]
        self._vn_pos: IntArray = np.array([self.branch_index[e.id] for e in vn], dtype=np.int64)
        self._vn_src = _Sources.from_elements(vn, _AMP_KEY)

        # Ideal voltage sources -> known-voltage nodes.
        known: dict[int, tuple[int, float]] = {}  # node -> (source idx, sign)
        for j, el in enumerate(ideal_v):
            k, m = el.nodes
            if is_ground(k) == is_ground(m):
                raise TopologyError(
                    f"nguồn áp '{el.id}': nguồn lý tưởng (không có R_ohm) phải có đúng một đầu "
                    f"nối đất; hãy khai báo R_ohm > 0 cho nguồn nổi"
                )
            node, sign = (self._idx(k), 1.0) if not is_ground(k) else (self._idx(m), -1.0)
            if node in known:
                other = ideal_v[known[node][0]].id
                raise TopologyError(
                    f"nút '{self.node_names[node]}' bị hai nguồn áp lý tưởng '{other}' và "
                    f"'{el.id}' cùng áp đặt"
                )
            known[node] = (j, sign)
        self.ideal_v = ideal_v
        self._iv_src = _Sources.from_elements(ideal_v, _AMP_KEY)
        self.known_nodes: IntArray = np.array(sorted(known), dtype=np.int64)
        self._known_src: IntArray = np.array(
            [known[n][0] for n in self.known_nodes], dtype=np.int64
        )
        self._known_sign: FloatArray = np.array([known[n][1] for n in self.known_nodes])

        self.isrc = isrc
        self._is_src = _Sources.from_elements(isrc, _AMP_KEY)
        self._is_k = np.array([self._idx(e.nodes[0]) for e in isrc], dtype=np.int64)
        self._is_m = np.array([self._idx(e.nodes[1]) for e in isrc], dtype=np.int64)

        n = len(self.node_names)
        is_known = np.zeros(n, dtype=bool)
        is_known[self.known_nodes] = True
        self.unknown_nodes: IntArray = np.flatnonzero(~is_known).astype(np.int64)

        # Full nodal conductance matrix, then partition.
        rows: list[int] = []
        cols: list[int] = []
        vals: list[float] = []
        for k, m, gb in zip(self.bk, self.bm, self.g, strict=True):
            for a, b, s in ((k, k, 1.0), (m, m, 1.0), (k, m, -1.0), (m, k, -1.0)):
                if a >= 0 and b >= 0:
                    rows.append(int(a))
                    cols.append(int(b))
                    vals.append(s * gb)
        G = sp.csc_matrix((vals, (rows, cols)), shape=(n, n))
        u, kn = self.unknown_nodes, self.known_nodes
        self.G_uu = G[u][:, u].tocsc()
        self.G_uk = G[u][:, kn].tocsc()
        self._check_floating()
        try:
            self._lu = splu(self.G_uu) if len(u) else None
        except RuntimeError as exc:
            raise TopologyError(
                "ma trận điện dẫn suy biến: có nút nổi hoặc vòng chỉ gồm nguồn"
            ) from exc

    def _check_floating(self) -> None:
        """Every unknown node needs a conductive path to ground or to a known node."""
        n = len(self.node_names)
        adj: list[list[int]] = [[] for _ in range(n + 1)]  # index n = ground
        for k, m in zip(self.bk, self.bm, strict=True):
            a, b = (n if k < 0 else int(k)), (n if m < 0 else int(m))
            adj[a].append(b)
            adj[b].append(a)
        reached = {n, *map(int, self.known_nodes)}
        stack = list(reached)
        while stack:
            x = stack.pop()
            for y in adj[x]:
                if y not in reached:
                    reached.add(y)
                    stack.append(y)
        floating = [self.node_names[i] for i in range(n) if i not in reached]
        if floating:
            raise TopologyError(
                "nút nổi (không có đường dẫn điện về đất hoặc nguồn áp): " + ", ".join(floating)
            )

    # --------------------------------------------------------------- stepping
    def initial_state(self) -> SolverState:
        """Zero initial state with element initial conditions (``i0_A``, ``v0_V``)."""
        nb = len(self.branches)
        i_b = np.zeros(nb)
        v_b = np.zeros(nb)
        for j, el in enumerate(self.branches):
            if el.kind == "L":
                i_b[j] = el.p("i0_A")
            elif el.kind == "C":
                v_b[j] = el.p("v0_V")
        v = np.zeros(len(self.node_names))
        st = SolverState(t=0.0, step=0, v=v, i_b=i_b, v_b=v_b, h=np.zeros(nb))
        st.h = self._history(st.i_b, st.v_b, backward_euler=self.cda)
        return st

    def _history(self, i_b: FloatArray, v_b: FloatArray, backward_euler: bool) -> FloatArray:
        """History terms for the next (half-)step from branch states at current time."""
        h = np.zeros_like(i_b)
        isl, isc = self.kind == K_L, self.kind == K_C
        if backward_euler:  # step dt/2: G_L = dt/(2L), G_C = 2C/dt
            h[isl] = i_b[isl]
            h[isc] = -self.g[isc] * v_b[isc]
        else:
            h[isl] = i_b[isl] + self.g[isl] * v_b[isl]
            h[isc] = -i_b[isc] - self.g[isc] * v_b[isc]
        return h

    def _solve_at(self, t: float, h: FloatArray) -> tuple[FloatArray, FloatArray, FloatArray]:
        """Solve the network at time ``t`` given history ``h``; return (v, v_b, i_b)."""
        n = len(self.node_names)
        h = h.copy()
        if len(self._vn_pos):
            h[self._vn_pos] = -self.g[self._vn_pos] * self._vn_src(t)
        rhs = np.zeros(n + 1)  # last slot collects ground contributions
        np.add.at(rhs, self.bk, -h)
        np.add.at(rhs, self.bm, h)
        if len(self.isrc):
            j = self._is_src(t)
            np.add.at(rhs, self._is_k, j)
            np.add.at(rhs, self._is_m, -j)
        v = np.zeros(n + 1)
        if len(self.known_nodes):
            v[self.known_nodes] = self._known_sign * self._iv_src(t)[self._known_src]
        if self._lu is not None:
            b = rhs[self.unknown_nodes] - self.G_uk @ v[self.known_nodes]
            v[self.unknown_nodes] = self._lu.solve(b)
        v_b = v[self.bk] - v[self.bm]  # v[-1] is the ground slot (always 0)
        i_b = self.g * v_b + h
        return v[:n], v_b, i_b

    def step(self, st: SolverState) -> SolverState:
        """Advance one full step ``dt``."""
        dt = self.dt
        if st.step == 0 and self.cda:
            _, v_b, i_b = self._solve_at(st.t + dt / 2, st.h)
            h = self._history(i_b, v_b, backward_euler=True)
        else:
            h = st.h
        t = st.t + dt
        v, v_b, i_b = self._solve_at(t, h)
        if not np.all(np.isfinite(v)):
            raise SolverError(f"nghiệm không hữu hạn tại t = {t:.6g} s")
        h_next = self._history(i_b, v_b, backward_euler=False)
        return SolverState(t=t, step=st.step + 1, v=v, i_b=i_b, v_b=v_b, h=h_next)

    # ---------------------------------------------------------------- signals
    def signal_layout(self) -> list[tuple[str, str]]:
        """``(name, unit)`` of every recordable signal, in :meth:`probe` order."""
        out = [(f"{n}.V", "V") for n in self.node_names]
        out += [(f"{e.id}.I", "A") for e in self.branches]
        out += [(f"{e.id}.V", "V") for e in self.branches]
        for group in (self.ideal_v, self.isrc):
            out += [(f"{e.id}.I", "A") for e in group]
            out += [(f"{e.id}.V", "V") for e in group]
        return out

    def probe(self, st: SolverState) -> FloatArray:
        """All recordable quantities at state ``st``, ordered as :meth:`signal_layout`.

        Element voltage is ``v_k - v_m``; element current flows ``k -> m`` through passive
        elements and out of the positive terminal ``k`` for sources.
        """
        vfull = np.append(st.v, 0.0)
        i_b = st.i_b.copy()
        i_b[self._vn_pos] *= -1.0  # Norton sources: report current delivered
        iv = self._iv_src(st.t)
        js = self._is_src(st.t)
        out: FloatArray = np.concatenate(
            [
                st.v,
                i_b,
                st.v_b,
                self.ideal_source_currents(st),
                iv,
                js,
                vfull[self._is_k] - vfull[self._is_m],
            ]
        )
        return out

    def ideal_source_currents(self, st: SolverState) -> FloatArray:
        """Current delivered by each ideal voltage source (out of its positive terminal)."""
        n = len(self.node_names)
        inj = np.zeros(n + 1)  # net current leaving each node through branches
        np.add.at(inj, self.bk, st.i_b)
        np.add.at(inj, self.bm, -st.i_b)
        if len(self.isrc):
            j = self._is_src(st.t)
            np.add.at(inj, self._is_k, -j)
            np.add.at(inj, self._is_m, j)
        out = np.zeros(len(self.ideal_v))
        for node, src, sign in zip(
            self.known_nodes, self._known_src, self._known_sign, strict=True
        ):
            out[src] = sign * inj[node]
        return out
