"""Constant-parameter (Bergeron) transmission lines, single- and multi-conductor (SPEC 6,
F2-06).

Element ``LINE`` with ``nodes = (k_1..k_N, m_1..m_N)`` and per-km parameters ``L_H_per_km``,
``C_F_per_km`` (N x N, row-major tuples, or scalars for N = 1), ``R_ohm_per_km`` (scalar or one
value per conductor) and ``length_km``.

Modal decomposition: an orthonormal ``T`` that diagonalises ``L'`` and ``C'`` simultaneously
(symmetric or transposed lines; checked, otherwise an error is raised). Phase and mode
quantities: ``v_mode = T^T v``, ``i = T i_mode``. Each mode ``j`` is a lossless line
(``Zc = sqrt(L_j/C_j)``, ``tau = length sqrt(L_j C_j)``) with its total resistance ``R_j``
lumped as R/4 - R/2 - R/4 (Dommel, *EMTP Theory Book*, 2nd ed., section 4.2.3)::

    Z = Zc + R/4,  h = (Zc - R/4) / (Zc + R/4)
    i_km(t) = v_k(t)/Z + I_k
    I_k = -(1 + h)/2 [v_m(t - tau)/Z + h i_mk(t - tau)] - (1 - h)/2 [v_k(t - tau)/Z + h i_km(t - tau)]

and symmetrically at end ``m``. Modal resistance is the diagonal of ``T^T diag(R') T``
(coupling of unequal conductor resistances is neglected).

In the solver every conductor end is a branch from its node to ground with the phase-domain
admittance ``T diag(1/Z) T^T`` (a coupled branch group) and the history current ``T I``.
Grid-point samples of ``v`` and ``i`` at both ends are kept in a ring buffer inside the solver
state (snapshots stay exact); values at ``t - tau`` are interpolated linearly between grid
samples, so off-grid sub-steps (switching interpolation, CDA) are supported. ``tau >= dt`` is
required.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from vnemt.errors import TopologyError
from vnemt.model.netlist import Element

FloatArray = NDArray[np.float64]


def _matrix(el: Element, key: str, n: int) -> FloatArray:
    v = el.params.get(key)
    if v is None:
        raise TopologyError(f"đường dây '{el.id}': thiếu tham số {key}")
    a = np.atleast_1d(np.asarray(v, dtype=float))
    if a.size == 1 and n == 1:
        return a.reshape(1, 1)
    if a.size != n * n:
        raise TopologyError(f"đường dây '{el.id}': {key} cần {n}x{n} = {n * n} giá trị")
    m = a.reshape(n, n)
    if not np.allclose(m, m.T, rtol=1e-12, atol=0.0):
        raise TopologyError(f"đường dây '{el.id}': {key} phải đối xứng")
    return m


@dataclass
class _Line:
    id: str
    n: int
    T: FloatArray  # N x N orthonormal
    Z: FloatArray  # modal surge impedance incl. R/4
    hc: FloatArray  # modal loss factor h
    tau: FloatArray  # modal travel times
    bk: list[int]  # branch index of the k-end conductors
    bm: list[int]  # branch index of the m-end conductors
    nbuf: int

    @property
    def key(self) -> str:
        return f"line:{self.id}"


def modal_parameters(el: Element) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    """``(T, Zc, tau, R_mode)`` of a line element."""
    if len(el.nodes) % 2:
        raise TopologyError(f"đường dây '{el.id}': số nút phải chẵn (k_1..k_N, m_1..m_N)")
    n = len(el.nodes) // 2
    length = el.p("length_km")
    if length <= 0.0:
        raise TopologyError(f"đường dây '{el.id}': length_km phải > 0")
    lm = _matrix(el, "L_H_per_km", n)
    cm = _matrix(el, "C_F_per_km", n)
    r = np.broadcast_to(np.atleast_1d(np.asarray(el.params.get("R_ohm_per_km", 0.0), float)),
                        (n,))
    # a generic combination has distinct eigenvalues when L' and C' commute
    k = np.trace(lm) / np.trace(cm) * (math.sqrt(5.0) - 1.0)
    _, T = np.linalg.eigh(lm + k * cm)
    lmod, cmod = T.T @ lm @ T, T.T @ cm @ T
    off = max(np.max(np.abs(lmod - np.diag(np.diag(lmod)))) / np.max(np.abs(lm)),
              np.max(np.abs(cmod - np.diag(np.diag(cmod)))) / np.max(np.abs(cm)))
    if off > 1e-9:
        raise TopologyError(f"đường dây '{el.id}': L' và C' không chéo hóa đồng thời được bằng "
                            "biến đổi mode thực (đường dây không đối xứng/không hoán vị)")
    ld, cd = np.diag(lmod), np.diag(cmod)
    if np.any(ld <= 0.0) or np.any(cd <= 0.0):
        raise TopologyError(f"đường dây '{el.id}': L' và C' phải xác định dương")
    zc = np.sqrt(ld / cd)
    tau = length * np.sqrt(ld * cd)
    rmod = length * np.diag(T.T @ np.diag(r) @ T)
    return T, zc, tau, rmod


class LineSet:
    """All Bergeron lines of a netlist."""

    def __init__(self, dt: float) -> None:
        self.dt = dt
        self.lines: list[_Line] = []

    def add(self, el: Element, add_branch: object, coup: list[tuple[int, int, float]]) -> None:
        T, zc, tau, rmod = modal_parameters(el)
        if np.min(tau) < self.dt:
            raise TopologyError(
                f"đường dây '{el.id}': thời gian truyền {np.min(tau) * 1e6:.1f} µs nhỏ hơn bước "
                f"thời gian {self.dt * 1e6:.1f} µs; hãy dùng mô hình π hoặc giảm Δt")
        n = len(zc)
        z = zc + rmod / 4.0
        hc = (zc - rmod / 4.0) / z
        y = T @ np.diag(1.0 / z) @ T.T
        bk: list[int] = []
        bm: list[int] = []
        for end, out in (("k", bk), ("m", bm)):
            off = 0 if end == "k" else n
            for c in range(n):
                out.append(add_branch(el, y[c, c], el.nodes[off + c], "gnd",  # type: ignore[operator]
                                      f"{el.id}.{end}{c + 1}"))
            for a in range(n):
                for b in range(n):
                    if a != b:
                        coup.append((out[a], out[b], float(y[a, b])))
        nbuf = math.ceil(float(np.max(tau)) / self.dt) + 3
        self.lines.append(_Line(el.id, n, T, z, hc, tau, bk, bm, nbuf))

    def __len__(self) -> int:
        return len(self.lines)

    def init_hist(self) -> dict[str, FloatArray]:
        return {ln.key: np.zeros((ln.nbuf, 4 * ln.n)) for ln in self.lines}

    def push(self, hist: dict[str, FloatArray], step: int, v_b: FloatArray,
             i_b: FloatArray) -> None:
        """Store the grid-point sample ``step``: rows ``[v_k, v_m, i_k, i_m]``."""
        for ln in self.lines:
            hist[ln.key][step % ln.nbuf] = np.concatenate(
                [v_b[ln.bk], v_b[ln.bm], i_b[ln.bk], i_b[ln.bm]])

    def _sample(self, buf: FloatArray, ln: _Line, last: int, t: float) -> FloatArray:
        if t <= 0.0:
            return np.zeros(4 * ln.n)  # the line starts de-energised
        s = t / self.dt
        s0 = math.floor(s + 1e-9)
        if s0 + 1 > last:
            if s0 == last and s - s0 < 1e-6:
                exact: FloatArray = buf[last % ln.nbuf]
                return exact
            raise TopologyError(f"đường dây '{ln.id}': lịch sử chưa có tại t = {t:.9g} s")
        if last - s0 >= ln.nbuf:
            raise TopologyError(f"đường dây '{ln.id}': bộ đệm lịch sử quá ngắn")
        frac = s - s0
        out: FloatArray = (1.0 - frac) * buf[s0 % ln.nbuf] + frac * buf[(s0 + 1) % ln.nbuf]
        return out

    def history(self, hist: dict[str, FloatArray], last_step: int, t: float,
                h: FloatArray) -> None:
        """Write the history currents of every line branch for a solution at time ``t``."""
        for ln in self.lines:
            buf, n, T = hist[ln.key], ln.n, ln.T
            hk, hm = np.zeros(n), np.zeros(n)
            for j in range(n):
                row = self._sample(buf, ln, last_step, t - float(ln.tau[j]))
                vk, vm = T[:, j] @ row[:n], T[:, j] @ row[n:2 * n]
                ik, im = T[:, j] @ row[2 * n:3 * n], T[:, j] @ row[3 * n:]
                z, hc = float(ln.Z[j]), float(ln.hc[j])
                a, b = 0.5 * (1.0 + hc), 0.5 * (1.0 - hc)
                hk[j] = -a * (vm / z + hc * im) - b * (vk / z + hc * ik)
                hm[j] = -a * (vk / z + hc * ik) - b * (vm / z + hc * im)
            h[ln.bk] = T @ hk
            h[ln.bm] = T @ hm
