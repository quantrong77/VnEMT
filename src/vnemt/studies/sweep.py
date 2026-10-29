"""Multiple run from a steady-state snapshot (SPEC S-10, TC-09).

Sweep file::

    sweep:
      snapshot_t_s: 1.0          # base case (without events) is run once up to here
      t_end_s: 1.6               # end time of every run
      parameters:                # Cartesian product; keys are dotted paths into the case
        events.0.depth_pct: [10, 20, 30]
        converter_stations.1.control.cfprev: [false, true]
      save_results: false        # also write each run to <out>/runs/run_###.h5

Each run starts from the snapshot (event elements are added in their initial state, see
:mod:`vnemt.systems.events`), is simulated in its own process (``spawn``, works on Windows)
and reduced to the FRT metrics of :mod:`vnemt.analysis.frt`. Rows are returned in the order of
the Cartesian product, so the table does not depend on the number of workers (Q-02).
"""

from __future__ import annotations

import copy
import csv
import itertools
import math
import multiprocessing as mp
import os
import sys
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any

from vnemt.errors import CaseError, VnEMTError
from vnemt.io.case_loader import CaseFile, load_case, load_yaml

_FAULT_TYPES = ("ac_fault", "ac_dip", "dc_fault", "valve_short", "misfire")


def set_path(data: Any, path: str, value: Any) -> None:
    """Set ``data[a][b][0]...`` from the dotted path ``a.b.0``."""
    keys = path.split(".")
    obj = data
    try:
        for k in keys[:-1]:
            obj = obj[int(k)] if isinstance(obj, list) else obj[k]
        last = keys[-1]
        if isinstance(obj, list):
            obj[int(last)] = value
        else:
            obj[last] = value
    except (KeyError, IndexError, ValueError, TypeError):
        raise CaseError(f"đường dẫn tham số '{path}' không tồn tại trong case",
                        path="sweep.parameters") from None


def load_sweep(path: str | Path) -> dict[str, Any]:
    raw = load_yaml(Path(path).read_text(encoding="utf-8"))
    sw = raw.get("sweep") if isinstance(raw, dict) else None
    if not isinstance(sw, dict) or not isinstance(sw.get("parameters"), dict):
        raise CaseError("file quét cần mục 'sweep' với 'parameters' (khóa: danh sách giá trị)",
                        source=str(path))
    for k, v in sw["parameters"].items():
        if not isinstance(v, list) or not v:
            raise CaseError(f"tham số '{k}' phải là danh sách khác rỗng", source=str(path))
    if "snapshot_t_s" not in sw or "t_end_s" not in sw:
        raise CaseError("file quét cần 'snapshot_t_s' và 't_end_s'", source=str(path))
    return sw


def _metrics_context(data: Mapping[str, Any]) -> dict[str, Any]:
    from vnemt.model.grid import grid_from_case

    grid = grid_from_case(data)
    if grid.base is None or not grid.stations:
        raise CaseError("chỉ số FRT cần hệ HVDC (converter_stations, base)")
    rec = next(s for s in grid.stations.values() if s.role == "rectifier")
    inv = next(s for s in grid.stations.values() if s.role == "inverter")
    ac = grid.ac_systems[inv.ac_system]
    return {"rec": rec.id, "inv": inv.id, "inv_ac": ac.id, "U_ac_kV": ac.U_kV, "f_Hz": ac.f_Hz,
            "I_base": grid.base.I_A, "U_base": grid.base.U_dc_kV * 1e3}


def _run_one(args: tuple[int, dict[str, Any], str, str | None]) -> dict[str, Any]:
    from vnemt.analysis.frt import lcc_frt_metrics, required_signals
    from vnemt.case import Case

    k, data, snapshot, save = args
    ctx = _metrics_context(data)
    data["case"]["init"] = {"mode": "snapshot", "file": snapshot}
    data["case"].pop("snapshot", None)
    data["outputs"] = {"signals": required_signals(ctx["rec"], ctx["inv"], ctx["inv_ac"]),
                       "format": ["hdf5"]}
    res = Case(CaseFile(data=data, path=None, sha256="")).run()
    if save:
        res.export(Path(save) / f"run_{k:03d}.h5")
    faults = [e for e in data.get("events", []) if e["type"] in _FAULT_TYPES]
    if not faults:
        raise CaseError("mỗi lần chạy cần ít nhất một sự kiện sự cố", path="events")
    t_fault = min(float(e["t_s"]) for e in faults)
    t_clear = max(float(e["t_s"]) + float(e.get("duration_ms", 0.0)) * 1e-3 for e in faults)
    return lcc_frt_metrics(res, t_fault, t_clear, ctx["I_base"], ctx["U_base"], ctx["U_ac_kV"],
                           ctx["f_Hz"], ctx["rec"], ctx["inv"], ctx["inv_ac"],
                           criteria=data.get("criteria"))


def run_sweep(case_path: str | Path, sweep: Mapping[str, Any], out_dir: str | Path,
              workers: int | None = None) -> list[dict[str, Any]]:
    """Run every parameter combination from one snapshot; returns the metrics table."""
    case = load_case(case_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    base_dir = case.path.parent if case.path else Path.cwd()

    snap = out / "snapshot.h5"
    base = copy.deepcopy(case.data)
    base.pop("events", None)
    base["case"]["solver"]["t_end_s"] = float(sweep["snapshot_t_s"])
    base["case"]["snapshot"] = {"t_s": float(sweep["snapshot_t_s"]), "file": str(snap.resolve())}
    base["case"].pop("init", None)
    base["outputs"] = {"signals": [], "format": ["hdf5"], "decimate": 1000}
    from vnemt.case import Case

    Case(CaseFile(data=base, path=None, sha256="")).run()

    names = list(sweep["parameters"])
    combos = list(itertools.product(*(sweep["parameters"][n] for n in names)))
    save = str((out / "runs").resolve()) if sweep.get("save_results") else None
    jobs = []
    for k, values in enumerate(combos):
        d = copy.deepcopy(case.data)
        d["case"]["solver"]["t_end_s"] = float(sweep["t_end_s"])
        for n, v in zip(names, values, strict=True):
            set_path(d, n, v)
        jobs.append((k, d, str(snap.resolve()), save))
    n_workers = workers or min(len(jobs), os.cpu_count() or 1, MAX_DEFAULT_WORKERS)
    cwd = os.getcwd()
    os.chdir(base_dir)  # relative paths in the case resolve like a normal run
    try:
        if n_workers <= 1:
            rows = [_run_one(j) for j in jobs]
        else:
            rows = _parallel(jobs, n_workers)
    finally:
        os.chdir(cwd)
    table = [{"run": k, **dict(zip(names, vals, strict=True)), **row}
             for k, (vals, row) in enumerate(zip(combos, rows, strict=True))]
    write_table(table, out / "sweep.csv")
    (out / "sweep.md").write_text(to_markdown(table), encoding="utf-8")
    return table


_THREAD_VARS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
MAX_DEFAULT_WORKERS = 6  # each process reserves several hundred MB of commit on Windows


def _parallel(jobs: list[tuple[int, dict[str, Any], str, str | None]],
              n_workers: int) -> list[dict[str, Any]]:
    """Run jobs in spawned processes with one BLAS thread each (otherwise every process starts
    one BLAS thread per core and memory runs out with many workers)."""
    saved = {k: os.environ.get(k) for k in _THREAD_VARS}
    os.environ.update({k: "1" for k in _THREAD_VARS})
    try:
        while True:
            try:
                with ProcessPoolExecutor(n_workers, mp_context=mp.get_context("spawn")) as ex:
                    return list(ex.map(_run_one, jobs))
            except BrokenProcessPool as exc:
                if n_workers <= 1:
                    raise VnEMTError("tiến trình chạy bị dừng đột ngột (thiếu bộ nhớ?)") from exc
                # usually out of memory (commit limit): results do not depend on the number
                # of processes, so the whole sweep is simply repeated with fewer of them
                n_workers = max(1, n_workers // 2)
                print(f"Cảnh báo: tiến trình song song bị dừng đột ngột; chạy lại với "
                      f"{n_workers} tiến trình", file=sys.stderr)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def write_table(rows: Sequence[Mapping[str, Any]], path: Path) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else [])
        w.writeheader()
        w.writerows(rows)
    return path


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return "–" if math.isnan(v) else f"{v:.4g}"
    return str(v)


def to_markdown(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return ""
    cols = list(rows[0])
    lines = ["| " + " | ".join(cols) + " |", "|" + " --- |" * len(cols)]
    lines += ["| " + " | ".join(_fmt(r[c]) for c in cols) + " |" for r in rows]
    return "\n".join(lines) + "\n"
