---
name: spec-trace
description: Rà soát ma trận truy xuất giữa yêu cầu SPEC, mã nguồn và kiểm thử của VnEMT
disable-model-invocation: true
---

Rà soát truy xuất yêu cầu.

1. Trích toàn bộ mã yêu cầu (S-xx, F1-…F8-…, P-xx, Q-xx) từ `docs/SPEC-v0.1.md`.
2. Với mỗi mã: tìm trong `src/` (docstring, comment) và `tests/` (tên test, marker `@pytest.mark.req("F1-L01")`).
3. Ghi `docs/traceability.md`: mã | mô tả ngắn | ưu tiên | file mã | file kiểm thử | trạng thái (chưa làm / có mã / có kiểm thử / đã nghiệm thu).
4. Báo cho người dùng: tỷ lệ yêu cầu bắt buộc (B) đã có kiểm thử, danh sách yêu cầu B chưa có mã.
