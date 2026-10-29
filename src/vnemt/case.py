"""High-level case API: ``vnemt.load(path).run()``."""

from __future__ import annotations

import datetime as dt
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np
import scipy

from vnemt import __version__
from vnemt.core.simulate import simulate
from vnemt.core.snapshot import load_snapshot
from vnemt.core.solver import EmtSolver
from vnemt.errors import CaseError
from vnemt.io.case_loader import CaseFile, load_case, parse_case
from vnemt.model.netlist import Netlist, build_netlist
from vnemt.results import Result

# Sections accepted by the schema but not yet simulated, with the milestone that adds them.
_PENDING_SECTIONS = {
    "ac_systems": "M2",
    "converter_stations": "M2",
    "dc_network": "M4",
    "events": "M3",
}
_SUPPORTED_FORMATS = ("hdf5", "csv")


class Case:
    """A validated case ready to run."""

    def __init__(self, file: CaseFile) -> None:
        self.file = file

    @property
    def data(self) -> dict[str, Any]:
        return self.file.data

    @property
    def name(self) -> str:
        return self.file.name

    @property
    def solver_params(self) -> dict[str, Any]:
        s = dict(self.data["case"]["solver"])
        s.setdefault("method", "trapezoidal")
        s.setdefault("cda", True)
        return s

    def _check_supported(self) -> None:
        src = str(self.file.path) if self.file.path else None
        for key, milestone in _PENDING_SECTIONS.items():
            if self.data.get(key):
                raise CaseError(
                    f"mục '{key}' chưa được mô phỏng trong phiên bản này (dự kiến mốc "
                    f"{milestone}); hiện chỉ chạy được mục 'circuit'",
                    path=key, source=src,
                )
        if "circuit" not in self.data:
            raise CaseError("case không có mục 'circuit' để mô phỏng", source=src)
        mode = self.data["case"].get("init", {}).get("mode", "zero")
        if mode == "loadflow":
            raise CaseError(
                "chế độ khởi tạo 'loadflow' chưa triển khai (cần trào lưu AC/DC, F6-07); "
                "dùng 'zero' hoặc 'snapshot'",
                path="case.init.mode", source=src,
            )
        bad = [f for f in self.formats if f not in _SUPPORTED_FORMATS]
        if bad:
            raise CaseError(
                f"định dạng {bad} chưa hỗ trợ (COMTRADE, PSCAD .out, .mat: mốc M3); "
                f"hiện có {list(_SUPPORTED_FORMATS)}",
                path="outputs.format", source=src,
            )

    @property
    def formats(self) -> list[str]:
        return list(self.data.get("outputs", {}).get("format", ["hdf5"]))

    def netlist(self) -> Netlist:
        return build_netlist(self.data)

    def resolve(self, path: str) -> Path:
        """Resolve a path given in the case relative to the case file's directory."""
        p = Path(path)
        if p.is_absolute() or self.file.path is None:
            return p
        return self.file.path.parent / p

    def run(self) -> Result:
        """Simulate the case and return the result with provenance metadata."""
        self._check_supported()
        sp = self.solver_params
        solver = EmtSolver(self.netlist(), dt=sp["dt_us"] * 1e-6, cda=bool(sp["cda"]))
        out = self.data.get("outputs", {})
        sig = out.get("signals", "all")
        init = self.data["case"].get("init", {})
        start = None
        if init.get("mode") == "snapshot":
            start = load_snapshot(solver, self.resolve(init["file"]))
        snap = self.data["case"].get("snapshot")
        res = simulate(
            solver,
            t_end=float(sp["t_end_s"]),
            signals=None if sig == "all" else list(sig),
            decimate=int(out.get("decimate", 1)),
            start=start,
            snapshot=(float(snap["t_s"]), self.resolve(snap["file"])) if snap else None,
        )
        res.meta = self.provenance()
        res.meta["lu_factorizations"] = solver.stats.lu_factorizations
        res.meta["switching_events"] = solver.stats.events
        if start is not None:
            res.meta["init_snapshot"] = str(self.resolve(init["file"]))
        return res

    def provenance(self) -> dict[str, Any]:
        """Metadata stored with every result (SPEC Q-03)."""
        return {
            "vnemt_version": __version__,
            "python_version": sys.version.split()[0],
            "numpy_version": np.__version__,
            "scipy_version": scipy.__version__,
            "platform": platform.platform(),
            "case_name": self.name,
            "case_file": str(self.file.path) if self.file.path else "",
            "case_sha256": self.file.sha256,
            "solver": self.solver_params,
            "base": self.data.get("base", {}),
            "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        }


def load(path: str | Path) -> Case:
    """Load and validate a case file."""
    return Case(load_case(path))


def loads(text: str) -> Case:
    """Load and validate a case from YAML text."""
    return Case(parse_case(text))
