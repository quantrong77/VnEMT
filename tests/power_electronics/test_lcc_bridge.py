"""Six-pulse bridge builder (F1-L01) and valve snubbers (S-14)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from vnemt.analysis.lcc import measure_bridge
from vnemt.control import Epc6, PllSrf
from vnemt.core import EmtSolver, simulate
from vnemt.io.case_loader import load_case
from vnemt.model.netlist import Element, Netlist, build_netlist
from vnemt.power_electronics.lcc_bridge import six_pulse_bridge

F, U_LL, LC, ID = 50.0, 10e3, 5e-3, 250.0


def test_builder_matches_tc01_valve_topology(cases_dir: Path) -> None:
    net = build_netlist(load_case(cases_dir / "tc01_bridge6.yaml").data)
    els, ids = six_pulse_bridge("T", ("A", "B", "C"), "P", "N")
    assert ids == ["T1", "T2", "T3", "T4", "T5", "T6"]
    for el in els:
        assert net.element(el.id).nodes == el.nodes


@pytest.mark.req("S-14")
def test_bridge_with_rc_snubbers_keeps_average_voltage() -> None:
    upk = U_LL * np.sqrt(2 / 3)
    els = []
    for k, ph in enumerate("abc"):
        els += [Element(f"V{ph}", "V_ac", (f"S{ph}", "gnd"),
                        {"U_peak_V": upk, "f_Hz": F, "phase_deg": -120.0 * k}),
                Element(f"L{ph}", "L", (f"S{ph}", ph.upper()), {"L_H": LC})]
    br, ids = six_pulse_bridge("T", ("A", "B", "C"), "P", "N", snubber=(5000.0, 0.05e-6))
    assert sum(1 for e in br if e.kind == "C") == 6
    els += br + [Element("ID", "I_dc", ("N", "P"), {"I_A": ID, "ramp_s": 0.02}),
                 Element("RG", "R", ("N", "gnd"), {"R_ohm": 1e6})]
    s = EmtSolver(Netlist(els), dt=20e-6)
    alpha = 30.0
    res = simulate(s, 0.2, ["Sa.V", "Sb.V", "Sc.V", "P.V", "N.V"],
                   controllers=[PllSrf("PLL", "Sa.V", "Sb.V", "Sc.V", F),
                                Epc6("EPC", "PLL", ids, alpha_deg=alpha)])
    last = res.time > 0.16
    ud = np.mean((res["P.V"] - res["N.V"])[last])
    xc = 2 * np.pi * F * LC
    ud0 = 3 * np.sqrt(2) / np.pi * U_LL
    assert abs(ud - (ud0 * np.cos(np.radians(alpha)) - 3 / np.pi * xc * ID)) / ud0 < 0.01
    m = measure_bridge(res, ids, ("Sa.V", "Sb.V", "Sc.V"), F)
    assert m.n_cf == 0
    assert np.max(np.abs(m.alpha[m.t > 0.16] - alpha)) < 0.1
