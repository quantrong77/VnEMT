"""Snapshot save/restore (SPEC S-08c, S-09): continued run equals uninterrupted run."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import vnemt
from vnemt.core import simulate
from vnemt.core.snapshot import load_snapshot, save_snapshot
from vnemt.errors import VnEMTError

from .test_switching import bridge


@pytest.mark.req("S-09")
def test_continue_from_snapshot_matches_continuous_run(tmp_path: Path) -> None:
    names = ["P.V", "LD.I", "D1.I", "La.I"]
    full = simulate(bridge(20e-6), 0.1, names)

    snap = tmp_path / "s.h5"
    first = simulate(bridge(20e-6), 0.05, names, snapshot=(0.05, snap))
    s2 = bridge(20e-6)
    rest = simulate(s2, 0.1, names, start=load_snapshot(s2, snap))

    assert rest.time[0] == pytest.approx(0.05)
    k0 = len(first.time) - 1
    np.testing.assert_array_equal(full.time[k0:], rest.time)
    for n in names:
        scale = np.max(np.abs(full[n]))
        assert np.max(np.abs(full[n][k0:] - rest[n])) / scale < 1e-9
    # switching events after the snapshot are identical too
    after = [e for e in full.events if e[0] > 0.05]
    assert [(i, s) for _, i, s in after] == [(i, s) for _, i, s in rest.events]
    np.testing.assert_allclose([e[0] for e in after], [e[0] for e in rest.events],
                               rtol=0, atol=1e-15)


def test_snapshot_rejects_different_circuit(tmp_path: Path) -> None:
    s = bridge(20e-6)
    st = s.initial_state()
    save_snapshot(s, st, tmp_path / "s.h5")
    with pytest.raises(VnEMTError, match="mạch hoặc bước thời gian khác"):
        load_snapshot(bridge(10e-6), tmp_path / "s.h5")


@pytest.mark.req("S-08")
def test_case_level_snapshot_roundtrip(cases_dir: Path, tmp_path: Path) -> None:
    text = (cases_dir / "m1_diode_bridge.yaml").read_text(encoding="utf-8")
    text = text.replace("../results/m1_diode_bridge/snapshot_t0.3.h5", "snap.h5")
    text = text.replace("t_end_s: 0.4", "t_end_s: 0.1").replace("t_s: 0.3", "t_s: 0.06")
    base = tmp_path / "base.yaml"
    base.write_text(text, encoding="utf-8")
    full = vnemt.load(base).run()
    assert (tmp_path / "snap.h5").is_file()

    cont = tmp_path / "cont.yaml"
    cont.write_text(text.replace("  snapshot: {t_s: 0.06, file: snap.h5}\n",
                                 "  init: {mode: snapshot, file: snap.h5}\n"), encoding="utf-8")
    rest = vnemt.load(cont).run()
    assert rest.time[0] == pytest.approx(0.06)
    k0 = int(np.argmin(np.abs(full.time - 0.06)))
    for n in rest.names:
        np.testing.assert_allclose(rest[n], full[n][k0:], rtol=0,
                                   atol=1e-9 * max(1.0, float(np.max(np.abs(full[n])))))
    assert rest.meta["init_snapshot"].endswith("snap.h5")
