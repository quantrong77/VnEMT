"""Fixed-step nodal EMT solver (Dommel method) with switching, interpolation and CDA.

Every branch ``b`` between nodes ``k`` and ``m`` obeys ``i_b = G_b * v_b + h_b`` with
``v_b = v_k - v_m`` (SPEC S-01). Trapezoidal discretisation with step ``dt`` (SPEC S-02)::

    R:  G = 1/R        h = 0
    L:  G = dt/(2L)    h(t+dt) = i(t) + G v(t)
    C:  G = 2C/dt      h(t+dt) = -i(t) - G v(t)

Critical Damping Adjustment (CDA, SPEC S-02): after every topology change (and at start-up
from the zero state) two backward-Euler half steps of ``dt/2`` are taken. Backward Euler with
step ``dt/2`` has the same branch conductances as the trapezoidal rule with step ``dt``::

    L:  h(t+dt/2) = i(t)          C:  h(t+dt/2) = -G v(t)

so the matrix depends only on the switch states, and the history needs only the state
variables ``i_L`` and ``v_C`` (continuous across switching).

A voltage source with internal resistance ``R > 0`` is a Norton branch (``G = 1/R``,
``h = -G U(t)``). An ideal source must have one grounded terminal; its other node is a
known-voltage node and the network is partitioned as in Dommel (1969)::

    G_uu v_u = J_u - (A h)_u - G_uk v_k

Switching devices (:mod:`vnemt.core.switching`) change ``G``; LU factorisations are cached per
switch-state combination (SPEC S-05). Switching instants inside a step are found by linear
interpolation, the network state is interpolated to that instant, and after the post-switch
step the solution is interpolated back onto the regular time grid (SPEC S-04).

The solver state is only ``(v, i_b, v_b)`` plus switch/CDA bookkeeping; history terms are
recomputed from it for the rule of the next step. This makes interpolation and snapshots
(SPEC S-09) exact and simple.

References
----------
H. W. Dommel, "Digital computer solution of electromagnetic transients in single- and
multiphase networks", IEEE Trans. PAS-88(4), 1969.
J. R. Marti, J. Lin, "Suppression of numerical oscillations in the EMTP", IEEE Trans.
Power Systems 4(2), 1989 (CDA).
P. Kuffel, K. Kent, G. Irwin, "The implementation and effectiveness of linear interpolation
within digital simulation", Int. J. Electrical Power & Energy Systems 19(4), 1997.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
import scipy.sparse as sp
from numpy.typing import NDArray
from scipy.sparse.linalg import splu

from vnemt.core.switching import BoolArray, SwitchSet
from vnemt.errors import SolverError, TopologyError
from vnemt.model.netlist import Element, Netlist, is_ground

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

# Branch kind codes (kept as integers for Numba later).
K_R, K_L, K_C, K_VN, K_SW = 0, 1, 2, 3, 4

MAX_EVENTS_PER_STEP = 100
_LU_CACHE_MAX = 4096


@dataclass
class _Sources:
    """Vectorised time functions ``a * ramp(t) * (1 or sin(2 pi f t + phi))``."""

    amp: FloatArray
    freq: FloatArray  # 0 => DC
    phase: FloatArray  # rad
    ramp: FloatArray  # s, 0 => step

    @classmethod
    def from_elements(cls, els: list[Element]) -> _Sources:
        amp = np.array([el.p(_AMP_KEY[el.kind]) for el in els], dtype=float)
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
    step: int  # index of the last regular grid point reached
    v: FloatArray  # non-ground node voltages
    i_b: FloatArray  # branch currents k->m
    v_b: FloatArray  # branch voltages
    sw_on: BoolArray  # switch conduction states
    armed: BoolArray  # breakers waiting for a current zero
    sched_idx: IntArray  # next schedule entry per switch
    cda_left: int = 0  # backward-Euler half steps still to take

    def copy(self) -> SolverState:
        return replace(
            self,
            v=self.v.copy(),
            i_b=self.i_b.copy(),
            v_b=self.v_b.copy(),
            sw_on=self.sw_on.copy(),
            armed=self.armed.copy(),
            sched_idx=self.sched_idx.copy(),
        )


@dataclass
class SwitchEvent:
    t: float
    id: str
    on: bool


@dataclass
class _Topology:
    lu: Any
    G_uk: Any
    g: FloatArray
    h_sw: FloatArray


@dataclass
class SolverStats:
    lu_factorizations: int = 0
    events: int = 0
    interpolations: int = 0
    extra: dict[str, int] = field(default_factory=dict)


class EmtSolver:
    """Dommel solver for a :class:`Netlist` with two-state switching devices.

    Parameters
    ----------
    netlist : Netlist
        Circuit to solve (SI units).
    dt : float
        Time step in seconds.
    cda : bool
        Critical Damping Adjustment at start-up and after every topology change.
    """

    def __init__(self, netlist: Netlist, dt: float, cda: bool = True) -> None:
        if dt <= 0:
            raise SolverError(f"bước thời gian dt phải > 0, nhận được {dt}")
        self.netlist = netlist
        self.dt = dt
        self.cda = cda
        self.node_names = netlist.nodes
        self.node_index = {n: i for i, n in enumerate(self.node_names)}
        self.events: list[SwitchEvent] = []
        self.stats = SolverStats()
        self._lu_cache: dict[bytes, _Topology] = {}
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
            elif el.kind in ("SW", "D"):
                add(el, K_SW, 0.0)  # conductance set per switch state
            else:
                isrc.append(el)

        self.branches = branches
        self.kind: IntArray = np.array(kinds, dtype=np.int64)
        self.g_base: FloatArray = np.array(g, dtype=float)
        self.bk: IntArray = np.array([self._idx(e.nodes[0]) for e in branches], dtype=np.int64)
        self.bm: IntArray = np.array([self._idx(e.nodes[1]) for e in branches], dtype=np.int64)
        self.branch_index = {e.id: i for i, e in enumerate(branches)}
        self._isl, self._isc = self.kind == K_L, self.kind == K_C
        vn = [e for e in branches if e.kind in ("V_dc", "V_ac")]
        self._vn_pos: IntArray = np.array([self.branch_index[e.id] for e in vn], dtype=np.int64)
        self._vn_src = _Sources.from_elements(vn)
        sw = [e for e in branches if e.kind in ("SW", "D")]
        self.switches = SwitchSet.from_elements(sw, [self.branch_index[e.id] for e in sw])

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
        self._iv_src = _Sources.from_elements(ideal_v)
        self.known_nodes: IntArray = np.array(sorted(known), dtype=np.int64)
        self._known_src: IntArray = np.array(
            [known[n][0] for n in self.known_nodes], dtype=np.int64
        )
        self._known_sign: FloatArray = np.array([known[n][1] for n in self.known_nodes])

        self.isrc = isrc
        self._is_src = _Sources.from_elements(isrc)
        self._is_k = np.array([self._idx(e.nodes[0]) for e in isrc], dtype=np.int64)
        self._is_m = np.array([self._idx(e.nodes[1]) for e in isrc], dtype=np.int64)

        n = len(self.node_names)
        is_known = np.zeros(n, dtype=bool)
        is_known[self.known_nodes] = True
        self.unknown_nodes: IntArray = np.flatnonzero(~is_known).astype(np.int64)
        self._check_floating()

    def _check_floating(self) -> None:
        """Every unknown node needs a conductive path to ground or to a known node.

        Switch branches count as conductive (their off resistance is finite).
        """
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

    def _topology(self, sw_on: BoolArray) -> _Topology:
        """Factorised matrices for a switch-state combination (cached, SPEC S-05)."""
        key = sw_on.tobytes()
        top = self._lu_cache.get(key)
        if top is not None:
            return top
        g = self.g_base.copy()
        h_sw = np.zeros_like(g)
        if len(self.switches):
            g[self.switches.pos] = self.switches.conductance(sw_on)
            h_sw[self.switches.pos] = self.switches.norton(sw_on)
        n = len(self.node_names)
        ka, ma = self.bk, self.bm
        rows = np.concatenate([ka, ma, ka, ma])
        cols = np.concatenate([ka, ma, ma, ka])
        vals = np.concatenate([g, g, -g, -g])
        keep = (rows >= 0) & (cols >= 0)
        G = sp.csc_matrix((vals[keep], (rows[keep], cols[keep])), shape=(n, n))
        u, kn = self.unknown_nodes, self.known_nodes
        G_uu = G[u][:, u].tocsc()
        try:
            lu = splu(G_uu) if len(u) else None
        except RuntimeError as exc:
            raise TopologyError(
                "ma trận điện dẫn suy biến: có nút nổi hoặc vòng chỉ gồm nguồn"
            ) from exc
        top = _Topology(lu=lu, G_uk=G[u][:, kn].tocsc(), g=g, h_sw=h_sw)
        if len(self._lu_cache) >= _LU_CACHE_MAX:
            self._lu_cache.clear()
        self._lu_cache[key] = top
        self.stats.lu_factorizations += 1
        return top

    def fingerprint(self) -> str:
        """SHA-256 of the netlist and time step; snapshots are only valid for the same value."""
        desc = [
            [e.id, e.kind, list(e.nodes), sorted((k, v) for k, v in e.params.items())]
            for e in self.netlist.elements
        ]
        text = json.dumps({"dt": self.dt, "cda": self.cda, "elements": desc}, sort_keys=True)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    # --------------------------------------------------------------- stepping
    def initial_state(self) -> SolverState:
        """Zero initial state with element initial conditions (``i0_A``, ``v0_V``).

        Switch commands at ``t <= 0`` are applied immediately.
        """
        nb = len(self.branches)
        i_b = np.zeros(nb)
        v_b = np.zeros(nb)
        for j, el in enumerate(self.branches):
            if el.kind == "L":
                i_b[j] = el.p("i0_A")
            elif el.kind == "C":
                v_b[j] = el.p("v0_V")
        ns = len(self.switches)
        st = SolverState(
            t=0.0, step=0, v=np.zeros(len(self.node_names)), i_b=i_b, v_b=v_b,
            sw_on=self.switches.initial_on.copy(), armed=np.zeros(ns, dtype=bool),
            sched_idx=np.zeros(ns, dtype=np.int64), cda_left=2 if self.cda else 0,
        )
        for j in range(ns):
            while (cmd := self.switches.next_command(j, int(st.sched_idx[j]))) is not None \
                    and cmd[0] <= 0.0:
                mask = np.zeros(ns, dtype=bool)
                mask[j] = True
                for sid, on in self.switches.apply(0.0, mask, st.sw_on, st.armed, st.sched_idx):
                    self.events.append(SwitchEvent(0.0, sid, on))
        return st

    def _history(self, st: SolverState, backward_euler: bool) -> FloatArray:
        """History terms for the next (half-)step from branch states of ``st``."""
        h = np.zeros_like(st.i_b)
        isl, isc = self._isl, self._isc
        g = self.g_base
        if backward_euler:
            h[isl] = st.i_b[isl]
            h[isc] = -g[isc] * st.v_b[isc]
        else:
            h[isl] = st.i_b[isl] + g[isl] * st.v_b[isl]
            h[isc] = -st.i_b[isc] - g[isc] * st.v_b[isc]
        return h

    def _solve(self, st: SolverState, t: float, backward_euler: bool) -> SolverState:
        """Advance ``st`` to time ``t`` with fixed topology; returns the new state."""
        top = self._topology(st.sw_on)
        n = len(self.node_names)
        h = self._history(st, backward_euler) + top.h_sw
        if len(self._vn_pos):
            h[self._vn_pos] = -top.g[self._vn_pos] * self._vn_src(t)
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
        if top.lu is not None:
            b = rhs[self.unknown_nodes] - top.G_uk @ v[self.known_nodes]
            v[self.unknown_nodes] = top.lu.solve(b)
        if not np.all(np.isfinite(v)):
            raise SolverError(f"nghiệm không hữu hạn tại t = {t:.9g} s")
        v_b = v[self.bk] - v[self.bm]  # v[-1] is the ground slot (always 0)
        i_b = top.g * v_b + h
        out = st.copy()
        out.t, out.v, out.v_b, out.i_b = t, v[:n], v_b, i_b
        return out

    @staticmethod
    def _interp(a: SolverState, b: SolverState, lam: float) -> SolverState:
        """Linear interpolation of the network state; bookkeeping is taken from ``a``."""
        out = a.copy()
        out.t = a.t + lam * (b.t - a.t)
        out.v = a.v + lam * (b.v - a.v)
        out.i_b = a.i_b + lam * (b.i_b - a.i_b)
        out.v_b = a.v_b + lam * (b.v_b - a.v_b)
        return out

    def _first_event(self, a: SolverState, b: SolverState) -> tuple[float, BoolArray]:
        sw = self.switches
        if not len(sw):
            return np.inf, np.zeros(0, dtype=bool)
        p = sw.pos
        lam = sw.event_fractions(a.t, b.t, a.sw_on, a.armed, a.sched_idx,
                                 a.i_b[p], b.i_b[p], a.v_b[p], b.v_b[p])
        lmin = float(np.min(lam))
        return lmin, lam <= lmin + 1e-9

    def step(self, st: SolverState) -> SolverState:
        """Advance from regular grid point ``st.step`` to the next one, handling switching."""
        dt = self.dt
        target_step = st.step + 1
        T = target_step * dt
        tol = 1e-9 * dt
        n_ev = 0
        cur = st
        while True:
            be = cur.cda_left > 0
            nxt = self._solve(cur, cur.t + (dt / 2 if be else dt), backward_euler=be)
            if be:
                nxt.cda_left = cur.cda_left - 1
            lam, mask = self._first_event(cur, nxt)
            if lam <= 1.0 and cur.t + lam * (nxt.t - cur.t) <= T + tol:
                x = self._interp(cur, nxt, lam) if lam < 1.0 else nxt
                if lam < 1.0:
                    self.stats.interpolations += 1
                x.cda_left = cur.cda_left if lam < 1.0 else nxt.cda_left
                changed = self.switches.apply(x.t, mask, x.sw_on, x.armed, x.sched_idx)
                for sid, on in changed:
                    self.events.append(SwitchEvent(x.t, sid, on))
                if changed:
                    self.stats.events += len(changed)
                    if self.cda:
                        x.cda_left = 2
                n_ev += 1
                if n_ev > MAX_EVENTS_PER_STEP:
                    ids = sorted({e.id for e in self.events[-20:]})
                    raise SolverError(
                        f"quá {MAX_EVENTS_PER_STEP} lần đóng cắt trong một bước tại "
                        f"t ≈ {x.t:.9g} s (rung đóng cắt); khóa liên quan: {', '.join(ids)}"
                    )
                cur = x
                if abs(cur.t - T) <= tol:
                    cur.t, cur.step = T, target_step
                    return cur
                continue
            if nxt.t > T + tol:  # overshoot: interpolate back onto the grid
                self.stats.interpolations += 1
                out = self._interp(cur, nxt, (T - cur.t) / (nxt.t - cur.t))
                out.cda_left = nxt.cda_left
            else:
                out = nxt
            if abs(out.t - T) <= tol:
                out.t, out.step = T, target_step
                return out
            cur = out

    # ---------------------------------------------------------------- signals
    def signal_layout(self) -> list[tuple[str, str]]:
        """``(name, unit)`` of every recordable signal, in :meth:`probe` order."""
        out = [(f"{n}.V", "V") for n in self.node_names]
        out += [(f"{e.id}.I", "A") for e in self.branches]
        out += [(f"{e.id}.V", "V") for e in self.branches]
        for group in (self.ideal_v, self.isrc):
            out += [(f"{e.id}.I", "A") for e in group]
            out += [(f"{e.id}.V", "V") for e in group]
        out += [(f"{sid}.on", "-") for sid in self.switches.ids]
        return out

    def probe(self, st: SolverState) -> FloatArray:
        """All recordable quantities at state ``st``, ordered as :meth:`signal_layout`.

        Element voltage is ``v_k - v_m``; element current flows ``k -> m`` through passive
        elements and switches, and out of the positive terminal ``k`` for sources.
        """
        vfull = np.append(st.v, 0.0)
        i_b = st.i_b.copy()
        i_b[self._vn_pos] *= -1.0  # Norton sources: report current delivered
        out: FloatArray = np.concatenate(
            [
                st.v,
                i_b,
                st.v_b,
                self.ideal_source_currents(st),
                self._iv_src(st.t),
                self._is_src(st.t),
                vfull[self._is_k] - vfull[self._is_m],
                st.sw_on.astype(float),
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
