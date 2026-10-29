# Hướng dẫn VnEMT

Tài liệu này hướng dẫn cài đặt, phát triển VnEMT bằng Claude Code trong VS Code, và cách sử dụng phần mềm theo thiết kế. Các phần ghi **(dự kiến)** mô tả chức năng sẽ có khi mốc tương ứng hoàn thành; giao diện chính xác có thể thay đổi trong quá trình xây dựng.

## Mục lục

1. [Cài đặt](#1-cài-đặt)
2. [Phát triển với Claude Code](#2-phát-triển-với-claude-code)
3. [Agent và lệnh](#3-agent-và-lệnh)
4. [Sử dụng phần mềm (dự kiến)](#4-sử-dụng-phần-mềm-dự-kiến)
5. [Trao đổi dữ liệu với PSCAD, PSS/E và phần mềm khác](#5-trao-đổi-dữ-liệu-với-pscad-psse-và-phần-mềm-khác)
6. [Nghiên cứu lưới và runback/run-up (dự kiến, từ v0.4)](#6-nghiên-cứu-lưới-và-runbackrun-up-dự-kiến-từ-v04)
7. [Quy tắc làm việc](#7-quy-tắc-làm-việc)
8. [Xử lý sự cố thường gặp](#8-xử-lý-sự-cố-thường-gặp)

---

## 1. Cài đặt

### 1.1 Phần mềm cần có (Windows 10/11)

| Phần mềm | Ghi chú |
| --- | --- |
| Python ≥ 3.11 | Tích chọn *Add Python to PATH* khi cài |
| Git | |
| VS Code | |
| uv | Trong PowerShell: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| Extension **Claude Code** (Anthropic) cho VS Code | Đăng nhập tài khoản claude.ai (Pro, Max, Team hoặc Enterprise) |
| PSCAD V5, PSS/E 36 | **Không bắt buộc**. Chỉ cần khi trao đổi mô hình trực tiếp với hai phần mềm này |

### 1.2 Lấy mã nguồn

```powershell
cd D:\Projects
git clone https://github.com/quantrong77/VnEMT.git
cd VnEMT
```

Nên đặt dự án ngoài thư mục đồng bộ OneDrive để tránh xung đột file khi Claude Code ghi nhiều file.

### 1.3 Tạo môi trường Python

```powershell
uv venv
uv pip install -e ".[dev]"
```

Nếu máy có PSCAD V5 và muốn đọc file `.psout` hoặc điều khiển PSCAD từ Python:

```powershell
uv pip install -e ".[dev,pscad]"
```

Trong VS Code: `Ctrl+Shift+P` → *Python: Select Interpreter* → chọn `.venv`.

### 1.4 Mở trong VS Code

```powershell
code .
```

Khi VS Code gợi ý cài các extension khuyến nghị (Python, Ruff, Jupyter, YAML, Mermaid), chọn **Install All**.

### 1.5 Thư mục dữ liệu riêng

Tạo thư mục `private/` ở gốc dự án để chứa thông số thiết bị của dự án thật (MBA, van, điều khiển của nhà cung cấp). Thư mục này đã nằm trong `.gitignore` và Claude Code bị chặn đọc theo `.claude/settings.json`.

---

## 2. Phát triển với Claude Code

### 2.1 Kiểm tra cấu hình

Mở khung Claude Code trong VS Code:

- Gõ `/agents` → phải thấy **13 agent** (mục 3.1).
- Gõ `/` → phải thấy **7 lệnh** của dự án (mục 3.2).

Nếu thiếu, đóng và mở lại khung Claude Code (lần đầu tạo thư mục `.claude/agents` cần khởi động lại).

### 2.2 Quy trình theo mốc

Mã nguồn được xây dựng theo các mốc trong [SPEC-v0.1 mục 11](SPEC-v0.1.md#11-lộ-trình-phát-triển):

| Mốc | Nội dung | Case nghiệm thu |
| --- | --- | --- |
| M0 | Khung dự án, CI, schema YAML, đọc case, ghi HDF5 | `vnemt run` chạy mạch RLC |
| M1 | Lõi giải Dommel, khóa, nội suy, CDA, snapshot | Kiểm thử giải tích, hội tụ |
| M2 | LCC: thyristor, cầu 6/12 xung, MBA Y/Δ, EPC/PLL, CC/CEA/VDCOL | TC-01, TC-02 |
| M3 | Sự cố, chỉ số FRT, multiple run; xuất/nhập COMTRADE, PSCAD `.out` | TC-03, TC-09, TC-10 |
| M4 | Lưỡng cực, OLTC, lọc AC, sóng hài, đảo chiều LCC | TC-04, TC-05 |
| M5 | VSC 2 mức, MMC DEM/AVM, điều khiển dq | TC-05 |
| M6 | MTDC, droop, trào lưu DC | TC-06 |
| M7 | Nối đất | TC-07 |
| M8 | Điện gió ngoài khơi | TC-08 |
| M9 | Tài liệu, ví dụ, phát hành v0.1 | Toàn bộ |

Với mỗi mốc:

1. Gõ `/milestone M0` (thay bằng mốc cần làm).
2. Claude Code nhờ `emt-architect` lập kế hoạch và trình bảng việc. **Đọc kỹ, chỉnh nếu cần, rồi xác nhận.**
3. Các agent chuyên môn viết mã và kiểm thử. Khi được hỏi quyền sửa file, có thể cho phép chỉnh sửa trong phiên.
4. `validation-engineer` kiểm chứng độc lập và ghi báo cáo vào `docs/validation/`.
5. Tự kiểm tra lại:

   ```powershell
   pytest -q
   ruff check src tests
   mypy src
   ```

6. Commit và đẩy lên GitHub:

   ```powershell
   git add .
   git commit -m "M0: project skeleton, schema, HDF5 output"
   git push
   ```

7. Gõ `/spec-trace` để xem tỷ lệ yêu cầu đã có mã và kiểm thử.

Chỉ chuyển sang mốc sau khi mốc trước đạt nghiệm thu. M0 và M1 là nền móng: sai ở đây thì mọi mô hình HVDC sau đều sai theo.

### 2.3 Làm việc từ điện thoại

Khi mốc chạy lâu: gõ `/rc` trong khung Claude Code, rồi mở app Claude trên điện thoại → tab **Code** → chọn phiên để duyệt quyền và trả lời câu hỏi. Laptop và VS Code phải luôn mở.

### 2.4 Gọi trực tiếp một agent

Gõ `@` trong khung Claude Code rồi chọn agent, ví dụ:

```text
@agent-lcc-modeler thêm bộ lọc C-type bậc 3, tính tham số từ Q = 50 Mvar
```

---

## 3. Agent và lệnh

### 3.1 Agent (`.claude/agents/`)

| Agent | Phụ trách | Yêu cầu SPEC |
| --- | --- | --- |
| `emt-architect` | Kiến trúc, giao diện module, schema YAML, review thiết kế | Toàn bộ |
| `emt-solver-engineer` | Lõi giải Dommel, đóng cắt, nội suy, snapshot, multiple run, hiệu năng | S-xx, P-xx |
| `lcc-modeler` | Thyristor, cầu 6/12 xung, MBA chuyển đổi, OLTC, bộ lọc, lưỡng cực | F1-L, F2, F5 |
| `vsc-mmc-modeler` | VSC 2 mức, MMC DEM/AVM, PWM, NLM, cân bằng tụ | F1-V, F6 |
| `hvdc-control-engineer` | EPC/PLL, CC/CEA/VDCOL, điều khiển dq, droop, đảo chiều | F3 |
| `fault-study-engineer` | Thư viện sự cố, chỉ số FRT, sóng hài | F4, F5 |
| `grounding-engineer` | Điện cực nối đất, mô hình đất, DC bias | F7 |
| `offshore-wind-modeler` | Turbine tổng hợp, lưới ngoài khơi, chopper | F8 |
| `interop-engineer` | COMTRADE, PSCAD, PSS/E, MATLAB, CGMES | IO-xx |
| `grid-analysis-engineer` | Trào lưu, ngắn mạch, N-k, PV/QV, ATC, OPF | G-xx |
| `power-system-dynamics-engineer` | Ổn định RMS, tần số, trị riêng, runback/run-up, lai RMS–EMT | G-07…09, R, H |
| `transmission-planning-engineer` | Quy hoạch, chuỗi thời gian, độ tin cậy, sàng lọc HVDC, đấu nối, vận hành | P, O |
| `validation-engineer` | Kiểm chứng độc lập, báo cáo nghiệm thu (không sửa mã mô hình) | Tất cả |

### 3.2 Lệnh (`.claude/skills/`)

| Lệnh | Tác dụng |
| --- | --- |
| `/milestone <M0…M9>` | Lập kế hoạch và thực hiện một mốc |
| `/new-component <tên> <nhóm>` | Tạo khung mô hình mới kèm docstring, kiểm thử giải tích |
| `/new-case <mô tả>` | Tạo file case YAML hợp lệ từ mô tả bằng lời |
| `/validate <case \| F1…F8 \| M0…M9 \| all>` | Chạy kiểm chứng, báo cáo đạt/không đạt |
| `/spec-trace` | Lập ma trận truy xuất yêu cầu ↔ mã ↔ kiểm thử |
| `/convert <file> <định dạng>` | Chuyển kết quả/mô hình giữa VnEMT, PSCAD, PSS/E, COMTRADE… |
| `/study <loại> <lưới>` | Thiết lập và chạy nghiên cứu lưới (từ v0.4) |

---

## 4. Sử dụng phần mềm (dự kiến)

### 4.1 Lệnh dòng lệnh

```powershell
vnemt validate cases/tc02_cigre_lcc.yaml      # kiểm tra file case theo schema
vnemt run cases/tc02_cigre_lcc.yaml           # chạy mô phỏng
vnemt run cases/tc03_inv_dip.yaml --sweep sweeps/dip_depth.yaml   # quét nhiều lần chạy
vnemt report results/tc03_inv_dip/            # tạo báo cáo Markdown/HTML
```

### 4.2 File case

Mô hình mô tả bằng file YAML (xem đầy đủ tại [SPEC-v0.1 mục 9.1](SPEC-v0.1.md#91-file-mô-tả-case-yaml)):

```yaml
case:
  name: cigre_lcc_bipole
  solver: {dt_us: 20, t_end_s: 1.5, method: trapezoidal, cda: true}
base: {S_MVA: 1000, U_dc_kV: 500, f_Hz: 50}
converter_stations:
  - id: REC_P
    type: lcc_12pulse
    control: {mode: CC, alpha_min_deg: 5}
events:
  - {t_s: 1.0, type: ac_fault, location: AC_I, kind: 3ph, duration_ms: 100}
outputs:
  signals: [REC_P.Id, REC_P.alpha, INV_P.gamma]
  format: [hdf5, comtrade, pscad_out]
```

Tạo nhanh bằng Claude Code: `/new-case liên kết LCC lưỡng cực 500 kV, sụt áp 20% phía nghịch lưu`.

### 4.3 Python API

```python
import vnemt
case = vnemt.load("cases/tc02_cigre_lcc.yaml")
res = case.run()
res.plot(["REC_P.Id", "INV_P.gamma"])
res.export("results/tc02.cfg", format="comtrade")
```

### 4.4 Kết quả

| Định dạng | Dùng cho |
| --- | --- |
| HDF5 | Lưu trữ đầy đủ, phân tích bằng Python |
| COMTRADE | Phần mềm phân tích sự cố, rơle, Enerplot, PSCAD, PowerFactory |
| PSCAD `.out` + `.inf` | Mở bằng Enerplot, so sánh với PSCAD |
| CSV, MATLAB `.mat` | Excel, MATLAB/Octave |
| Báo cáo Markdown/HTML | Chỉ số FRT, sóng hài, kết luận đạt/không đạt |

---

## 5. Trao đổi dữ liệu với PSCAD, PSS/E và phần mềm khác

Chi tiết tại [SPEC-v0.1 mục 9.3](SPEC-v0.1.md#93-trao-đổi-dữ-liệu-với-pscad-và-phần-mềm-khác) và [SPEC-phan-tich-luoi mục 7](SPEC-phan-tich-luoi-v0.1.md#7-trao-đổi-dữ-liệu-psse-bổ-sung-spec-v01-mục-934).

| Phần mềm | Kết quả (dạng sóng) | Mô hình |
| --- | --- | --- |
| PSCAD | Xuất/nhập COMTRADE và `.out/.inf`; nhập `.psout` (cần `mhi-psout`) | Mức L1–L3 qua `mhi-pscad` (cần PSCAD V5), từ v0.2. Không chuyển Blackbox hay mã Fortran/C |
| PSS/E (mục tiêu bản 36, đọc ngược 33–35) | Nhập `.out` để so sánh | RAW, SEQ (v0.2); RAWX, SUB/MON/CON (v0.4); DYR (v0.5); `.sav` qua `psspy` |
| PowerFactory, CGMES, ATP, FMI | COMTRADE | v0.3 |

Ví dụ: `/convert results/tc03.h5 pscad_out` rồi mở file `.out` bằng Enerplot.

Đổi phiên bản PSS/E mục tiêu: sửa khóa `psse.target_version` trong cấu hình.

---

## 6. Nghiên cứu lưới và runback/run-up (dự kiến, từ v0.4)

### 6.1 Bộ tiêu chí

Phần mềm **không có ngưỡng mặc định**. Sao chép `criteria/template.yaml` thành file mới, điền ngưỡng điện áp, mang tải, ngắn mạch, ổn định và căn cứ văn bản. Nghiên cứu dừng và báo lỗi nếu còn ô trống.

### 6.2 Chạy nghiên cứu

```text
/study n-1 data/luoi_500kV_2030.raw
/study runback cases/hvdc_bipole.yaml
```

Nghiên cứu runback/run-up luôn chạy cả chiều truyền thuận và chiều ngược, đánh giá phía lưới AC (RMS) và phía bộ chuyển đổi (EMT).

---

## 7. Quy tắc làm việc

- Mọi thay đổi phải gắn với một mã yêu cầu trong SPEC. Muốn thêm tính năng mới: sửa SPEC trước, rồi mới yêu cầu Claude Code viết mã.
- Không hạ tiêu chí chấp nhận để kiểm thử qua. Nếu tiêu chí không khả thi, sửa SPEC có ghi lý do.
- Commit sau mỗi mốc; khi Claude Code làm hỏng, xem bằng `git diff` và quay lại bằng `git restore`.
- Không đưa thông số thiết bị thật vào `cases/` hay lên GitHub; dùng `private/`.
- Thay đổi lõi giải (`src/vnemt/core/`) phải cập nhật SPEC mục 5 trước.

## 8. Xử lý sự cố thường gặp

| Hiện tượng | Cách xử lý |
| --- | --- |
| `/agents` không thấy agent | Đóng và mở lại khung Claude Code; kiểm tra đang mở đúng thư mục gốc dự án |
| `uv` không nhận | Mở lại PowerShell sau khi cài để cập nhật PATH |
| `vnemt` báo "chưa được triển khai" | Bình thường trước khi xong M0 |
| Kiểm thử đánh dấu `pscad` bị bỏ qua | Máy chưa cài PSCAD hoặc gói `[pscad]`; không ảnh hưởng chức năng khác |
| Claude Code hỏi quyền liên tục | Chọn cho phép chỉnh sửa trong phiên; lệnh pytest, ruff, mypy, vnemt đã được cho phép sẵn trong `.claude/settings.json` |
| Remote Control không thấy phiên trên điện thoại | App và VS Code phải cùng tài khoản claude.ai; gõ lại `/rc` |
