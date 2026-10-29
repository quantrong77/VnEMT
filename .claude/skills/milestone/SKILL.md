---
name: milestone
description: Lập kế hoạch và thực hiện một mốc phát triển VnEMT theo SPEC mục 11 (M0…M9)
argument-hint: "[M0..M9]"
disable-model-invocation: true
---

Thực hiện mốc **$ARGUMENTS** của VnEMT.

1. Đọc `docs/SPEC-v0.1.md` mục 11 (lộ trình), mục 13 (truy xuất) và các mã yêu cầu thuộc mốc $ARGUMENTS. Đọc `CLAUDE.md`.
2. Dùng subagent `emt-architect` viết ghi chú thiết kế `docs/design/$ARGUMENTS.md`: yêu cầu, giao diện, danh sách việc, mỗi việc gắn agent và mã yêu cầu.
3. Trình bày kế hoạch cho người dùng (bảng ngắn) và chờ xác nhận trước khi viết mã.
4. Sau khi được xác nhận, giao từng việc cho agent chuyên môn đúng theo bảng phân công trong `CLAUDE.md`. Việc độc lập có thể chạy song song.
5. Khi mã xong: chạy `pytest -q`, `ruff check src tests`, `mypy src`.
6. Gọi subagent `validation-engineer` kiểm chứng các case nghiệm thu của mốc (SPEC mục 10.2) và lập báo cáo.
7. Cập nhật cột trạng thái trong `docs/traceability.md` (tạo nếu chưa có). Báo cho người dùng: đã xong gì, đạt/không đạt, việc còn lại.
