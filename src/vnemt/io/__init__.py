"""Input/output: case files, schema validation, result formats (SPEC 9, IO-01...IO-07)."""

from __future__ import annotations

from pathlib import Path

from vnemt.errors import VnEMTError
from vnemt.results import Result


def read(path: str | Path) -> Result:
    """Read a result file; the format follows the extension.

    ``.h5``/``.hdf5`` (VnEMT), ``.cfg``/``.dat`` (COMTRADE), ``.inf``/``.out`` (PSCAD),
    ``.psout`` (PSCAD V5, needs ``mhi-psout``), ``.mat``, ``.csv``.
    """
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".h5", ".hdf5"):
        from vnemt.io.hdf5 import read_result

        return read_result(p)
    if ext in (".cfg", ".dat"):
        from vnemt.io.comtrade import read_comtrade

        return read_comtrade(p)
    if ext in (".inf", ".out"):
        from vnemt.io.pscad import read_pscad_out

        if ext == ".out":  # <name>_01.out or <name>_r01_01.out -> <name>[_r01].inf
            stem = p.stem.rsplit("_", 1)[0]
            p = p.with_name(stem + ".inf")
        return read_pscad_out(p)
    if ext == ".psout":
        from vnemt.io.pscad import read_psout

        return read_psout(p)
    if ext == ".mat":
        from vnemt.io.matfile import read_mat

        return read_mat(p)
    if ext == ".csv":
        from vnemt.io.csvfile import read_csv

        return read_csv(p)
    raise VnEMTError(f"không nhận diện được định dạng kết quả '{p.suffix}' của '{p}'")
