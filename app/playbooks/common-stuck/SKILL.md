---
name: common-stuck
description: "KB các lỗi KẸT lặp lại của agent điều phối trình duyệt + cách gỡ đã kiểm chứng. DÀNH RIÊNG cho Agent Advisor (gpt-5) tra cứu khi gpt-4o báo kẹt — KHÔNG phải playbook use-case, KHÔNG dùng để định tuyến."
---

# Các lỗi KẸT thường gặp & cách gỡ (cho Agent Advisor)

Mỗi mục: **DẤU HIỆU → CÁCH GỠ** cụ thể (hành-động-được theo element đánh số của browser-use).
Khớp dấu hiệu trước rồi đưa đúng cách gỡ; nhiều mục khớp thì gộp ngắn gọn.

## 1. Field tự RESET về mặc định (Traveloka: điểm đến → "Bangkok")
DẤU HIỆU: đã nhập điểm đến đúng, sau khi sửa field khác (ngày / loại chuyến) thì điểm đến nhảy về
Bangkok hoặc giá trị lạ; màn kết quả/thanh toán ra sai tuyến.
GỠ: Nhập điểm đi/điểm đến **CUỐI CÙNG**, ngay trước khi bấm Tìm. Gõ xong phải **click chọn mục trong
dropdown gợi ý** (không bỏ lửng). Trước khi bấm Tìm, đọc lại 2 ô xác nhận đúng. Nếu vẫn reset: nhập
lại rồi bấm Tìm NGAY, đừng đụng field nào khác nữa.

## 2. Date-picker không nhận ngày / tự reformat / sai năm (2023)
DẤU HIỆU: gõ ngày vào ô → ô reformat sai; lịch hiện sai tháng/năm; "set nhiều lần không đúng".
GỠ: **ĐỪNG gõ số vào ô ngày.** Click ô ngày để **mở lịch**, dùng mũi tên ‹ › (Next/Prev tháng) tới đúng
**Tháng + NĂM** (vd Tháng 6 / 2026), rồi **click trực tiếp số ngày (10)** trong lưới. Click xong lịch
thường tự đóng — đọc lại ô ngày xác nhận. Lịch không mở thì click đúng ô hiển thị ngày (không phải nhãn).

## 3. Nút "Select / Chọn / Tiếp tục" bấm mà KHÔNG có gì xảy ra (lặp click)
DẤU HIỆU: click cùng một nút / cùng index nhiều lần, trang không đổi ("repeated attempts unsuccessful").
GỠ: (a) **cuộn nút vào giữa màn hình** rồi click lại (có thể bị che / ngoài viewport); (b) click vào **cả
HÀNG/THẺ chuyến bay** thay vì nút nhỏ; (c) có thể phải **chọn hạng vé (fare) / mở rộng** trước khi nút
hoạt động; (d) **chờ 1-2s** cho trang settle rồi click; (e) vẫn không ăn sau 2 lần → thử element kế bên /
nút "Tiếp tục"/"Continue" khác.

## 4. Popup đăng nhập / cookie / khuyến mãi che thao tác
DẤU HIỆU: overlay che form, click bị "nuốt".
GỠ: Đóng popup trước (X / "Để sau" / "Skip" / từ chối cookie không bắt buộc) rồi mới thao tác. KHÔNG đăng nhập.

## 5. Lặp vô ích / kẹt cùng một bước ≥3 lần
DẤU HIỆU: cùng goal/eval lặp lại, không tiến triển.
GỠ: DỪNG lặp. ĐỔI CHIẾN LƯỢC: (a) đổi cách tương tác (picker thay vì gõ; click khối thay vì nút nhỏ);
(b) cuộn/đợi; (c) nếu đang ở web hãng khó (vietjetair) → **chuyển sang Traveloka** làm lại; (d) không qua
được thì tóm tắt trạng thái rồi dừng — đừng đốt thêm step.

## 6. Trang chưa load xong → thao tác trượt
DẤU HIỆU: click/nhập ngay sau điều hướng nhưng element chưa sẵn sàng / index lệch.
GỠ: chờ trang ổn định (spinner biến mất / nội dung chính hiện) rồi mới thao tác; ưu tiên ô tìm kiếm +
gợi ý thay vì đoán toạ độ.
