---
name: new-case
description: Tạo file case YAML hợp lệ cho VnEMT từ mô tả bằng lời
argument-hint: "<mo ta case>"
disable-model-invocation: true
---

Tạo file case từ mô tả: $ARGUMENTS

1. Đọc schema trong `src/vnemt/io/schema/` và các case mẫu trong `cases/`.
2. Chọn số liệu: ưu tiên mô hình chuẩn CIGRE hoặc giáo trình; ghi nguồn số liệu trong khóa `meta.source`. Không dùng dữ liệu trong `private/` trừ khi người dùng chỉ định.
3. Ghi `cases/<ten>.yaml`, chạy `vnemt validate` trên file và sửa đến khi hợp lệ.
4. Nếu được yêu cầu chạy: `vnemt run`, rồi tóm tắt các đại lượng chính (Id, Ud, α, γ, P, Q) và đường dẫn đồ thị.
