---
name: study
description: Thiết lập và chạy một nghiên cứu lưới (trào lưu, N-1, ngắn mạch, ổn định, PV/QV, ATC, chuỗi thời gian, runback/run-up, đấu nối) theo docs/SPEC-phan-tich-luoi-v0.1.md
argument-hint: "<loại nghiên cứu> <file lưới hoặc mô tả>"
disable-model-invocation: true
---

Nghiên cứu: $ARGUMENTS

1. Xác định loại nghiên cứu và mã yêu cầu (G-, P-, O-, R-) trong `docs/SPEC-phan-tich-luoi-v0.1.md`. Nếu chức năng chưa được triển khai, báo cho người dùng mốc lộ trình tương ứng và dừng.
2. Kiểm tra dữ liệu đầu vào: file lưới (PSS/E RAW/RAWX, CGMES, YAML), kịch bản, file tiêu chí. Thiếu file tiêu chí thì hỏi người dùng; không tự đặt ngưỡng.
3. Giao việc:
   - trào lưu, N-k, ngắn mạch, PV/QV, ATC → `grid-analysis-engineer`;
   - ổn định RMS, tần số, runback/run-up → `power-system-dynamics-engineer` (runback luôn chạy cả chiều thuận và chiều ngược);
   - quy hoạch, chuỗi thời gian, đấu nối, báo cáo → `transmission-planning-engineer`.
4. Tạo file cấu hình nghiên cứu trong `studies/<ten>.yaml`, chạy, lưu kết quả trong `results/studies/<ten>/`.
5. Báo cáo Markdown tiếng Việt: dữ liệu dùng, giả định, bảng vi phạm/kết quả, kết luận. Tóm tắt cho người dùng trong 5–10 dòng.
