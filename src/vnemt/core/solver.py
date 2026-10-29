"""Fixed-step nodal EMT solver (Dommel method) with switching, interpolation and CDA.

Branch equations are written for the vector of branch voltages ``v_b`` (``v_k - v_m``) and
currents ``i_b`` (``k -> m``) with a sparse branch admittance matrix ``Y`` (SPEC S-01)::

    i_b = Y v_b + h,        G = A Y A^T     (A: node-branch incidence, ground removed)

``Y`` is diagonal except for coupled branch groups (transformer windings). Trapezoidal
discretisation with step ``dt`` (SPEC S-02)::

    R:  Y = 1/R          h = 0
    L:  Y = dt/2 L^-1    h(t+dt) = i(t) + Y v(t)          (L^-1 may be a matrix: coupling)
    C:  Y = 2C/dt        h(t+dt) = -i(t) - Y v(t)

Critical Damping Adjustment (CDA, SPEC S-02): after every topology change (and at start-up
from the zero state) two backward-Euler half steps of ``dt/2`` are taken. Backward Euler with
step ``dt/2`` has the same ``Y`` as the trapezoidal rule with step ``dt``::

    L:  h(t+dt/2) = i(t)          C:  h(t+dt/2) = -Y v(t)

so the matrix depends only on the switch states, and the history needs only the state
variables ``i_L`` and ``v_C`` (continuous across switching).

Single-phase two-winding transformer ``XF1`` (nodes ``k1, m1, k2, m2``, ratio ``a = U1/U2``,
leakage ``L_k`` referred to winding 1, no magnetising current) uses the inverse-inductance
form, valid when the magnetising inductance is infinite::

    d/dt [i1, i2] = (1/L_k) [[1, -a], [-a, a^2]] [v1, v2]

An optional magnetising inductance ``Lm_H`` is a separate branch across winding 1.

A voltage source with internal resistance ``R > 0`` is a Norton branch (``Y = 1/R``,
``h = -U(t)/R``). An ideal source must have one grounded terminal; its other node is a
known-voltage node and the network is partitioned as in Dommel (1969)::

    G_uu v_u = J_u - (A h)_u - G_uk v_k

Switching devices (:mod:`vnemt.core.switching`) change ``Y``; LU factorisations are cached per
switch-state combination (SPEC S-05). Switching instants inside a step are found by linear
interpolation, the network state is interpolated to that instant, and after the post-switch
step the solution is interpolated back onto the regular time grid (SPEC S-04).

The solver state is ``(v, i_b, v_b)`` plus switching, CDA and control bookkeeping; history
terms are recomputed from it for the rule of the next step, which keeps interpolation and
snapshots (SPEC S-09) exact.

References
----------
H. W. Dommel, "Digital computer solution of electromagnetic transients in single- and
multiphase networks", IEEE Trans. PAS-88(4), 1969.
H. W. Dommel, *EMTP Theory Book*, 2nd ed., Microtran, 1992, ch. 6 (transformers, L^-1 form).
J. R. Marti, J. Lin, "Suppression of numerical oscillations in the EMTP", IEEE Trans.
Power Systems 4(2), 1989 (CDA).
P. Kuffel, K. Kent, G. Irwin, "The implementation and effectiveness of linear interpolation
within digital simulation", Int. J. Electrical Power & Energy Systems 19(4), 1997.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import scipy.sparse as sp
from numpy.typing import NDArray
from scipy.sparse.linalg import splu

from vnemt.core.lines import LineSet
from vnemt.core.switching import DEV_THYRISTOR, BoolArray, DeviceState, SwitchSet
from vnemt.errors import SolverError, TopologyError
from vnemt.model.netlist import Element, Netlist, is_ground

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

# Branch kind codes (kept as integers for Numba later).
K_R, K_L, K_C, K_VN, K_SW, K_LINE = 0, 1, 2, 3, 4, 5

MAX_EVENTS_PER_STEP = 100
_LU_CACHE_MAX = 4096


@dataclass
class _Sources:
    """Vectorised time functions ``a * ramp(t) * (1 or sin(2 pi f t + phi))``."""

    amp: FloatArray
    freq: FloatArray  # 0 => DC
    phase: FloatArray  # rad
    ramp: FloatArray  # s, 0 => step
    mods: list[tuple[int, float, float, float]] = field(default_factory=list)
    # amplitude modulations (source index, t_start, t_end, factor): controlled dips (F4-02)

    @classmethod
    def from_elements(cls, els: list[Element],
                      mods: Mapping[str, list[tuple[float, float, float]]] | None = None
                      ) -> _Sources:
        amp = np.array([el.p(_AMP_KEY[el.kind]) for el in els], dtype=float)
        freq = np.array([el.p("f_Hz") for el in els], dtype=float)
        phase = np.deg2rad(np.array([el.p("phase_deg") for el in els], dtype=float))
        ramp = np.array([el.p("ramp_s") for el in els], dtype=float)
        idx = {el.id: i for i, el in enumerate(els)}
        ml = [(idx[sid], t0, t1, k) for sid, w in (mods or {}).items() if sid in idx
              for t0, t1, k in w]
        return cls(amp, freq, phase, ramp, ml)

    def __call__(self, t: float) -> FloatArray:
        with np.errstate(divide="ignore", invalid="ignore"):
            r = np.where(self.ramp > 0.0, np.minimum(t / self.ramp, 1.0), 1.0)
        wave = np.where(self.freq > 0.0, np.sin(2.0 * np.pi * self.freq * t + self.phase), 1.0)
        out: FloatArray = self.amp * r * wave
        for i, t0, t1, k in self.mods:
            if t0 <= t < t1:
                out[i] *= k
        return out


_AMP_KEY = {"V_dc": "U_V", "V_ac": "U_peak_V", "I_dc": "I_A", "I_ac": "I_peak_A"}


@dataclass
class SolverState:
    """Complete simulation state at time ``t`` (serialisable; snapshots, SPEC S-09)."""

    t: float
    step: int  # index of the last regular grid point reached
    v: FloatArray  # non-ground node voltages
    i_b: FloatArray  # branch currents k->m
    v_b: FloatArray  # branch voltages
    dev: DeviceState  # switching devices
    cda_left: int = 0  # backward-Euler half steps still to take
    ctrl: dict[str, FloatArray] = field(default_factory=dict)  # control states (S-06)
    hist: dict[str, FloatArray] = field(default_factory=dict)  # line history buffers
    taps: FloatArray = field(default_factory=lambda: np.zeros(0))  # transformer ratio factors

    @property
    def sw_on(self) -> BoolArray:
        return self.dev.on

    def copy(self) -> SolverState:
        return SolverState(
            t=self.t, step=self.step, v=self.v.copy(), i_b=self.i_b.copy(),
            v_b=self.v_b.copy(), dev=self.dev.copy(), cda_left=self.cda_left,
            ctrl={k: a.copy() for k, a in self.ctrl.items()},
            hist={k: a.copy() for k, a in self.hist.items()},
            taps=self.taps.copy(),
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
    Y: Any  # sparse branch admittance matrix for this switch state
    h_sw: FloatArray


@dataclass
class SolverStats:
    lu_factorizations: int = 0
    events: int = 0
    interpolations: int = 0


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
    modulations : mapping, optional
        ``{source id: [(t_start, t_end, factor), ...]}`` amplitude modulation of voltage or
        current sources (controlled voltage dips, F4-02); not part of the fingerprint.
    misfires : mapping, optional
        ``{thyristor id: t}``: the first gate window starting at or after ``t`` is dropped
        (misfire, F4-04).
    """

    def __init__(self, netlist: Netlist, dt: float, cda: bool = True,
                 modulations: Mapping[str, list[tuple[float, float, float]]] | None = None,
                 misfires: Mapping[str, float] | None = None) -> None:
        if dt <= 0:
            raise SolverError(f"bước thời gian dt phải > 0, nhận được {dt}")
        self.netlist = netlist
        self.dt = dt
        self.cda = cda
        self._mods = dict(modulations or {})
        self._misfire_spec = dict(misfires or {})
        self.node_names = netlist.nodes
        self.node_index = {n: i for i, n in enumerate(self.node_names)}
        self.events: list[SwitchEvent] = []
        self.markers: list[tuple[float, str, str]] = []  # (t, device, "fwd" | "cf")
        self.stats = SolverStats()
        self._lu_cache: dict[bytes, _Topology] = {}
        self._build()

    # ------------------------------------------------------------------ setup
    def _idx(self, node: str) -> int:
        return -1 if is_ground(node) else self.node_index[node]

    def _build(self) -> None:
        dt = self.dt
        names: list[str] = []  # branch signal prefix
        owner: list[Element] = []
        kinds: list[int] = []
        g: list[float] = []
        bk: list[int] = []
        bm: list[int] = []
        coup: list[tuple[int, int, float]] = []  # off-diagonal entries of Y
        self.lines = LineSet(dt)
        self._xf: list[tuple[int, int, float, float]] = []  # (b1, b2, y, a0) per XF1
        self._xf_ids: list[str] = []
        self._sat_elements: dict[int, Element] = {}
        ideal_v: list[Element] = []
        isrc: list[Element] = []

        def add(el: Element, kind: int, gb: float, k: str, m: str, name: str = "") -> int:
            names.append(name or el.id)
            owner.append(el)
            kinds.append(kind)
            g.append(gb)
            bk.append(self._idx(k))
            bm.append(self._idx(m))
            return len(g) - 1

        for el in self.netlist.elements:
            n2 = el.nodes[:2]
            if el.kind == "R":
                add(el, K_R, 1.0 / el.p("R_ohm"), *n2)
            elif el.kind == "L":
                add(el, K_L, dt / (2.0 * el.p("L_H")), *n2)
            elif el.kind == "C":
                add(el, K_C, 2.0 * el.p("C_F") / dt, *n2)
            elif el.kind in ("V_dc", "V_ac"):
                if el.p("R_ohm") > 0.0:
                    add(el, K_VN, 1.0 / el.p("R_ohm"), *n2)
                else:
                    ideal_v.append(el)
            elif el.kind in ("SW", "D", "T"):
                add(el, K_SW, 0.0, *n2)  # conductance set per switch state
            elif el.kind == "LSAT":
                add(el, K_L, 0.0, *n2)  # inductor; conductance set by its segment
            elif el.kind == "XF1":
                self._add_transformer(el, add, coup)
            elif el.kind == "LINE":
                self.lines.add(el, lambda e, gb, k, m, nm: add(e, K_LINE, gb, k, m, nm), coup)
            else:
                isrc.append(el)

        self.branch_names = names
        self.branches = owner
        self.kind: IntArray = np.array(kinds, dtype=np.int64)
        self.g_base: FloatArray = np.array(g, dtype=float)
        self.bk: IntArray = np.array(bk, dtype=np.int64)
        self.bm: IntArray = np.array(bm, dtype=np.int64)
        nb = len(g)
        self.branch_index = {nm: i for i, nm in enumerate(names)}
        self._isl, self._isc = self.kind == K_L, self.kind == K_C
        cr = [c[0] for c in coup]
        cc = [c[1] for c in coup]
        self._Ycoup = sp.csr_matrix(([c[2] for c in coup], (cr, cc)), shape=(nb, nb))
        self._vn_pos: IntArray = np.flatnonzero(self.kind == K_VN).astype(np.int64)
        self._vn_src = _Sources.from_elements([owner[i] for i in self._vn_pos], self._mods)
        is_dev = (self.kind == K_SW) | np.array([e.kind == "LSAT" for e in owner], dtype=bool)
        is_dev[list(self._sat_elements)] = True
        sw_pos = np.flatnonzero(is_dev)
        # the saturable magnetising branch of a transformer is its own LSAT element
        sw_els = [self._sat_elements.get(int(i), owner[i]) for i in sw_pos]
        self.switches = SwitchSet.from_elements(sw_els, list(sw_pos), dt)
        self._sw_index = {sid: j for j, sid in enumerate(self.switches.ids)}
        unknown = [v for v in self._misfire_spec if v not in self._sw_index]
        if unknown:
            raise SolverError(f"sự kiện misfire: không có van {', '.join(unknown)}")
        self._misfire = {self._sw_index[v]: t for v, t in self._misfire_spec.items()}
        base_nodes = self.netlist.base_nodes()
        self.n_base_nodes = sum(1 for nd in self.node_names if nd in base_nodes)
        self.n_base_branches = sum(1 for e in owner if e.origin != "event")
        self.n_base_switches = sum(1 for i in sw_pos if owner[i].origin != "event")

        # node-branch incidence (ground column dropped)
        n = len(self.node_names)
        rows = np.concatenate([self.bk, self.bm])
        cols = np.concatenate([np.arange(nb), np.arange(nb)])
        vals = np.concatenate([np.ones(nb), -np.ones(nb)])
        keep = rows >= 0
        self._A = sp.csr_matrix((vals[keep], (rows[keep], cols[keep])), shape=(n, nb))

        # Ideal voltage sources -> known-voltage nodes.
        known: dict[int, tuple[int, float]] = {}  # node -> (source idx, sign)
        for j, el in enumerate(ideal_v):
            k, m = el.nodes[:2]
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
        self._iv_src = _Sources.from_elements(ideal_v, self._mods)
        self.known_nodes: IntArray = np.array(sorted(known), dtype=np.int64)
        self._known_src: IntArray = np.array(
            [known[n][0] for n in self.known_nodes], dtype=np.int64
        )
        self._known_sign: FloatArray = np.array([known[n][1] for n in self.known_nodes])

        self.isrc = isrc
        self._is_src = _Sources.from_elements(isrc, self._mods)
        self._is_k = np.array([self._idx(e.nodes[0]) for e in isrc], dtype=np.int64)
        self._is_m = np.array([self._idx(e.nodes[1]) for e in isrc], dtype=np.int64)

        is_known = np.zeros(n, dtype=bool)
        is_known[self.known_nodes] = True
        self.unknown_nodes: IntArray = np.flatnonzero(~is_known).astype(np.int64)
        self._check_floating()

    def _add_transformer(self, el: Element, add: Any, coup: list[tuple[int, int, float]]) -> None:
        a = el.p("U1_V") / el.p("U2_V")
        lk = el.p("L_k_H")
        if not lk > 0.0 or not a > 0.0:
            raise TopologyError(f"MBA '{el.id}': cần L_k_H > 0, U1_V > 0, U2_V > 0")
        y = self.dt / (2.0 * lk)
        k1, m1, k2, m2 = el.nodes
        b1 = add(el, K_L, y, k1, m1, f"{el.id}.w1")
        b2 = add(el, K_L, a * a * y, k2, m2, f"{el.id}.w2")
        self._xf.append((b1, b2, y, a))  # coupling -a y is built per tap position
        self._xf_ids.append(el.id)
        if el.p("Lm_H") > 0.0:
            if el.p("Lsat_H") > 0.0:  # saturable magnetising branch (two-slope)
                bm = add(el, K_L, 0.0, k1, m1, f"{el.id}.m")
                self._sat_elements[bm] = Element(
                    f"{el.id}.m", "LSAT", (k1, m1),
                    {"L_H": el.p("Lm_H"), "Lsat_H": el.p("Lsat_H"),
                     "I_knee_A": el.p("Im_knee_A")}, el.origin)
            else:
                add(el, K_L, self.dt / (2.0 * el.p("Lm_H")), k1, m1, f"{el.id}.m")

    def _check_floating(self) -> None:
        """Every unknown node needs a conductive path to ground or to a known node.

        Switch branches count as conductive (their off resistance is finite); transformer
        windings connect only their own two terminals.
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

    def _topology(self, sw_on: BoolArray, taps: FloatArray) -> _Topology:
        """Factorised matrices for a switch-state and tap combination (cached, SPEC S-05)."""
        key = sw_on.tobytes() + taps.tobytes()
        top = self._lu_cache.get(key)
        if top is not None:
            return top
        g = self.g_base.copy()
        h_sw = np.zeros_like(g)
        if len(self.switches):
            g[self.switches.pos] = self.switches.conductance(sw_on)
            h_sw[self.switches.pos] = self.switches.norton(sw_on)
        rows, cols, vals = [], [], []
        for (b1, b2, y, a0), f in zip(self._xf, taps, strict=True):
            a = a0 * float(f)
            g[b2] = a * a * y
            rows += [b1, b2]
            cols += [b2, b1]
            vals += [-a * y, -a * y]
        nb = len(g)
        Yx = sp.csr_matrix((vals, (rows, cols)), shape=(nb, nb))
        Y = (sp.diags(g) + self._Ycoup + Yx).tocsr()
        G = (self._A @ Y @ self._A.T).tocsc()
        u, kn = self.unknown_nodes, self.known_nodes
        G_uu = G[u][:, u].tocsc()
        try:
            lu = splu(G_uu) if len(u) else None
        except RuntimeError as exc:
            raise TopologyError(
                "ma trận điện dẫn suy biến: có nút nổi hoặc vòng chỉ gồm nguồn"
            ) from exc
        top = _Topology(lu=lu, G_uk=G[u][:, kn].tocsc(), Y=Y, h_sw=h_sw)
        if len(self._lu_cache) >= _LU_CACHE_MAX:
            self._lu_cache.clear()
        self._lu_cache[key] = top
        self.stats.lu_factorizations += 1
        return top

    def fingerprint(self) -> str:
        """SHA-256 of the netlist without event elements, and of the time step; snapshots are
        only valid for the same value."""
        desc = [
            [e.id, e.kind, list(e.nodes), sorted((k, v) for k, v in e.params.items())]
            for e in self.netlist.elements if e.origin != "event"
        ]
        text = json.dumps({"dt": self.dt, "cda": self.cda, "elements": desc}, sort_keys=True)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------- control I/O
    def switch_index(self, device_id: str) -> int:
        try:
            return self._sw_index[device_id]
        except KeyError:
            raise SolverError(f"không có van/khóa '{device_id}'") from None

    def transformer_index(self, xf_id: str) -> int:
        try:
            return self._xf_ids.index(xf_id)
        except ValueError:
            raise SolverError(f"không có MBA '{xf_id}'") from None

    def set_tap(self, st: SolverState, j: int, factor: float) -> None:
        """Change the ratio factor of transformer ``j`` (``a = a0 factor``) in the grid state
        ``st``. The winding-1 current is reset to ``-i2/a`` (ideal-transformer constraint with
        the load current kept); CDA follows. The tap-changer transition is not modelled."""
        if factor == st.taps[j]:
            return
        b1, b2, _, a0 = self._xf[j]
        st.taps[j] = factor
        st.i_b[b1] = -st.i_b[b2] / (a0 * factor)
        if self.cda:
            st.cda_left = 2
        self.markers.append((st.t, self._xf_ids[j], "tap"))

    def command_switch(self, st: SolverState, j: int, close: bool, t: float) -> None:
        """Order switch ``j`` to close or open at ``t`` (opens at current zero if it has
        ``open_at_zero``)."""
        st.dev.cmd_t[j] = t
        st.dev.cmd_on[j] = close

    def fire(self, st: SolverState, j: int, t_on: float, t_off: float) -> None:
        """Set the gate window of thyristor ``j`` (index from :meth:`switch_index`)."""
        if self.switches.dev[j] != DEV_THYRISTOR:
            raise SolverError(f"'{self.switches.ids[j]}' không phải thyristor")
        t_mf = self._misfire.get(j)
        if t_mf is not None and t_on >= t_mf > st.dev.fire_on[j]:
            # misfire: the first window after t_mf is dropped (an empty window marks it used)
            st.dev.fire_on[j] = t_on
            st.dev.fire_off[j] = t_on - 1.0
            self.markers.append((t_on, self.switches.ids[j], "misfire"))
            return
        st.dev.fire_on[j] = t_on
        st.dev.fire_off[j] = t_off

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
        st = SolverState(
            t=0.0, step=0, v=np.zeros(len(self.node_names)), i_b=i_b, v_b=v_b,
            dev=self.switches.initial_state(), cda_left=2 if self.cda else 0,
            hist=self.lines.init_hist(), taps=np.ones(len(self._xf)),
        )
        ns = len(self.switches)
        for j in range(ns):
            while (cmd := self.switches.next_command(j, int(st.dev.sched_idx[j]))) is not None \
                    and cmd[0] <= 0.0:
                mask = np.zeros(ns, dtype=bool)
                mask[j] = True
                for ch in self.switches.apply(0.0, mask, st.dev):
                    self.events.append(SwitchEvent(0.0, ch.id, ch.on))
        return st

    def _history(self, st: SolverState, backward_euler: bool, top: _Topology) -> FloatArray:
        """History terms for the next (half-)step from branch states of ``st``; ``Y`` of the
        present state (saturation segment, tap position) gives the inductor conductances."""
        h = np.zeros_like(st.i_b)
        isl, isc = self._isl, self._isc
        if backward_euler:
            h[isl] = st.i_b[isl]
            h[isc] = -self.g_base[isc] * st.v_b[isc]
        else:
            yv = top.Y @ st.v_b
            h[isl] = st.i_b[isl] + yv[isl]
            h[isc] = -st.i_b[isc] - yv[isc]
        return h

    def _solve(self, st: SolverState, t: float, backward_euler: bool) -> SolverState:
        """Advance ``st`` to time ``t`` with fixed topology; returns the new state."""
        top = self._topology(st.dev.on, st.taps)
        n = len(self.node_names)
        h = self._history(st, backward_euler, top) + top.h_sw
        if len(self.lines):
            self.lines.history(st.hist, st.step, t, h)
        if len(self._vn_pos):
            h[self._vn_pos] = -self.g_base[self._vn_pos] * self._vn_src(t)
        rhs = -(self._A @ h)
        if len(self.isrc):
            j = self._is_src(t)
            rhs_full = np.zeros(n + 1)
            np.add.at(rhs_full, self._is_k, j)
            np.add.at(rhs_full, self._is_m, -j)
            rhs += rhs_full[:n]
        v = np.zeros(n + 1)
        if len(self.known_nodes):
            v[self.known_nodes] = self._known_sign * self._iv_src(t)[self._known_src]
        if top.lu is not None:
            b = rhs[self.unknown_nodes] - top.G_uk @ v[self.known_nodes]
            v[self.unknown_nodes] = top.lu.solve(b)
        if not np.all(np.isfinite(v)):
            raise SolverError(f"nghiệm không hữu hạn tại t = {t:.9g} s")
        v_b = v[self.bk] - v[self.bm]  # v[-1] is the ground slot (always 0)
        i_b = top.Y @ v_b + h
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
        lam = sw.event_fractions(a.t, b.t, a.dev, a.i_b[p], b.i_b[p], a.v_b[p], b.v_b[p])
        lmin = float(np.min(lam))
        return lmin, lam <= lmin + 1e-9

    def _track(self, a: SolverState, b: SolverState) -> None:
        """Mark the instant ``v_AK`` of a turned-off thyristor becomes positive (for gamma)."""
        pend = np.flatnonzero(a.dev.fwd_pending)
        for j in pend:
            p = self.switches.pos[j]
            v0, v1 = a.v_b[p], b.v_b[p]
            if v0 <= 0.0 < v1:
                t = a.t + v0 / (v0 - v1) * (b.t - a.t)
                self.markers.append((t, self.switches.ids[j], "fwd"))
                b.dev.fwd_pending[j] = False

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
                self._track(cur, x)
                changed = self.switches.apply(x.t, mask, x.dev)
                for ch in changed:
                    self.events.append(SwitchEvent(x.t, ch.id, ch.on))
                    if not ch.gated:
                        self.markers.append((x.t, ch.id, "cf"))
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
                    self.lines.push(cur.hist, target_step, cur.v_b, cur.i_b)
                    return cur
                continue
            if nxt.t > T + tol:  # overshoot: interpolate back onto the grid
                self.stats.interpolations += 1
                out = self._interp(cur, nxt, (T - cur.t) / (nxt.t - cur.t))
                out.cda_left = nxt.cda_left
            else:
                out = nxt
            self._track(cur, out)
            if abs(out.t - T) <= tol:
                out.t, out.step = T, target_step
                self.lines.push(out.hist, target_step, out.v_b, out.i_b)
                return out
            cur = out

    # ---------------------------------------------------------------- signals
    def signal_layout(self) -> list[tuple[str, str]]:
        """``(name, unit)`` of every recordable signal, in :meth:`probe` order."""
        out = [(f"{n}.V", "V") for n in self.node_names]
        out += [(f"{nm}.I", "A") for nm in self.branch_names]
        out += [(f"{nm}.V", "V") for nm in self.branch_names]
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
                st.dev.on.astype(float),
            ]
        )
        return out

    def ideal_source_currents(self, st: SolverState) -> FloatArray:
        """Current delivered by each ideal voltage source (out of its positive terminal)."""
        inj = np.append(self._A @ st.i_b, 0.0)  # net current leaving each node via branches
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
