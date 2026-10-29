from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "cases"


@pytest.fixture
def cases_dir() -> Path:
    return CASES
