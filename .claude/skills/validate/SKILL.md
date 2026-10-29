---
name: validate
description: Chạy kiểm chứng VnEMT cho một case, nhóm yêu cầu hoặc mốc và lập báo cáo đạt/không đạt
argument-hint: "<case.yaml | F1..F8 | M0..M9 | all>"
disable-model-invocation: true
---

Kiểm chứng: $ARGUMENTS

Giao việc này cho subagent `validation-engineer` với chỉ dẫn:
- Xác định yêu cầu và tiêu chí chấp nhận liên quan trong `docs/SPEC-v0.1.md` (mục 7, 8, 10).
- Chạy kiểm thử và case tương ứng, ghi lại lệnh đã chạy.
- Lập báo cáo `docs/validation/` dạng bảng: yêu cầu | tiêu chí | kết quả đo | đạt/không đạt | bằng chứng.
- Không sửa mã mô hình, không hạ tiêu chí.

Sau đó tóm tắt cho người dùng trong 5–10 dòng: số yêu cầu đạt/không đạt/chưa kiểm được và việc cần làm tiếp.
