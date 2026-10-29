# VnEMT

Phần mềm mô phỏng quá độ điện từ (EMT) cho hệ thống điện, có tính năng tương tự PSCAD/EMTDC. Phiên bản đầu (v0.1) tập trung vào **truyền tải điện một chiều HVDC**; các phiên bản sau mở rộng sang phân tích lưới miền phasor, quy hoạch – vận hành lưới truyền tải và nghiên cứu runback/run-up HVDC.

> **Trạng thái:** đã xong M0 → M4b (lõi EMT, LCC, sự cố/FRT, lưỡng cực, OLTC, lọc AC, sóng hài); tiếp theo M4c. Mã nguồn được xây dựng dần theo các mốc M0 → M9 trong [đặc tả](docs/SPEC-v0.1.md#11-lộ-trình-phát-triển), dùng Claude Code trong VS Code. Ma trận truy xuất: [docs/traceability.md](docs/traceability.md).
>
> **Chạy thử trên trình duyệt** (không cần cài đặt): <https://quantrong77.github.io/VnEMT/> — chạy các case mẫu trong `cases/`, sửa YAML, xem dạng sóng, tải CSV. Trang được dựng lại tự động khi đẩy lên `main` ([web/](web/), workflow `pages.yml`).

## Tính năng theo đặc tả

**Lõi EMT – HVDC (v0.1)** — [docs/SPEC-v0.1.md](docs/SPEC-v0.1.md)

| Mã | Nhóm chức năng |
| --- | --- |
| F1 | HVDC LCC (cầu 6/12 xung, góc kích α, β, γ, μ) và VSC/MMC (PWM, SVPWM, NLM, điều khiển vector dq) |
| F2 | Liên kết đa cực: đơn cực, đơn cực đối xứng, lưỡng cực |
| F3 | Điều khiển dòng điện và đảo chiều công suất (CC, CEA, VDCOL, droop) |
| F4 | Mô phỏng sự cố, đánh giá khả năng chịu sự cố thoáng qua của bộ chuyển đổi |
| F5 | HVDC lưỡng cực có điều khiển nấc MBA chuyển đổi, bộ lọc AC, đánh giá sóng hài |
| F6 | Liên kết HVDC nhiều trạm (MTDC) |
| F7 | Tính toán nối đất (điện cực, đất hai lớp, điện áp bước) |
| F8 | Trang trại gió ngoài khơi nối MMC |
| IO | Trao đổi dữ liệu: COMTRADE, PSCAD `.out/.inf/.psout/.pscx`, PSS/E (mục tiêu bản 36), MATLAB, CGMES |

**Mở rộng (v0.4 → v1.0)** — [docs/SPEC-phan-tich-luoi-v0.1.md](docs/SPEC-phan-tich-luoi-v0.1.md): trào lưu, ngắn mạch IEC 60909, N-1/N-2, ổn định RMS và tín hiệu nhỏ, PV/QV, ATC, trào lưu chuỗi thời gian, độ tin cậy, sàng lọc vị trí HVDC, nghiên cứu runback/run-up chiều thuận và ngược, lai RMS–EMT.

## Bắt đầu nhanh (Windows)

```powershell
git clone https://github.com/quantrong77/VnEMT.git
cd VnEMT
uv venv
uv pip install -e ".[dev]"
code .
```

Trong VS Code, mở khung **Claude Code** và gõ:

```text
/milestone M0
```

Hướng dẫn đầy đủ: **[docs/HUONG-DAN.md](docs/HUONG-DAN.md)**.

## Cấu trúc thư mục

| Đường dẫn | Nội dung |
| --- | --- |
| `docs/SPEC-v0.1.md` | Đặc tả lõi EMT – HVDC: yêu cầu, tiêu chí chấp nhận, lộ trình |
| `docs/SPEC-phan-tich-luoi-v0.1.md` | Đặc tả mở rộng: phân tích lưới, quy hoạch – vận hành, runback/run-up |
| `docs/HUONG-DAN.md` | Hướng dẫn cài đặt, phát triển và sử dụng |
| `CLAUDE.md` | Quy tắc dự án cho Claude Code |
| `.claude/agents/` | 13 agent chuyên môn (lõi giải, LCC, VSC/MMC, điều khiển, sự cố, nối đất, điện gió, trao đổi dữ liệu, phân tích lưới, động học, quy hoạch, kiến trúc, kiểm chứng) |
| `.claude/skills/` | 7 lệnh: `/milestone`, `/new-component`, `/new-case`, `/validate`, `/spec-trace`, `/convert`, `/study` |
| `src/vnemt/` | Mã nguồn Python |
| `cases/` | File case YAML mẫu |
| `criteria/` | Bộ tiêu chí lưới do người dùng đặt (`template.yaml`) |
| `tests/` | Kiểm thử |
| `private/` | Dữ liệu thiết bị dự án thật — không đưa lên git |

## Công nghệ

Python ≥ 3.11, NumPy, SciPy, Numba, h5py, PyYAML, jsonschema, Matplotlib, Plotly, pytest. Lõi giải theo phương pháp Dommel (hình thang + CDA, nội suy thời điểm đóng cắt).

## Tài liệu liên quan

Giáo trình *Điện tử công suất ứng dụng trong HVDC* (công thức, ký hiệu và bài thực hành dùng trong đặc tả) và trang mô phỏng góc kích đi kèm.

## Giấy phép

Chưa chọn giấy phép. Cho tới khi có file `LICENSE`, mã nguồn thuộc quyền của chủ repo.
