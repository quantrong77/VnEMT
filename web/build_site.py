"""Build the static try-out site (GitHub Pages): the page, the vnemt wheel and the example
cases. The page runs VnEMT in the browser with Pyodide (no Numba, see ``worker.js``).

Usage: ``python web/build_site.py [out_dir]`` (default ``web/_site``).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else WEB / "_site"
    if out.exists():
        shutil.rmtree(out)
    (out / "cases").mkdir(parents=True)
    for name in ("index.html", "worker.js"):
        shutil.copy2(WEB / name, out / name)
    uv = shutil.which("uv")
    cmd = ([uv, "build", "--wheel", "-q", "-o", str(out), str(ROOT)] if uv else
           [sys.executable, "-m", "pip", "wheel", "--no-deps", "-q", "-w", str(out), str(ROOT)])
    subprocess.run(cmd, check=True)
    (out / ".gitignore").unlink(missing_ok=True)  # uv build ignores its output dir ("*")
    wheel = next(out.glob("vnemt-*.whl")).name
    cases = []
    for f in sorted((ROOT / "cases").glob("*.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        shutil.copy2(f, out / "cases" / f.name)
        solver = d["case"]["solver"]
        cases.append({"file": f.name, "name": d["case"]["name"],
                      "description": d["case"].get("description", ""),
                      "t_end_s": solver["t_end_s"], "dt_us": solver["dt_us"]})
    (out / "manifest.json").write_text(
        json.dumps({"wheel": wheel, "cases": cases}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(f"site: {out} ({len(cases)} cases, {wheel})")


if __name__ == "__main__":
    main()
