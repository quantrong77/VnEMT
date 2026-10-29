# Ma trận truy xuất yêu cầu ↔ mã ↔ kiểm thử

Cập nhật sau mỗi mốc (SPEC-v0.1 mục 13). Trạng thái: **Đạt** (có mã và kiểm thử đạt tiêu chí), **Một phần**, **Chưa**.

Cập nhật lần cuối: 29/10/2026 — sau M4b.

## Lõi giải và chất lượng

| Mã | Yêu cầu (rút gọn) | Mã nguồn | Kiểm thử | Trạng thái |
| --- | --- | --- | --- | --- |
| S-01 | Dommel, RLC sai số < 0,1 % với Δt = 1 µs | `core/solver.py` | `tests/core/test_solver_analytic.py::test_series_rlc_dc_step_within_0p1_percent`, `::test_rl_ac_energisation_norton_source` | Đạt |
| S-02 | Hình thang + CDA nửa bước Euler lùi sau đóng cắt | `core/solver.py` | `test_solver_analytic.py::test_trapezoidal_second_order_convergence`, `::test_no_cda_start_lags_half_step`, `test_switching.py::test_inductor_current_interruption_cda` | Đạt theo tiêu chí SPEC r3: dư ≤ 4·i₀·L²/(Δt²·R_off), và 0,16 % điện áp nguồn khi R_off = 1e9 Ω |
| S-03 | Δt cố định 1–100 µs | schema `case.solver.dt_us` | `tests/io/test_case_loader.py` | Đạt |
| S-04 | Nội suy thời điểm đóng cắt, sai số < 1 % Δt, cầu 6 xung không rung | `core/solver.py::step`, `core/switching.py` | `test_switching.py::test_half_wave_rl_rectifier_extinction_time_within_1pct_dt`, `::test_rc_charge_with_off_grid_switch_closing`, `::test_breaker_opens_at_next_current_zero`, `::test_diode_bridge_has_no_chatter` | Đạt |
| S-05 | G thưa, LU lại khi đổi trạng thái van, bộ đệm LU | `core/solver.py::_topology` | `test_switching.py::test_lu_factorisations_are_cached_per_switch_state` | Đạt; TC-02 (95 nút, 24 van) chạy 1 s mô phỏng trong khoảng 24 s |
| P-01 | Lưỡng cực 12 xung, 1 s, ≤ 2 phút | — | `cases/m4a_bipole.yaml` | Đạt — khoảng 35 s cho 1 s (189 nút, 48 van) |
| Bergeron | Đường dây tham số phân bố 1 dây và nhiều dây (mode) | `core/lines.py` | `tests/core/test_lines.py` | Đạt (không phụ thuộc tần số; ULM ở v0.2) |
| S-06 | Bộ giải điều khiển tuần tự sau mạng, trễ một bước, đa tốc độ | `control/base.py`, `core/simulate.py` | `tests/control/test_blocks_pll.py`, `test_snapshot.py::test_snapshot_includes_control_state` | Đạt — thứ tự khối theo khai báo (như PSCAD) |
| S-07 | Phân vùng | — | — | Chưa (v0.2) |
| S-08 | Khởi tạo: (a) từ 0 có ramp; (b) trào lưu; (c) snapshot | `core/solver.py` (a), `core/snapshot.py` (c) | `::test_ramp_source`, `test_snapshot.py::test_case_level_snapshot_roundtrip` | Một phần — (b) cần trào lưu (F6-07); tiêu chí xác lập ≤ 0,5 s kiểm ở TC-02 |
| S-09 | Snapshot, chạy tiếp sai lệch < 1e-9 | `core/snapshot.py` | `test_snapshot.py::test_continue_from_snapshot_matches_continuous_run` | Đạt (trùng từng bit) |
| S-10 | Multiple run song song từ snapshot | `studies/sweep.py`, `vnemt sweep` | `tests/validation/test_tc03_tc09.py::test_tc09_fifty_faults_from_snapshot`, `tests/systems/test_events.py::test_sweep_helpers` | Đạt — 50 lần chạy khoảng 3,5 phút (6 tiến trình), không phụ thuộc số tiến trình |
| S-11 | Van hai trạng thái R_on/R_off, tùy chọn V_T + R_on | `core/switching.py` | `test_switching.py` | Đạt |
| S-12 | Thyristor: xung, I_H, t_q, phát hiện mở lại | `core/switching.py`, `EmtSolver.fire` | `tests/core/test_thyristor.py`, `test_tc01_bridge6.py::test_tc01_commutation_failure_when_tq_exceeds_extinction_time` | Đạt |
| S-13 | IGBT + diode ngược | `core/switching.py` (diode) | `test_switching.py::test_diode_bridge_*` | Một phần — diode xong, IGBT ở M5 |
| S-14 | Van có snubber RC | `power_electronics/lcc_bridge.py` | `tests/power_electronics/test_lcc_bridge.py::test_bridge_with_rc_snubbers_keeps_average_voltage` | Một phần — snubber xong; quy đổi chuỗi n thyristor ở M2b |
| Q-01 | Mỗi mô hình có kiểm thử giải tích | `tests/` | | Đạt cho R, L, C, nguồn, khóa, diode, thyristor, MBA, khối điều khiển, PLL |
| Q-02 | Tái lập < 1e-9 | | `tests/io/test_results_io.py::test_reproducible_bit_for_bit` | Đạt (trùng từng bit) |
| Q-03 | Kết quả kèm phiên bản, mã băm, tham số solver | `case.py::Case.provenance`, `io/hdf5.py` | `::test_hdf5_roundtrip_with_provenance` | Đạt |
| Q-04 | SI trong lõi | `model/netlist.py`, schema (đơn vị trong tên khóa) | | Đạt |
| Q-05 | Thông báo lỗi tiếng Việt kèm đường dẫn khóa | `errors.py`, `io/case_loader.py` | `tests/io/test_case_loader.py` | Đạt |
| Q-06 | Type hints + mypy strict, ruff, phủ `core/` ≥ 80 % | toàn bộ `src/` | CI | Đạt (phủ `core/` 95–100 %, toàn bộ 96 %) |

## HVDC LCC (F1-L, F3)

| Mã | Yêu cầu | Mã nguồn | Kiểm thử | Trạng thái |
| --- | --- | --- | --- | --- |
| F1-L01 | Cầu 6 xung, Ud khớp công thức < 1 % | `power_electronics/lcc_bridge.py` | `tests/validation/test_tc01_bridge6.py::test_tc01_alpha_sweep` | Đạt — sai lệch ≤ 0,16 % Ud0 trên dải α 0–150° (chuẩn hóa theo Ud0 vì Ud → 0 tại 90°) |
| F1-L02 | Cầu 12 xung, MBA Y/Y và Y/Δ, không còn bậc 5, 7 | `components/transformer.py`, `systems/builder.py` | `tests/core/test_transformer.py`, `tests/systems/test_builder.py::test_twelve_pulse_cancels_5th_and_7th_harmonics` | Đạt — bậc 5, 7 < 1 % I1; Ud hai cầu khớp công thức < 1 % |
| F1-L03 | EPC + PLL, lệch khoảng cách xung < 0,1° | `control/pll.py`, `control/epc.py` | `test_blocks_pll.py::test_pll_locks_to_phase_and_frequency`, `test_tc01_alpha_sweep`, `::test_tc01_firing_independent_of_time_step`, `::test_tc01_deblock_without_overvoltage` | Đạt — lệch đo được < 0,001°, không phụ thuộc Δt |
| F1-L04 | Đo μ, γ từng van; γ khớp công thức < 0,5° | `analysis/lcc.py` | `test_tc01_alpha_sweep` | Đạt — γ sai < 0,04° với α ≥ 120°. γ thực tế bị vết khía chuyển mạch chặn khi γ > ~60° − μ, nên công thức chỉ áp dụng cho nghịch lưu |
| F1-L05 | Phát hiện sự cố chuyển mạch (t_q và γ < γ_cf) | `core/switching.py`, `control/lcc.py`, `analysis/frt.py` | `test_tc01_bridge6.py::test_tc01_commutation_failure_when_tq_exceeds_extinction_time`, `test_tc03_tc09.py` | Đạt — đếm theo van, theo đợt, theo trạm |
| F1-L06 | Kháng san bằng, lọc DC | `systems/builder.py` | `test_builder.py` | Một phần — kháng san bằng xong; lọc DC ở M4 |
| F3-01…F3-03 | CC, CEA vòng kín (γ theo IEC 60633), biên dòng, VDCOL, giới hạn | `control/lcc.py`, `control/blocks.py` | `test_builder.py::test_vdcol_and_ramp`, `tests/control/test_blocks_pll.py`, `tests/validation/test_tc02_cigre.py` | Một phần — điểm làm việc CC/CEA đạt (TC-02); kiểm thử hoán đổi vai trò khi U_AC chỉnh lưu giảm cần lịch sự kiện (M3) |

## Cấu hình cực (F2, F5-01)

| Mã | Yêu cầu | Mã nguồn | Kiểm thử | Trạng thái |
| --- | --- | --- | --- | --- |
| F2-01 | Đơn cực về đất và dây kim loại hồi | `systems/builder.py`, `model/grid.py` | TC-02; `tests/validation/test_m4a_bipole.py::test_monopole_metallic_return` | Đạt |
| F2-02 | Đơn cực đối xứng VSC | — | — | Chưa (M5) |
| F2-03 | Lưỡng cực có điện cực, cân bằng/mất cân bằng | `systems/builder.py` | `::test_balanced_bipole_has_no_ground_current`, `::test_unbalanced_bipole_ground_current_is_pole_difference`, `test_events.py::test_bipole_orientation_and_pole_pole_fault` | Đạt — dòng đất 0,0 A khi cân bằng |
| F2-04 | Chuyển chế độ khi mất cực (MRTB, GRTS) | — | — | Chưa (mức M) |
| F2-05 | Hai nhóm 12 xung nối tiếp mỗi cực | — | — | Chưa (mức M) |
| F2-06 | Đường dây lưỡng cực có ghép hỗ cảm | `core/lines.py` | `test_lines.py::test_two_conductor_induced_voltage_on_open_conductor`, `test_m4a_bipole.py::test_pole_to_ground_fault_induces_voltage_on_healthy_pole` | Đạt |
| F5-01 | Hệ lưỡng cực LCC hoàn chỉnh | `cases/m4a_bipole.yaml` | `test_m4a_bipole.py` | Đạt |

## MBA, lọc, Q, sóng hài (F5)

| Mã | Yêu cầu | Mã nguồn | Kiểm thử | Trạng thái |
| --- | --- | --- | --- | --- |
| F5-02 | MBA bão hòa, OLTC | `core/switching.py` (LSAT), `core/solver.py` (nấc) | `tests/core/test_saturation_taps.py`, TC-04 | Một phần — bão hòa hai đoạn; đổi nấc lý tưởng (không mô hình điện trở chuyển tiếp) |
| F5-03 | Điều khiển nấc (α trong dải, Ud) | `control/station.py::TapChangerControl` | `test_tc04.py::test_tc04_tap_changer_brings_alpha_back_into_band` | Đạt |
| F5-04 | Lọc kép điều chỉnh, thông cao, C-type, tụ | `components/filters.py` | `test_builder.py::test_double_tuned_and_c_type_filters` | Đạt |
| F5-05 | Đóng cắt lọc theo Q, chống lặp | `control/station.py::ReactivePowerControl` | `test_tc04.py::test_tc04_filter_switching_keeps_station_q_in_band` | Đạt |
| F5-06 | THD, Dn, TIF/IT, bảng có/không lọc | `analysis/harmonics.py` | `test_analysis_harmonics.py`, `test_tc04.py::test_tc04_harmonic_table_with_and_without_filters` | Một phần — THD, Dn, bảng so sánh đạt; TIF/IT cần bảng trọng số do người dùng cung cấp |
| F5-07 | Quét tổng trở theo tần số | `analysis/freqscan.py` | `test_analysis_harmonics.py::test_frequency_scan_*` | Đạt (van coi như hở) |
| F5-08 | FRT khi đóng cắt lọc, mất nhóm lọc | sự kiện + chỉ số FRT M3 | — | Chưa có case nghiệm thu riêng |

## Sự cố và FRT (F4)

| Mã | Yêu cầu | Mã nguồn | Kiểm thử | Trạng thái |
| --- | --- | --- | --- | --- |
| F4-01 | Sự cố AC 1ph/2ph/2phg/3ph, R và X, cắt tại dòng qua 0 | `systems/events.py` | `tests/systems/test_events.py::test_ac_fault_expansion_kinds`, `::test_fault_from_snapshot_matches_continuous_run` | Đạt |
| F4-02 | Sụt áp có kiểm soát | `systems/events.py`, `core/solver.py` (bộ nhân nguồn) | `::test_source_modulation_dips_amplitude`, TC-03 | Đạt |
| F4-03 | Sự cố DC cực–đất, cực–cực | `systems/events.py` | `::test_dc_fault_picks_nearest_line_node`, `::test_bipole_orientation_and_pole_pole_fault`, `test_m4a_bipole.py::test_pole_to_ground_fault_induces_voltage_on_healthy_pole` | Đạt — vị trí tại nút của mô hình đường dây (Bergeron: hai đầu; chia đoạn để sự cố giữa tuyến) |
| F4-04 | Ngắn mạch van, kích nhầm | `systems/events.py`, `EmtSolver.fire` | `::test_misfire_drops_one_pulse` | Một phần — ngắn mạch van và mất xung xong; ngắn mạch qua cầu dùng `ac_fault` với danh sách nút |
| F4-05 | Sự cố trong MMC | — | — | Chưa (M5) |
| F4-06 | Lịch sự kiện | `systems/events.py`, schema `events` | `::test_dip_setpoint_and_misfire_expansion` | Đạt (đóng cắt, sự cố, điểm đặt Id_ref); đóng cắt lọc ở M4 |
| F4-07 | Force retard, khử ion, khởi động lại | `control/lcc.py::LccRectifierControl` | thử thủ công (docs/design/M3.md 3.2) | Một phần — chạy đúng chuỗi; phát hiện không phân biệt CF nghịch lưu nên mặc định tắt; **chưa có kiểm thử tự động** |
| F4-08 | CFPREV | `control/lcc.py::LccInverterControl` | `test_tc03_tc09.py::test_tc03_cf_counted_and_reduced_by_cfprev` | Đạt theo tiêu chí TC-03 (giảm tổng CF 36 → 22); không tránh được đợt CF đầu |
| Chỉ số FRT | CF, phục hồi 90 % P (công suất trung bình một chu kỳ), đỉnh Id/Ud, U_AC, đạt/không đạt theo `criteria` | `analysis/frt.py` | `::test_frt_metrics_on_synthetic_record` | Đạt — phục hồi 205–264 ms sau sụt áp 10–30 % (docs/design/M3.md mục 4) |

## Dữ liệu vào/ra

| Mã | Yêu cầu | Mã nguồn | Kiểm thử | Trạng thái |
| --- | --- | --- | --- | --- |
| 9.1 | Case YAML + JSON Schema, lỗi theo đường dẫn khóa | `io/schema/case.schema.json`, `io/case_loader.py` | `tests/io/test_case_loader.py` | Một phần — `circuit` kiểm chặt; `ac_systems`, `converter_stations`, `dc_network`, `events` chỉ kiểm kiểu (chặt dần từ M2) |
| 9.2 | HDF5 + metadata | `io/hdf5.py` | `tests/io/test_results_io.py` | Đạt |
| IO-01 | Xuất COMTRADE 1999/2013, ASCII và nhị phân, kênh analog và số | `io/comtrade.py` | `tests/io/test_exchange.py::test_tc10_comtrade_roundtrip`, `::test_comtrade_status_channels_and_units` | Đạt về khứ hồi (int16: 7,6e-4 % toàn thang < 0,05 %); mở bằng Enerplot và phần mềm phân tích sự cố: **kiểm thủ công** |
| IO-02 | Nhập COMTRADE 1991/1999/2013 | `io/comtrade.py` | `::test_comtrade_read_1991_ascii_with_two_rates_and_blank_stamps` | Một phần — đọc đủ bốn dạng, nhiều tần số; chưa thử file thật của PSCAD COMTRADE Recorder; phát lại (playback) làm nguồn chưa có (M3b) |
| IO-03 | Xuất PSCAD `.out/.inf` | `io/pscad.py` | `::test_tc10_pscad_out_roundtrip`, `::test_pscad_channel_to_file_mapping_and_runs` | Đạt về cấu trúc và khứ hồi; mở bằng Enerplot: **kiểm thủ công** |
| IO-04 | Nhập `.out/.inf`, nhiều file, nhiều lần chạy | `io/pscad.py` | như trên | Một phần — chưa thử file do PSCAD sinh ra |
| IO-05 | Nhập `.psout` qua `mhi-psout` | `io/pscad.py::read_psout` | `::test_psout_reports_missing_package` | Chưa — chỉ báo lỗi hướng dẫn; cần máy có `mhi-psout` và file mẫu |
| IO-06 | So sánh dạng sóng | `analysis/compare.py`, `vnemt compare` | `::test_compare_metrics_against_known_differences`, `::test_cli_convert_and_compare` | Đạt |
| IO-07 | CSV, HDF5, `.mat` | `io/csvfile.py`, `io/hdf5.py`, `io/matfile.py` | `::test_mat_csv_hdf5_roundtrip` | Đạt (mở bằng MATLAB/Octave: kiểm thủ công) |

## Mô hình dữ liệu dùng chung (SPEC-phan-tich-luoi 2.1)

| Mục | Mã nguồn | Trạng thái |
| --- | --- | --- |
| Netlist mức mạch, định danh nút dạng chuỗi, không phụ thuộc lõi giải | `model/netlist.py` | Đạt |
| Mô hình mức hệ thống (hệ AC Thevenin, trạm LCC, đường dây DC) + mở rộng sang Netlist | `model/grid.py`, `systems/builder.py` | Một phần — dùng cho EMT; bus-branch đầy đủ (nút, nhánh AC, máy phát, tải) bổ sung ở v0.4 |

## Case nghiệm thu

| Mốc / Case | Nội dung | Kết quả |
| --- | --- | --- |
| M0 | `vnemt run cases/m0_rlc_series.yaml` | Đạt — `tests/test_cli.py`, CI |
| M1 | V1, V2 cho mạch thụ động và chỉnh lưu diode (`cases/m1_diode_bridge.yaml`) | Đạt — Ud sai lệch < 1 % so với công thức, μ sai lệch < 0,5°, hội tụ khi giảm Δt; S-02 đạt theo SPEC r3 |
| TC-01 | Cầu 6 xung quét α 0–150° (`cases/tc01_bridge6.yaml`) | Đạt — Ud, α, μ, γ, khoảng cách xung, CF |
| TC-02 | Hệ LCC kiểu CIGRE, cấu hình VnEMT (`cases/tc02_cigre_lcc.yaml`, SPEC r4) | Đạt — Id 1,000 pu, γ 15,00°, α 14,6°, P 983 MW, xác lập ≈ 0,8 s; TC-02b (CIGRE nguyên bản) chờ số liệu gốc |
| TC-10 | Xuất/nhập kết quả | Đạt phần tự động (sai lệch ≤ 7,6e-4 % toàn thang); mở bằng Enerplot cần kiểm thủ công |
| TC-03 | Sụt áp nghịch lưu 10–30 % | Đạt — CF được đếm; CFPREV giảm tổng CF; phục hồi 90 % P ≤ 300 ms (205–264 ms) |
| TC-09 | 50 sự cố từ snapshot | Đạt — bảng chỉ số đầy đủ, tái lập |
| TC-04 | Lưỡng cực có OLTC, lọc, điều khiển Q, bảng sóng hài | Đạt (lưới chỉnh lưu SCR 5; với SCR 2,5 OLTC mất tác dụng, xem docs/design/M4.md mục 5) |
| TC-05…TC-08 | | Chưa |
