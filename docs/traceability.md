# Ma trận truy xuất yêu cầu ↔ mã ↔ kiểm thử

Cập nhật sau mỗi mốc (SPEC-v0.1 mục 13). Trạng thái: **Đạt** (có mã và kiểm thử đạt tiêu chí), **Một phần**, **Chưa**.

Cập nhật lần cuối: 29/10/2026 — sau mốc M1.

## Lõi giải và chất lượng

| Mã | Yêu cầu (rút gọn) | Mã nguồn | Kiểm thử | Trạng thái |
| --- | --- | --- | --- | --- |
| S-01 | Dommel, RLC sai số < 0,1 % với Δt = 1 µs | `core/solver.py` | `tests/core/test_solver_analytic.py::test_series_rlc_dc_step_within_0p1_percent`, `::test_rl_ac_energisation_norton_source` | Đạt |
| S-02 | Hình thang + CDA nửa bước Euler lùi sau đóng cắt | `core/solver.py` | `test_solver_analytic.py::test_trapezoidal_second_order_convergence`, `::test_no_cda_start_lags_half_step`, `test_switching.py::test_inductor_current_interruption_cda` | Đạt theo tiêu chí SPEC r3: dư ≤ 4·i₀·L²/(Δt²·R_off), và 0,16 % điện áp nguồn khi R_off = 1e9 Ω |
| S-03 | Δt cố định 1–100 µs | schema `case.solver.dt_us` | `tests/io/test_case_loader.py` | Đạt |
| S-04 | Nội suy thời điểm đóng cắt, sai số < 1 % Δt, cầu 6 xung không rung | `core/solver.py::step`, `core/switching.py` | `test_switching.py::test_half_wave_rl_rectifier_extinction_time_within_1pct_dt`, `::test_rc_charge_with_off_grid_switch_closing`, `::test_breaker_opens_at_next_current_zero`, `::test_diode_bridge_has_no_chatter` | Đạt |
| S-05 | G thưa, LU lại khi đổi trạng thái van, bộ đệm LU | `core/solver.py::_topology` | `test_switching.py::test_lu_factorisations_are_cached_per_switch_state` | Đạt về chức năng; thời gian chạy P-01 đo ở M2 |
| S-06…S-07 | Bộ giải điều khiển; phân vùng | — | — | Chưa |
| S-08 | Khởi tạo: (a) từ 0 có ramp; (b) trào lưu; (c) snapshot | `core/solver.py` (a), `core/snapshot.py` (c) | `::test_ramp_source`, `test_snapshot.py::test_case_level_snapshot_roundtrip` | Một phần — (b) cần trào lưu (F6-07); tiêu chí xác lập ≤ 0,5 s kiểm ở TC-02 |
| S-09 | Snapshot, chạy tiếp sai lệch < 1e-9 | `core/snapshot.py` | `test_snapshot.py::test_continue_from_snapshot_matches_continuous_run` | Đạt (trùng từng bit) |
| S-10 | Multiple run | — | — | Chưa (M3) |
| S-11 | Van hai trạng thái R_on/R_off, tùy chọn V_T + R_on | `core/switching.py` | `test_switching.py` | Đạt |
| S-12 | Thyristor | — | — | Chưa (M2) |
| S-13 | IGBT + diode ngược | `core/switching.py` (diode) | `test_switching.py::test_diode_bridge_*` | Một phần — diode xong, IGBT ở M5 |
| S-14 | Van tương đương chuỗi thyristor có snubber | — | — | Chưa (M2) |
| Q-01 | Mỗi mô hình có kiểm thử giải tích | `tests/core/` | | Đạt cho R, L, C, nguồn, khóa, diode |
| Q-02 | Tái lập < 1e-9 | | `tests/io/test_results_io.py::test_reproducible_bit_for_bit` | Đạt (trùng từng bit) |
| Q-03 | Kết quả kèm phiên bản, mã băm, tham số solver | `case.py::Case.provenance`, `io/hdf5.py` | `::test_hdf5_roundtrip_with_provenance` | Đạt |
| Q-04 | SI trong lõi | `model/netlist.py`, schema (đơn vị trong tên khóa) | | Đạt |
| Q-05 | Thông báo lỗi tiếng Việt kèm đường dẫn khóa | `errors.py`, `io/case_loader.py` | `tests/io/test_case_loader.py` | Đạt |
| Q-06 | Type hints + mypy strict, ruff, phủ `core/` ≥ 80 % | toàn bộ `src/` | CI | Đạt (phủ `core/` 94–100 %) |

## Dữ liệu vào/ra

| Mã | Yêu cầu | Mã nguồn | Kiểm thử | Trạng thái |
| --- | --- | --- | --- | --- |
| 9.1 | Case YAML + JSON Schema, lỗi theo đường dẫn khóa | `io/schema/case.schema.json`, `io/case_loader.py` | `tests/io/test_case_loader.py` | Một phần — `circuit` kiểm chặt; `ac_systems`, `converter_stations`, `dc_network`, `events` chỉ kiểm kiểu (chặt dần từ M2) |
| 9.2 | HDF5 + metadata | `io/hdf5.py` | `tests/io/test_results_io.py` | Đạt |
| IO-07 | CSV, HDF5, `.mat` | `io/csvfile.py`, `io/hdf5.py` | `::test_csv_export` | Một phần — `.mat` ở M3 |
| IO-01…IO-06 | COMTRADE, PSCAD `.out/.inf`, so sánh dạng sóng | — | — | Chưa (M3) |

## Mô hình dữ liệu dùng chung (SPEC-phan-tich-luoi 2.1)

| Mục | Mã nguồn | Trạng thái |
| --- | --- | --- |
| Netlist mức mạch, định danh nút dạng chuỗi, không phụ thuộc lõi giải | `model/netlist.py` | Đạt |
| Mô hình bus-branch + mở rộng sang Netlist | `model/grid.py` | Chưa — thiết kế khi bắt đầu M2 (lưới AC Thevenin) để v0.4 dùng lại |

## Case nghiệm thu

| Mốc / Case | Nội dung | Kết quả |
| --- | --- | --- |
| M0 | `vnemt run cases/m0_rlc_series.yaml` | Đạt — `tests/test_cli.py`, CI |
| M1 | V1, V2 cho mạch thụ động và chỉnh lưu diode (`cases/m1_diode_bridge.yaml`) | Đạt — Ud sai lệch < 1 % so với công thức, μ sai lệch < 0,5°, hội tụ khi giảm Δt; S-02 đạt theo SPEC r3 |
| TC-01…TC-10 | | Chưa |
