---
name: trip
description: "Playbook lên kế hoạch du lịch / lịch trình đi chơi. Dùng khi người dùng muốn lên plan / lịch trình du lịch, gợi ý lịch trình X ngày Y đêm ở một địa điểm, rủ nhau đi chơi / đi phượt, tư vấn nên đi đâu chơi gì ăn gì. Đây là playbook NGHIÊN CỨU + TỔNG HỢP (ra lịch trình + chi phí), có thể nối sang playbook flight để đặt vé. KHÔNG dùng cho việc chỉ đặt một vé máy bay hoặc một khách sạn đơn lẻ."
---

# Playbook: Lên kế hoạch du lịch

## Khi nào dùng
Người dùng muốn một **lịch trình** đi chơi: nghiên cứu điểm đến, gợi ý chỗ chơi /
ăn / ở / di chuyển, dựng lịch theo ngày, ước tính chi phí. Kết quả là một **bản
kế hoạch** — không cần thanh toán; nếu người dùng muốn đặt thật thì chuyển sang
playbook tương ứng (vd `flight` cho vé máy bay).

## Thông tin cần có (thiếu thì hỏi qua ask_user)
- Điểm đến (và điểm xuất phát)
- Ngày đi / số ngày - số đêm
- Số người + thành phần (gia đình có trẻ nhỏ / nhóm bạn / cặp đôi)
- Ngân sách tổng (hoặc /người)
- Sở thích: biển, núi, ẩm thực, check-in, nghỉ dưỡng, vui chơi...
- Phương tiện dự kiến (máy bay / xe / tự lái)

## Trang nên dùng
1. **Google Search + Google Maps** — điểm tham quan, review, khoảng cách giữa các điểm.
2. **TripAdvisor / Foody** — quán ăn, điểm đến theo đánh giá.
3. **Booking / Agoda / Traveloka** — tham khảo khách sạn & giá.
4. Blog du lịch (cẩm nang, lịch trình mẫu) để lấy ý tưởng.

## Quy trình (mục tiêu từng bước)
1. Xác nhận đủ thông tin ở trên; thiếu thì `ask_user`.
2. Nghiên cứu điểm đến: lập danh sách điểm chơi / ăn / ở phù hợp sở thích & ngân sách.
3. Gom theo khu vực để giảm di chuyển; dựng lịch trình theo từng ngày
   (sáng / trưa / chiều / tối): đi đâu, ăn gì, nghỉ ở đâu.
4. Ước tính chi phí (đi lại, ăn ở, vé tham quan) so với ngân sách; nếu lệch nhiều
   → `ask_user` điều chỉnh (rút ngắn / đổi mức khách sạn...).
5. Trình bày lịch trình rõ ràng, dễ đọc.
6. Hỏi người dùng có muốn **đặt vé / đặt phòng luôn** không. Nếu có vé máy bay →
   chuyển sang playbook `flight`.

## Friction hay gặp & cách xử lý
- **Thông tin mâu thuẫn giữa các nguồn**: ưu tiên nguồn mới / uy tín, nêu rõ nếu chưa chắc.
- **Quá nhiều lựa chọn**: `ask_user` về sở thích để thu hẹp thay vì liệt kê dàn trải.
- **Điểm đến quá xa nhau trong 1 ngày**: gom lại theo cụm địa lý, cảnh báo thời gian di chuyển.
- **Ngân sách không đủ cho mong muốn**: `ask_user` để cắt giảm hợp lý.

## Điểm DỪNG
Kết quả là **lịch trình + ước tính chi phí**. Không tự thanh toán. Khi người dùng
muốn đặt thật, chuyển sang playbook đặt (vé/phòng) và vẫn dừng trước bước trả tiền.
