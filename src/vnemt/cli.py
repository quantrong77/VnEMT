"""Command line interface ``vnemt`` (SPEC-v0.1 section 4.1, IO-01...IO-07).

Commands: ``run``, ``validate``, ``convert``, ``compare``; ``report`` comes with M3b.
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
        written.append(res.export(out_dir / f"{case.name}{_EXT[fmt]}", format=fmt))
    if args.plot:
        written.append(out_dir / f"{case.name}.png")
        res.plot(path=written[-1])
    sp = case.solver_params
    print(f"Case '{case.name}': {len(res.time)} điểm, dt = {sp['dt_us']} µs, "
          f"t_end = {sp['t_end_s']} s, {len(res.signals)} tín hiệu, {elapsed:.2f} s.")
    for p in written:
        print(f"  -> {p}")
    return 0


_EXT = {"hdf5": ".h5", "csv": ".csv", "comtrade": ".cfg", "pscad_out": ".inf", "mat": ".mat"}


def cmd_convert(args: argparse.Namespace) -> int:
    from vnemt.io import read

    res = read(args.src)
    fmt = args.format
    opts: dict[str, object] = {}
    if fmt == "comtrade" or (fmt is None and Path(args.dst).suffix.lower() == ".cfg"):
        opts = {"rev": args.rev, "fmt": args.data_format}
    p = res.export(args.dst, format=fmt, **opts)
    print(f"Đã chuyển {args.src} -> {p} ({len(res.signals)} tín hiệu, {len(res.time)} mẫu).")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    from vnemt.analysis.compare import compare, to_csv, to_markdown
    from vnemt.io import read

    ref, test = read(args.ref), read(args.test)
    pairs = dict(m.split("=", 1) for m in args.map) if args.map else None
    t_range = (args.t0, args.t1) if args.t0 is not None and args.t1 is not None else None
    rows = compare(ref, test, pairs, t_range=t_range, threshold=args.threshold,
                   t_clear=args.t_clear)
    print(to_markdown(rows))
    if args.csv:
        print(f"  -> {to_csv(rows, args.csv)}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    print("Lệnh 'report' chưa triển khai (dự kiến mốc M3b).")
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

    p = sub.add_parser("convert", help="chuyển định dạng kết quả (COMTRADE, PSCAD .out, .mat...)")
    p.add_argument("src", help="file vào: .h5 .cfg .inf/.out .mat .csv")
    p.add_argument("dst", help="file ra; định dạng theo phần mở rộng nếu không có --format")
    p.add_argument("--format", choices=sorted(_EXT), help="định dạng ra")
    p.add_argument("--rev", type=int, default=1999, choices=[1999, 2013], help="bản COMTRADE")
    p.add_argument("--data-format", default="BINARY",
                   choices=["ASCII", "BINARY", "BINARY32", "FLOAT32"], help="dạng dữ liệu COMTRADE")
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser("compare", help="so sánh dạng sóng hai kết quả (IO-06)")
    p.add_argument("ref", help="kết quả tham chiếu")
    p.add_argument("test", help="kết quả cần so sánh")
    p.add_argument("--map", nargs="*", help="cặp tín hiệu ten_ref=ten_test")
    p.add_argument("--t0", type=float)
    p.add_argument("--t1", type=float)
    p.add_argument("--threshold", type=float, help="ngưỡng tính thời điểm vượt")
    p.add_argument("--t-clear", type=float, help="thời điểm loại trừ sự cố, tính thời gian phục hồi")
    p.add_argument("--csv", help="ghi bảng so sánh ra CSV")
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("report", help="tạo báo cáo (mốc M3b)")
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
