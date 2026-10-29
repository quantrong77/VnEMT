"""Transient fault ride-through metrics of an LCC link (SPEC 7.4 "Chỉ số đánh giá").

Computed from a result of a system-level case (signal names of
:mod:`vnemt.systems.builder`):

=================  ==========================================================================
cf_tq              valve re-conductions before ``t_q`` (solver markers ``cf``, criterion 1)
cf_gamma           commutations with gamma < ``gamma_cf_deg`` or not completed before the
                   commutating voltage reversed (inverter control, criterion 2)
cf_episodes        commutation-failure episodes: failure instants of both criteria grouped
                   when closer than ``episode_gap_s`` (default two cycles, 40 ms)
recovery_ms        time after fault clearing until the DC power at the rectifier stays at or
                   above 90 % of its pre-fault mean (nan: not recovered within the record)
Id_max_pu          peak DC current after the fault (rectifier smoothing reactor)
Ud_max_pu          peak absolute DC voltage at the rectifier terminal
Uac_min_pu,        smallest / largest one-cycle RMS of the inverter AC bus phase voltages after
Uac_max_pu         the fault, pu of the rated phase voltage
=================  ==========================================================================

Pass/fail compares with user criteria only (``recovery_90pct_ms``, ``max_cf`` on episodes,
``max_Id_pu``, ``max_Ud_pu``, ``min_Uac_pu``, ``max_Uac_pu``); there are no default thresholds.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np

from vnemt.analysis.compare import recovery_time
from vnemt.results import Result

SIGNALS = ("{r}_DC.V", "{r}_Ls.I", "{i}_CTRL.cf_count", "{ac}_a.V", "{ac}_b.V", "{ac}_c.V")


def required_signals(rec: str = "REC", inv: str = "INV", inv_ac: str = "ACI") -> list[str]:
    return [s.format(r=rec, i=inv, ac=inv_ac) for s in SIGNALS]


# criterion -> (metric, "max" | "min")
_CHECKS = {"recovery_90pct_ms": ("recovery_ms", "max"), "max_cf": ("cf_episodes", "max"),
           "max_Id_pu": ("Id_max_pu", "max"), "max_Ud_pu": ("Ud_max_pu", "max"),
           "min_Uac_pu": ("Uac_min_pu", "min"), "max_Uac_pu": ("Uac_max_pu", "max")}


def _ok(m: Mapping[str, Any], criterion: str, limit: float) -> bool:
    key, kind = _CHECKS[criterion]
    v = float(m[key])
    if math.isnan(v):
        return False  # e.g. not recovered within the record
    return v <= limit if kind == "max" else v >= limit


def _episodes(times: list[float], gap: float) -> int:
    n, last = 0, -math.inf
    for t in sorted(times):
        if t - last > gap:
            n += 1
        last = t
    return n


def _rms_cycle(t: np.ndarray, x: np.ndarray, f: float) -> np.ndarray:
    n = max(1, round(1.0 / f / (t[1] - t[0])))
    c = np.cumsum(np.concatenate([[0.0], x * x]))
    out: np.ndarray = np.sqrt((c[n:] - c[:-n]) / n)
    return out


def lcc_frt_metrics(res: Result, t_fault: float, t_clear: float, I_base: float, U_base: float,
                    U_ac_kV: float, f_Hz: float = 50.0, rec: str = "REC", inv: str = "INV",
                    inv_ac: str = "ACI", pre_window: tuple[float, float] | None = None,
                    criteria: Mapping[str, Any] | None = None,
                    episode_gap_s: float = 0.04) -> dict[str, Any]:
    t = res.time
    after = t >= t_fault
    valves = (f"{inv}_Y", f"{inv}_D")
    tq_times = [m[0] for m in res.markers
                if m[2] == "cf" and m[1].startswith(valves) and m[0] >= t_fault]
    cfc = res[f"{inv}_CTRL.cf_count"]
    base_count = float(np.interp(t_fault, t, cfc))
    inc = np.flatnonzero(np.diff(cfc) > 0) + 1
    g_times = [float(t[k]) for k in inc if t[k] >= t_fault]
    p = res[f"{rec}_DC.V"] * res[f"{rec}_Ls.I"]
    pre = pre_window or (max(t[0], t_fault - 0.05), t_fault)
    rec_s = recovery_time(t, p, t_clear, pre) if t[-1] > t_clear else math.nan
    vn = U_ac_kV * 1e3 / math.sqrt(3.0)
    rms = [_rms_cycle(t[after], res[f"{inv_ac}_{ph}.V"][after], f_Hz) / vn for ph in "abc"]
    m: dict[str, Any] = {
        "cf_tq": len(tq_times),
        "cf_gamma": int(cfc[-1] - base_count),
        "cf_episodes": _episodes(tq_times + g_times, episode_gap_s),
        "recovery_ms": 1e3 * rec_s,
        "Id_max_pu": float(np.max(np.abs(res[f"{rec}_Ls.I"][after]))) / I_base,
        "Ud_max_pu": float(np.max(np.abs(res[f"{rec}_DC.V"][after]))) / U_base,
        "Uac_min_pu": float(min(np.min(r) for r in rms)),
        "Uac_max_pu": float(max(np.max(r) for r in rms)),
    }
    failed = [k for k, v in (criteria or {}).items() if k in _CHECKS and not _ok(m, k, float(v))]
    m["pass"] = None if not criteria else not failed
    m["failed"] = ",".join(failed)
    return m
