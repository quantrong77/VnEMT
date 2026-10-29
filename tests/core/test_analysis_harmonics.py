"""Harmonic evaluation (F5-06) and frequency scan (F5-07)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from vnemt.analysis.freqscan import positive_sequence_impedance
from vnemt.analysis.harmonics import compare_filters, harmonic_table, spectrum, tif
from vnemt.errors import VnEMTError
from vnemt.model.netlist import Element, Netlist
from vnemt.results import Result

F = 50.0


def wave(t: np.ndarray, comps: dict[int, float]) -> np.ndarray:
    return sum(a * np.sin(2 * np.pi * F * n * t + 0.3 * n) for n, a in comps.items())


@pytest.mark.req("F5-06")
def test_spectrum_dn_and_thd() -> None:
    t = np.arange(0, 0.1 + 1e-12, 20e-6)
    x = wave(t, {1: 100.0, 5: 4.0, 7: 3.0, 11: 1.2})
    s = spectrum(t, x, F)
    assert s.cycles == 5
    assert s.fundamental == pytest.approx(100.0, rel=1e-9)
    assert s.dn_pct()[5] == pytest.approx(4.0, rel=1e-9) and s.dn_pct()[11] == pytest.approx(1.2)
    assert s.thd_pct() == pytest.approx(math.sqrt(16 + 9 + 1.44), rel=1e-9)
    r = Result(time=t, signals={"v": x, "w": wave(t, {1: 100.0, 5: 1.0})}, units={})
    rows = compare_filters(Result(time=t, signals={"v": wave(t, {1: 100.0, 5: 1.0})}, units={}),
                           r, ["v"], F, orders=(5, 7))
    assert rows[0]["D5_pct"] == pytest.approx(1.0) and rows[1]["D5_pct"] == pytest.approx(4.0)
    assert harmonic_table(r, "w", F)["THD_pct"] == pytest.approx(1.0)


@pytest.mark.req("F5-06")
def test_tif_requires_user_weights() -> None:
    t = np.arange(0, 0.04 + 1e-12, 20e-6)
    x = wave(t, {1: 100.0, 5: 10.0})
    with pytest.raises(VnEMTError, match="bảng trọng số"):
        tif(t, x, F, None)
    # weights 1 at 50 Hz and 20 at 250 Hz (zero elsewhere, linear in between not used here)
    w = {50.0: 1.0, 250.0: 20.0}
    expected = math.sqrt(100**2 + (20 * 10) ** 2) / math.sqrt(100**2 + 10**2)
    assert tif(t, x, F, w) == pytest.approx(expected, rel=1e-6)


@pytest.mark.req("F5-07")
def test_frequency_scan_thevenin_with_capacitor() -> None:
    r, lv, c = 2.0, 0.05, 20e-6
    els = []
    for k, p in enumerate("abc"):
        els += [Element(f"V{p}", "V_ac", (f"E{p}", "gnd"), {"U_peak_V": 1.0, "f_Hz": F}),
                Element(f"R{p}", "R", (f"E{p}", f"M{p}"), {"R_ohm": r}),
                Element(f"L{p}", "L", (f"M{p}", p), {"L_H": lv}),
                Element(f"C{p}", "C", (p, "gnd"), {"C_F": c})]
    freqs = np.array([50.0, 150.0, 1 / (2 * np.pi * math.sqrt(lv * c)), 1000.0])
    z = positive_sequence_impedance(Netlist(els), ("a", "b", "c"), freqs)
    w = 2 * np.pi * freqs
    exact = 1 / (1 / (r + 1j * w * lv) + 1j * w * c)
    np.testing.assert_allclose(z, exact, rtol=1e-9)
    assert np.argmax(np.abs(z)) == 2  # parallel resonance


@pytest.mark.req("F5-07")
def test_frequency_scan_matched_line_is_flat() -> None:
    lp, cp = 1e-3, 11e-9
    zc = math.sqrt(lp / cp)
    els = []
    for p in "abc":
        els += [Element(f"TL{p}", "LINE", (p, f"m{p}"),
                        {"length_km": 300.0, "L_H_per_km": lp, "C_F_per_km": cp}),
                Element(f"R{p}", "R", (f"m{p}", "gnd"), {"R_ohm": zc})]
    z = positive_sequence_impedance(Netlist(els), ("a", "b", "c"), [50.0, 777.0, 2500.0])
    np.testing.assert_allclose(z, zc, rtol=1e-9)
