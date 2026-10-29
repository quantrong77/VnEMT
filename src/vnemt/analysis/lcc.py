"""Measured firing, overlap and extinction angles of a six-pulse bridge (SPEC F1-L04, F1-L05).

For every commutation (incoming valve ``k``, outgoing valve ``k - 2`` of the same group):

* ``alpha``: from the natural commutation instant (rising zero of the commutating line
  voltage, linearly interpolated in the recorded waveform) to the turn-on of valve ``k``;
* ``mu``: from the turn-on of valve ``k`` to the turn-off of the outgoing valve;
* ``gamma``: from the turn-off of the outgoing valve to the instant its anode-cathode voltage
  becomes positive again (solver marker ``fwd``), i.e. the actual extinction angle.

Angles are in degrees at frequency ``f``. Commutation failures are counted from the solver
markers ``cf`` (re-conduction before ``t_q`` without gate pulse).

Commutating line voltages for valves 1..6 in firing order: ``v_ac, v_bc, v_ba, v_ca, v_cb,
v_ab`` (see :mod:`vnemt.power_electronics.lcc_bridge`).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from vnemt.results import Result

_PAIRS = ((0, 2), (1, 2), (1, 0), (2, 0), (2, 1), (0, 1))


@dataclass
class BridgeAngles:
    """Per-commutation measurements, ordered in time."""

    t: NDArray[np.float64]  # turn-on instant of the incoming valve
    valve: NDArray[np.int64]  # incoming valve number 1..6
    alpha: NDArray[np.float64]
    mu: NDArray[np.float64]
    gamma: NDArray[np.float64]  # of the outgoing valve (nan if not yet measured)
    n_cf: int


def _rising_zeros(t: NDArray[np.float64], v: NDArray[np.float64]) -> NDArray[np.float64]:
    i = np.flatnonzero((v[:-1] < 0.0) & (v[1:] >= 0.0))
    return t[i] - v[i] * (t[i + 1] - t[i]) / (v[i + 1] - v[i])


def measure_bridge(res: Result, valves: list[str], emf: tuple[str, str, str],
                   f: float) -> BridgeAngles:
    """Measure alpha, mu, gamma of a six-pulse bridge from a result.

    ``valves`` are the ids in firing order; ``emf`` are the recorded commutating phase
    voltages ``(a, b, c)`` (record them at full rate for best accuracy).
    """
    deg = 360.0 * f
    v = [res[s] for s in emf]
    on = {vid: np.array([e[0] for e in res.events if e[1] == vid and e[2]]) for vid in valves}
    off = {vid: np.array([e[0] for e in res.events if e[1] == vid and not e[2]])
           for vid in valves}
    fwd = {vid: np.array([m[0] for m in res.markers if m[1] == vid and m[2] == "fwd"])
           for vid in valves}
    rows: list[tuple[float, int, float, float, float]] = []
    for k, vid in enumerate(valves):
        a, b = _PAIRS[k]
        nat = _rising_zeros(res.time, v[a] - v[b])
        out = valves[(k - 2) % 6]
        for t_on in on[vid]:
            before = nat[nat <= t_on + 1e-7]
            if not len(before) or t_on - before[-1] > 1.0 / f:
                continue
            alpha = deg * (t_on - before[-1])
            later_off = off[out][off[out] > t_on]
            if not len(later_off):
                continue
            t_off = later_off[0]
            mu = deg * (t_off - t_on)
            later_fwd = fwd[out][fwd[out] > t_off]
            gamma = deg * (later_fwd[0] - t_off) if len(later_fwd) else np.nan
            rows.append((t_on, k + 1, alpha, mu, gamma))
    rows.sort()
    arr = np.array(rows, dtype=float).reshape(-1, 5)
    n_cf = sum(1 for m in res.markers if m[1] in valves and m[2] == "cf")
    return BridgeAngles(t=arr[:, 0], valve=arr[:, 1].astype(np.int64), alpha=arr[:, 2],
                        mu=arr[:, 3], gamma=arr[:, 4], n_cf=n_cf)
