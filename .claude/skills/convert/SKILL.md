---
name: convert
description: Chuyển đổi kết quả hoặc mô hình giữa VnEMT và PSCAD, COMTRADE, MATLAB, PSS/E và các định dạng khác theo SPEC mục 9.3
argument-hint: "<file nguồn> <định dạng đích: comtrade|pscad_out|mat|csv|pscad_project|vnemt>"
disable-model-invocation: true
---

Chuyển đổi: nguồn `$0` sang định dạng `$1`.

Giao cho subagent `interop-engineer`:
1. Xác định loại file nguồn (kết quả hay mô hình) và yêu cầu IO-xx tương ứng trong `docs/SPEC-v0.1.md` mục 9.3.
2. Nếu bộ chuyển đổi đã có trong `src/vnemt/io/`: chạy nó, ghi ra file mới trong `results/converted/` (không ghi đè file gốc).
3. Nếu chưa có: báo cho người dùng yêu cầu IO nào còn thiếu và đề xuất triển khai, chờ xác nhận.
4. Với chuyển mô hình: kèm báo cáo mức trung thực L1–L4 và danh sách phần tử bỏ qua.
5. Với kết quả: đọc lại file vừa ghi và báo sai lệch so với nguồn.
