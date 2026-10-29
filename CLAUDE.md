# VnEMT — hướng dẫn cho Claude Code

Phần mềm mô phỏng quá độ điện từ (EMT) cho hệ thống điện, phiên bản 0.1 tập trung vào HVDC. Đặc tả gốc: `docs/SPEC-v0.1.md` (lõi EMT – HVDC); đặc tả mở rộng: `docs/SPEC-phan-tich-luoi-v0.1.md` (phân tích lưới phasor, quy hoạch – vận hành, runback/run-up). Mọi thay đổi phải truy về được một mã yêu cầu trong đặc tả (S-xx, F1-…F8-…, IO-xx, P-xx, Q-xx; mở rộng: G-, P-, O-, R-, H-).

## Ngôn ngữ

- Trao đổi với người dùng, thông báo lỗi cho người dùng, tài liệu `docs/`: **tiếng Việt**.
- Tên biến, hàm, lớp, comment trong mã, commit message: tiếng Anh. Thuật ngữ chuyên ngành giữ nguyên (alpha, gamma, overlap, CEA, VDCOL, NLM…).

## Công nghệ

- Python ≥ 3.11, NumPy, SciPy (sparse, splu), Numba cho vòng lặp nóng, h5py, PyYAML + jsonschema, Matplotlib/Plotly, pytest, ruff, mypy.
- Quản lý môi trường: `uv` (ưu tiên) hoặc `venv` + `pip`. Hệ điều hành chính của người dùng: **Windows** — đường dẫn dùng `pathlib`, không gọi lệnh chỉ có trên Linux trong mã.

## Lệnh thường dùng

```bash
uv venv && uv pip install -e ".[dev]"     # cài đặt
pytest -q                                   # toàn bộ kiểm thử
pytest -q -m "not slow"                     # bỏ kiểm thử chậm
ruff check src tests && mypy src            # kiểm tra mã
vnemt run cases/tc01_bridge6.yaml           # chạy một case
vnemt validate cases/                       # kiểm tra schema
```

## Quy tắc kỹ thuật bắt buộc

1. **Đơn vị**: lõi tính bằng SI (V, A, Ω, H, F, s). Hệ pu chỉ ở lớp điều khiển và báo cáo, khai báo cơ bản tường minh.
2. **Lõi giải**: phương pháp Dommel, hình thang + CDA (Euler lùi nửa bước sau đóng cắt), nội suy thời điểm đóng cắt. Không thay đổi phương pháp tích phân mà không cập nhật SPEC mục 5.
3. **Ký hiệu góc** α, β, γ, μ theo IEC 60633 và giáo trình: α tính từ điểm chuyển mạch tự nhiên; β = π − α; γ = β − μ.
4. **Mỗi mô hình mới** phải có: docstring nêu phương trình và nguồn tham khảo; kiểm thử đơn vị; ít nhất một kiểm thử giải tích hoặc so với dạng sóng tham chiếu (`tests/reference/`).
5. **Tái lập**: không dùng số ngẫu nhiên không có seed; kết quả ghi kèm phiên bản và tham số solver.
6. **Không đưa dữ liệu thiết bị thực tế** vào `cases/`; dữ liệu dự án để trong `private/` (đã có trong `.gitignore`).
7. Không tự ý hạ tiêu chí chấp nhận trong SPEC để kiểm thử qua; nếu tiêu chí không khả thi, báo người dùng và đề xuất sửa SPEC.

## Phân công agent

| Việc | Agent |
| --- | --- |
| Kiến trúc, schema YAML, giao diện module, review thiết kế | `emt-architect` |
| Lõi giải, ma trận, đóng cắt, nội suy, snapshot, multiple run | `emt-solver-engineer` |
| Thyristor, cầu 6/12 xung, MBA chuyển đổi, OLTC, lọc AC, lưỡng cực | `lcc-modeler` |
| VSC 2 mức, MMC (DEM/AVM), PWM, NLM, cân bằng tụ | `vsc-mmc-modeler` |
| CC/CEA/VDCOL, EPC/PLL, điều khiển dq, droop, đảo chiều công suất | `hvdc-control-engineer` |
| Thư viện sự cố, logic phục hồi, chỉ số FRT, sóng hài | `fault-study-engineer` |
| Điện cực nối đất, mô hình đất, DC bias | `grounding-engineer` |
| Turbine gió tổng hợp, lưới ngoài khơi, chopper | `offshore-wind-modeler` |
| Xuất/nhập COMTRADE, PSCAD .out/.inf/.psout/.pscx, MATLAB, PSS/E, CGMES; so sánh dạng sóng | `interop-engineer` |
| Trào lưu, ngắn mạch, N-k, PV/QV, ATC, OPF | `grid-analysis-engineer` |
| Ổn định RMS, tần số, trị riêng, runback/run-up, lai RMS–EMT | `power-system-dynamics-engineer` |
| Quy hoạch, chuỗi thời gian, độ tin cậy, sàng lọc HVDC, đấu nối, vận hành | `transmission-planning-engineer` |
| Kiểm thử giải tích, hội tụ, benchmark CIGRE, báo cáo nghiệm thu | `validation-engineer` |

Quy trình mặc định cho một tính năng: `emt-architect` (thiết kế ngắn) → agent chuyên môn (mã + kiểm thử) → `validation-engineer` (kiểm chứng độc lập) → cập nhật ma trận truy xuất SPEC mục 13.

## Lệnh slash của dự án

- `/milestone M2` — lập kế hoạch và thực hiện một mốc trong SPEC mục 11.
- `/new-component <tên> <nhóm>` — tạo khung mô hình + kiểm thử theo chuẩn.
- `/new-case <mô tả>` — tạo file case YAML hợp lệ.
- `/validate <case hoặc nhóm>` — chạy kiểm chứng và báo cáo đạt/không đạt.
- `/spec-trace` — rà soát yêu cầu SPEC nào đã có mã, kiểm thử.
- `/study <loại> <lưới>` — thiết lập và chạy nghiên cứu lưới (từ v0.4).
- `/convert <file> <định dạng>` — chuyển kết quả/mô hình giữa VnEMT, PSCAD và phần mềm khác.

## Trao đổi với PSCAD

- Kết quả: COMTRADE và `.out/.inf` đọc/ghi trực tiếp; `.psout` chỉ đọc qua `mhi-psout`.
- Mô hình: qua thư viện `mhi-pscad` (cần Windows + PSCAD V5 có giấy phép), mức L1–L3; không chuyển Blackbox hay mã Fortran/C.
- Phụ thuộc PSCAD cài bằng `uv pip install -e ".[pscad]"`; kiểm thử đánh dấu `@pytest.mark.pscad`.

## Quyết định đã chốt với người dùng (29/10/2026)

- "Run back / Forward Study" = nghiên cứu runback/run-up HVDC, chiều thuận và chiều ngược.
- Bộ tiêu chí lưới: người dùng tự đặt sau trong `criteria/`; không dùng ngưỡng mặc định.
- PSS/E: mục tiêu bản 36 (`psse.target_version`), đọc ngược 33–35.
