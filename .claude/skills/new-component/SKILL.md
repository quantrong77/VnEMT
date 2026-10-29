---
name: new-component
description: Tạo khung một mô hình thành phần mới của VnEMT kèm docstring, kiểm thử giải tích và đăng ký vào thư viện
argument-hint: "<ten_mo_hinh> <nhom: components|power_electronics|control|grounding|systems>"
disable-model-invocation: true
---

Tạo mô hình mới: tên `$0`, nhóm `$1`.

1. Đọc giao diện phần tử trong `src/vnemt/core/element.py` (hoặc ghi chú thiết kế tương ứng) và một mô hình có sẵn cùng nhóm làm mẫu.
2. Tạo `src/vnemt/$1/$0.py` gồm: lớp mô hình, docstring nêu phương trình, giả định, tham số (đơn vị SI), nguồn tham khảo, mã yêu cầu SPEC liên quan; phương thức đóng góp ma trận G, cập nhật nguồn lịch sử, trạng thái tuần tự hóa (snapshot).
3. Tạo `tests/$1/test_$0.py`: kiểm thử đơn vị + ít nhất một kiểm thử so với lời giải giải tích.
4. Thêm khóa YAML cho mô hình vào JSON Schema và một ví dụ nhỏ trong `cases/examples/`.
5. Chạy kiểm thử của file mới và báo kết quả.
