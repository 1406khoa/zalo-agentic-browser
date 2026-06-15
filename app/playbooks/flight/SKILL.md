---
name: flight
description: "Playbook đặt vé máy bay. Dùng khi người dùng muốn đặt vé / book vé / mua vé máy bay, tìm chuyến bay, bay từ X đi Y, vé khứ hồi / một chiều, đi công tác hoặc về quê bằng máy bay; thường kèm tên hãng (Vietnam Airlines, Vietjet, Bamboo) hoặc thành phố/sân bay + ngày bay. KHÔNG dùng cho đặt tàu hỏa, xe khách hay khách sạn."
---

# Playbook: Đặt vé máy bay

## Khi nào dùng
Người dùng muốn tìm & đặt vé máy bay (nội địa hoặc quốc tế). Mục tiêu: đi tới
bước nhập thông tin hành khách / màn hình thanh toán, rồi **DỪNG** — không thanh
toán thật.

## Thông tin cần có (thiếu thì hỏi qua ask_user)
Trước khi mở trình duyệt, đảm bảo đã rõ các mục dưới. Thiếu cái nào thì gọi
`ask_user` hỏi gọn (gộp vào một câu nếu thiếu nhiều), rồi mới bắt đầu:
- Điểm đi & điểm đến (thành phố hoặc sân bay). **LƯU Ý CHIỀU**: "đi/ra/vào/đến X"
  nghĩa là X là **ĐIỂM ĐẾN** (KHÔNG phải điểm đi) — tuyệt đối đừng đảo chiều. Nếu
  người dùng không nói điểm đi, HỎI điểm đi qua `ask_user` (gợi ý mặc định nơi họ ở).
- **Loại chuyến: MỘT CHIỀU hay KHỨ HỒI** — nếu người dùng chưa nói rõ thì HỎI
  (`ask_user`), ĐỪNG tự mặc định. Nếu khứ hồi thì hỏi thêm ngày về.
- Ngày đi (xác nhận đúng ngày; ngày về nếu khứ hồi)
- Số hành khách (người lớn / trẻ em)
- Hãng ưu tiên (Vietnam Airlines / Vietjet / Bamboo / hay "rẻ nhất")
- Ưu tiên khác nếu có: giờ bay (sáng/tối/sớm nhất), hạng vé, mức giá

## ⚡ LỐI TẮT URL (ƯU TIÊN #1 — Traveloka): điều hướng thẳng, KHỎI date-picker
Date-picker Traveloka hay tự reset ngày/điểm đến → đặt NHẦM ngày. Né hẳn: **DỰNG URL
tìm kiếm từ yêu cầu user rồi `navigate` THẲNG** — tuyến + ngày nằm sẵn trong URL nên
không cần đụng date-picker:

    https://www.traveloka.com/en-vn/flight/fullsearch?ap=<ĐI>.<ĐẾN>&dt=<DD-MM-YYYY>&ps=<NL>.<TE>.<EB>&sc=ECONOMY

- `ap` = 2 mã sân bay 3 chữ ngăn bởi DẤU CHẤM, vd `SGN.HAN`.
- `dt` = ngày đi `DD-MM-YYYY`, vd `10-06-2026`. Khứ hồi: `dt=10-06-2026.15-06-2026`.
- `ps` = NgườiLớn.TrẻEm.EmBé, vd `1.0.0`. `sc` = `ECONOMY` (hoặc `BUSINESS`).

Mã sân bay hay dùng: HCM/Sài Gòn=**SGN** · Hà Nội=**HAN** · Đà Nẵng=DAD · Nha Trang/Cam Ranh=CXR
· Phú Quốc=PQC · Hải Phòng=HPH · Cần Thơ=VCA · Huế=HUI · Đà Lạt=DLI · Vinh=VII · Quy Nhơn=UIH
· Bangkok=BKK · Singapore=SIN · Seoul=ICN · Tokyo=NRT.

VD "HCM ra Hà Nội 10/6/2026, 1 người, một chiều" → `navigate`:
`https://www.traveloka.com/en-vn/flight/fullsearch?ap=SGN.HAN&dt=10-06-2026&ps=1.0.0&sc=ECONOMY`
→ đóng popup nếu có → sang bước LỌC HÃNG + CHỌN (Quy trình). Không rõ mã sân bay (thành phố lạ)
→ mới dùng form/date-picker thường.

## Trang nên dùng
1. **Traveloka** — ưu tiên #1, dùng LỐI TẮT URL ở trên (kể cả khi user nêu tên hãng → lọc hãng sau).
2. **Trang của hãng** (vietjetair.com…) — CHỈ khi user nói RÕ "đặt trên web hãng X". SPA khó → tránh.
3. **Google Flights** — so giá nhanh rồi quay về (1).

## Quy trình (mục tiêu từng bước — KHÔNG bám selector cứng)
1. **Dựng + `navigate` URL Traveloka** (lối tắt trên) đúng tuyến/ngày/khách. (Không dựng được mới dùng form;
   nếu dùng form: tránh "TP.HCM" → gõ "Ho Chi Minh"; chọn loại chuyến TRƯỚC; nhập điểm đến CUỐI cùng.)
2. Đóng popup đăng nhập / khuyến mãi nếu có (ở chế độ khách).
3. **Lọc hãng** nếu user nêu (tick vd "Vietjet" trong bộ lọc Hãng); lọc "Bay thẳng" nếu muốn.
4. **CHỌN CHUYẾN ĐẦU TIÊN — ĐỪNG so giá, ĐỪNG mở "Flight Details".** Web sắp GIÁ RẺ NHẤT lên đầu →
   chỉ bấm **"Choose"/"Chọn"** ngay trên chuyến đầu. **TUYỆT ĐỐI KHÔNG lặp mở/đóng panel chi tiết.**
   Chỉ lọc thêm theo giờ/giá khi user yêu cầu cụ thể.
5. Màn **"Select ticket type / Chọn loại vé"**: mỗi THẺ hạng vé (Economy 1.6xx.xxx đ, Eco, Deluxe…)
   có **nút XANH "Select"/"Chọn" ở ĐÁY thẻ** — click ĐÚNG nút đó ở **thẻ ĐẦU (rẻ nhất)**.
   **ĐỪNG click**: giờ bay (vd "22:15"), ô **tiền tệ** (KRW/USD/GBP…), tên hãng, hay "Flight Details".
   Nếu click nút Select 2 lần không sang trang → cuộn để nút vào giữa màn hình rồi click lại; vẫn không
   thì thử nút Select ở thẻ kế. KHÔNG add-on.
6. **TRƯỚC bước hành khách/thanh toán: XÁC NHẬN tuyến + NGÀY đúng** (vd Hồ Chí Minh → Hà Nội, 10/06/2026).
   Sai ngày/tuyến → `navigate` lại URL đúng (hoặc sửa), TUYỆT ĐỐI không tiếp tục với chuyến sai.
7. Tới màn nhập thông tin hành khách / thanh toán thì **DỪNG**, báo lại chuyến (hãng, giờ, giá).

## Friction hay gặp & cách xử lý
- **Trang mặc định KHỨ HỒI** (Traveloka hay vậy): nếu user đi một chiều, bấm tab
  "Một chiều" TRƯỚC khi điền — không thì dư ô ngày về và sai giá.
- **Lịch / date-picker khó bấm**: dùng nút chuyển tháng để tới đúng tháng rồi bấm
  đúng ngày; nếu kẹt 2-3 lần → `ask_user` xác nhận lại ngày.
- **Popup khuyến mãi / chọn ngôn ngữ / cookie**: đóng lại (từ chối cookie không
  cần thiết) rồi tiếp tục.
- **Bắt đăng nhập sớm**: thử tiếp tục ở chế độ khách; nếu bắt buộc đăng nhập mới
  đi tiếp được → báo lại, KHÔNG tự tạo tài khoản.
- **Không có chuyến đúng hãng/giờ**: `ask_user` hỏi có chấp nhận hãng khác hoặc
  khung giờ khác không, rồi làm theo.
- **Bị TƯỜNG ở một site** (nút tìm chuyến báo "thiếu thông tin" dù đã điền đủ /
  date-picker tự reset / kẹt 2-3 lần ở cùng một bước): ĐỪNG lặp lại thao tác cũ —
  **CHUYỂN sang Traveloka** (nếu đang ở web hãng) và làm lại từ đầu ở đó; Traveloka
  thường vượt qua được rào này. Lịch khó thì dùng nút chuyển tháng + bấm đúng ngày,
  đừng gõ tay vào ô ngày.
- **Traveloka tự RESET điểm đến về "Bangkok"** (giá trị mặc định của nó) khi bạn
  sửa một field khác SAU khi đã nhập điểm đến → màn kết quả/thanh toán dễ ra NHẦM
  tuyến (vd SGN→BKK). Sau MỖI lần sửa field, liếc lại ô điểm đến; nếu nhảy về
  Bangkok thì nhập lại đúng (Hà Nội). Coi chừng ô NĂM cũng hay nhảy về 2023.

## Điểm DỪNG (bắt buộc)
Dừng ngay tại màn hình nhập thông tin thanh toán / nhập thẻ. KHÔNG nhập số thẻ,
KHÔNG bấm thanh toán thật. Báo lại kết quả và bước đang dừng để người dùng tự
hoàn tất khâu trả tiền.
