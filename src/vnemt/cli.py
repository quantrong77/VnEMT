"""Command line interface ``vnemt`` (SPEC-v0.1 section 4.1).

Commands: ``run``, ``validate``; ``report`` is reserved for milestone M3.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from vnemt import __version__
from vnemt.errors import VnEMTError


def _case_files(paths: Sequence[str]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted([*p.rglob("*.yaml"), *p.rglob("*.yml")]))
        else:
            files.append(p)
    return files


def cmd_validate(args: argparse.Namespace) -> int:
    from vnemt.io.case_loader import load_case

    files = _case_files(args.paths)
    if not files:
        print("Không tìm thấy file case (*.yaml) nào.")
        return 1
    n_bad = 0
    for f in files:
        try:
            load_case(f)
            print(f"[hợp lệ]   {f}")
        except VnEMTError as exc:
            n_bad += 1
            print(f"[lỗi]      {exc}")
    print(f"\n{len(files) - n_bad}/{len(files)} file hợp lệ.")
    return 1 if n_bad else 0


def cmd_run(args: argparse.Namespace) -> int:
    import vnemt

    case = vnemt.load(args.case)
    out_dir = Path(args.output) if args.output else Path("results") / case.name
    t0 = time.perf_counter()
    res = case.run()
    elapsed = time.perf_counter() - t0
    written = []
    for fmt in case.formats:
        ext = {"hdf5": ".h5", "csv": ".csv"}[fmt]
        written.append(res.export(out_dir / f"{case.name}{ext}", format=fmt))
    if args.plot:
        written.append(out_dir / f"{case.name}.png")
        res.plot(path=written[-1])
    sp = case.solver_params
    print(f"Case '{case.name}': {len(res.time)} điểm, dt = {sp['dt_us']} µs, "
          f"t_end = {sp['t_end_s']} s, {len(res.signals)} tín hiệu, {elapsed:.2f} s.")
    for p in written:
        print(f"  -> {p}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    print("Lệnh 'report' chưa triển khai (dự kiến mốc M3).")
    return 2


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="vnemt", description="VnEMT - mô phỏng quá độ điện từ")
    ap.add_argument("--version", action="version", version=f"vnemt {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="chạy mô phỏng một file case")
    p.add_argument("case", help="file case YAML")
    p.add_argument("-o", "--output", help="thư mục kết quả (mặc định results/<tên case>)")
    p.add_argument("--plot", action="store_true", help="vẽ toàn bộ tín hiệu ra PNG")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("validate", help="kiểm tra file case theo schema")
    p.add_argument("paths", nargs="+", help="file hoặc thư mục")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("report", help="tạo báo cáo (mốc M3)")
    p.add_argument("path")
    p.set_defaults(func=cmd_report)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        code: int = args.func(args)
    except VnEMTError as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        return 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())
