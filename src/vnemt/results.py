"""Simulation result container (SPEC-v0.1 section 9.2)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from vnemt.errors import VnEMTError

EXPORT_FORMATS = ("hdf5", "csv", "comtrade", "pscad_out", "mat")


@dataclass
class Result:
    """Recorded waveforms plus provenance metadata (SPEC Q-03)."""

    time: NDArray[np.float64]
    signals: dict[str, NDArray[np.float64]]
    units: dict[str, str]
    meta: dict[str, Any] = field(default_factory=dict)
    events: list[tuple[float, str, bool]] = field(default_factory=list)
    """Switching events ``(t, device id, new conduction state)``."""
    markers: list[tuple[float, str, str]] = field(default_factory=list)
    """Valve markers ``(t, device id, kind)``: ``fwd`` = forward voltage reapplied after
    turn-off (end of the extinction interval), ``cf`` = re-conduction without gate pulse."""

    def __getitem__(self, name: str) -> NDArray[np.float64]:
        try:
            return self.signals[name]
        except KeyError:
            raise VnEMTError(f"kết quả không có tín hiệu '{name}'") from None

    @property
    def names(self) -> list[str]:
        return list(self.signals)

    def export(self, path: str | Path, format: str | None = None, **options: Any) -> Path:
        """Write the result; ``format`` defaults to the file extension.

        Formats: ``hdf5`` (.h5), ``csv``, ``comtrade`` (.cfg; options ``rev`` 1999/2013,
        ``fmt`` ASCII/BINARY/BINARY32/FLOAT32), ``pscad_out`` (.inf/.out; option ``run``),
        ``mat``.
        """
        p = Path(path)
        by_ext = {".h5": "hdf5", ".hdf5": "hdf5", ".csv": "csv", ".cfg": "comtrade",
                  ".inf": "pscad_out", ".out": "pscad_out", ".mat": "mat"}
        fmt = format or by_ext.get(p.suffix.lower())
        if fmt == "hdf5":
            from vnemt.io.hdf5 import write_result

            return write_result(self, p)
        if fmt == "csv":
            from vnemt.io.csvfile import write_csv

            return write_csv(self, p)
        if fmt == "comtrade":
            from vnemt.io.comtrade import write_comtrade

            return write_comtrade(self, p, **options)
        if fmt == "pscad_out":
            from vnemt.io.pscad import write_pscad_out

            return write_pscad_out(self, p, **options)
        if fmt == "mat":
            from vnemt.io.matfile import write_mat

            return write_mat(self, p)
        raise VnEMTError(
            f"định dạng xuất '{fmt or p.suffix}' chưa hỗ trợ; hiện có: {', '.join(EXPORT_FORMATS)}"
        )

    def plot(self, names: Sequence[str] | None = None, path: str | Path | None = None) -> Any:
        """Plot signals versus time with Matplotlib; save to ``path`` if given."""
        import matplotlib

        if path is not None:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        names = list(names) if names is not None else self.names
        fig, axes = plt.subplots(len(names), 1, sharex=True, squeeze=False,
                                 figsize=(9, 2.2 * len(names) + 0.6))
        for ax, name in zip(axes[:, 0], names, strict=True):
            ax.plot(self.time, self[name], lw=1.0)
            ax.set_ylabel(f"{name} [{self.units.get(name, '')}]")
            ax.grid(True, alpha=0.3)
        axes[-1, 0].set_xlabel("t [s]")
        fig.tight_layout()
        if path is not None:
            fig.savefig(path, dpi=120)
            plt.close(fig)
        return fig
