---
name: restaurant
description: "Playbook đặt bàn / đặt chỗ nhà hàng, quán ăn. Dùng khi người dùng muốn đặt bàn, đặt chỗ, book bàn, tìm quán ăn (lẩu, nướng, hải sản, buffet, lẩu hàn...) theo khu vực để ăn tại chỗ, đặt tiệc / liên hoan. Thường kèm loại món + khu vực (quận/thành phố) + thời gian + số người. KHÔNG dùng cho giao đồ ăn tận nơi (GrabFood/ShopeeFood), đặt vé hay đặt phòng khách sạn."
---

# Playbook: Đặt bàn nhà hàng

## Khi nào dùng
Người dùng muốn tìm một nhà hàng/quán ăn theo tiêu chí rồi đặt bàn để ăn tại
chỗ. Mục tiêu: đi tới bước xác nhận đặt bàn / đặt cọc, rồi **DỪNG** — không
thanh toán thật.

## Thông tin cần có (thiếu thì hỏi qua ask_user)
- Loại món / kiểu quán (lẩu hàn, hải sản, buffet, nướng...)
- Khu vực (quận + thành phố)
- Thời gian (ngày + khung giờ)
- Số người
- Ngân sách / người (nếu có)
- Dịp đặc biệt (sinh nhật, hẹn hò, tiếp khách) — ảnh hưởng kiểu quán

> Nếu **không có quán hợp tiêu chí ở đúng khu vực**, đừng bỏ cuộc: gọi `ask_user`
> hỏi người dùng có chấp nhận **quận lân cận** (hoặc loại món tương tự) không, rồi
> làm theo.

## Trang nên dùng
1. **PasGo** (pasgo.vn) — chuyên đặt bàn VN, nhiều ưu đãi, có nút "Đặt bàn".
2. **TheFork** / **Google Maps** — tìm quán + xem review + đặt hoặc lấy số gọi.
3. **Foody / ShopeeFood** — tham khảo đánh giá, đặt bàn nếu quán có hỗ trợ.

Ưu tiên trang có nút đặt bàn online; nếu chỉ có số điện thoại thì báo lại.

## Quy trình (mục tiêu từng bước — KHÔNG bám selector cứng)
1. Mở trang đã chọn, tìm theo **loại món + khu vực**.
2. Lọc theo tiêu chí (đánh giá, khoảng giá, còn nhận đặt).
3. Nếu không có quán hợp ở khu vực → `ask_user` (chấp nhận lân cận / đổi món?).
4. Chọn một quán hợp tiêu chí. Nhiều quán ngang nhau → `ask_user` đưa 2-3 lựa chọn.
5. Mở chức năng đặt bàn → chọn ngày, giờ, số người.
6. Nhập thông tin đặt chỗ (tên, SĐT liên hệ — hỏi người dùng nếu chưa có).
7. Tới bước xác nhận đặt bàn / đặt cọc thì **DỪNG**, báo lại đã chọn quán nào,
   khung giờ, số người.

## Friction hay gặp & cách xử lý
- **Quán không hỗ trợ đặt online**: báo lại tên + số điện thoại để người dùng tự gọi.
- **Hết chỗ khung giờ mong muốn**: `ask_user` xem đổi giờ / đổi ngày được không.
- **Bắt đăng nhập**: thử tiếp tục dạng khách; bắt buộc thì báo lại, KHÔNG tự tạo tài khoản.
- **Popup / cookie**: đóng (từ chối cookie không cần thiết) rồi tiếp tục.

## Điểm DỪNG (bắt buộc)
Dừng ở bước xác nhận đặt bàn / màn hình đặt cọc. KHÔNG nhập số thẻ, KHÔNG thanh
toán thật. Báo lại kết quả để người dùng tự xác nhận.
