---
name: shopping
description: "Playbook mua sắm online. Dùng khi người dùng muốn mua / đặt mua / order / săn sale / 'tìm mua' một món hàng trên Tiki (ưu tiên), Shopee, Lazada, Uniqlo — so giá, tìm hàng rẻ / chính hãng / giao nhanh; thường kèm tên sản phẩm (áo, điện thoại, máy sấy, đồ gia dụng...) + ngân sách / màu / size / số lượng. KHÔNG dùng cho đặt vé máy bay, đặt bàn nhà hàng, đặt phòng khách sạn, đặt tour."
---

# Playbook: Mua sắm online (Tiki)

## Khi nào dùng
Người dùng muốn tìm & mua một món hàng trên sàn TMĐT. Mục tiêu: chọn ĐÚNG sản phẩm +
đúng phân loại + còn hàng → giỏ → checkout → điền thông tin giao hàng → **chọn thẻ ngân hàng** →
tới **màn nhập thẻ** rồi **DỪNG** (KHÔNG nhập thẻ, KHÔNG bấm nút đặt-đơn cuối). KHÔNG bao giờ đặt
hàng thật. **Sàn mặc định: Tiki** (duyệt ẩn danh thoải mái, ít chặn bot).
Tránh **Shopee** trừ khi user yêu cầu rõ — Shopee chặn bot rất gắt (trang `/verify/traffic/error`
+ CAPTCHA kéo-thả) ngay cả khi đã đăng nhập, dễ kẹt giữa chừng.

## Đăng nhập & TỰ GỠ RỐI (bạn là agent — cứ thử, gặp gì gỡ nấy, ĐỪNG kẹt, ĐỪNG bỏ cuộc)
Trình duyệt khởi động ở **hồ sơ KHÁCH**. Đường ĐỌC (tìm/xem sản phẩm) mở tự do; nhiều hành động
GHI (Thêm giỏ, Mua, thêm Yêu thích/wishlist, xem đơn, thanh toán…) sẽ bật yêu cầu **ĐĂNG NHẬP**.

**ĐĂNG NHẬP LÀ ĐĂNG NHẬP — gặp Ở ĐÂU cũng xử lý GIỐNG NHAU, và là việc BÌNH THƯỜNG (không phải lỗi).**
Bất kỳ lúc nào hiện form / popup / màn đăng nhập — ở giỏ hàng, ở **wishlist/Yêu thích**, ở trang tài
khoản, hay do một thông báo "vui lòng đăng nhập" — bạn CÓ tài khoản, cứ đăng nhập rồi đi tiếp:
gọi tool **`fill_login("uniqlo")`** (nó tự điền email+mật khẩu đã cấu hình — bạn không thấy giá trị)
→ **BẤM "Đăng nhập"/"Login"** → tiếp tục. Nếu chưa thấy ô mật khẩu, bấm "Đăng nhập"/"Login" để MỞ
form ra trước rồi gọi `fill_login`. (Nếu `fill_login` báo chưa cấu hình tài khoản site này → khi đó
mới dừng + báo người dùng.)

**LỠ THAO TÁC NGOÀI Ý MUỐN? GỠ RA RỒI VỀ MỤC TIÊU CHÍNH — bạn được THỬ–SAI–SỬA.** Đừng coi một cú
bấm nhầm là thất bại rồi kẹt. Ví dụ: lỡ bấm ♡ "thêm vào Yêu thích" và bị bắt đăng nhập → **đăng nhập
(fill_login) → bỏ món khỏi Yêu thích → quay lại** mở đúng sản phẩm → chọn size → Thêm vào giỏ. Mọi ngã
rẽ phụ (mở nhầm trang, popup, wishlist…) đều có đường lùi: đóng (X) / quay lại / bỏ chọn, rồi đi tiếp.

**SAU đăng nhập → nhìn lại trang:** vào được (trang thành viên / tường login biến mất) = ĐÃ login,
đi tiếp. Đừng tưởng thất bại chỉ vì vừa bấm nút.

**Chỉ DỪNG + báo người dùng ở lằn ranh THẬT SỰ ngoài khả năng** (không phải để cấm bạn — mà vì bạn
KHÔNG GIẢI ĐƯỢC): **OTP / mã xác minh / 2FA / CAPTCHA / "xác minh đó là bạn" / nhập số thẻ ngân hàng**,
và **tạo tài khoản mới**. (Điền user+pass qua `fill_login` thì ĐƯỢC — tài khoản test đã uỷ quyền.)

## ⛔ HỎI ĐỦ TRƯỚC KHI THAO TÁC (BẮT BUỘC — làm NGAY sau load_playbook, TRƯỚC mọi navigate/search)
Best practice: dồn HẾT thông tin quyết-định-mua mà ĐOÁN TRƯỚC ĐƯỢC vào **1-2 câu hỏi NGAY ĐẦU**, rồi
mới thao tác. TUYỆT ĐỐI KHÔNG search → chọn → giữa chừng mới nhận ra thiếu (rất tốn step, phải làm lại).
Nguyên tắc: hỏi **NHIỀU nhất có thể mà không gây khó chịu** (gộp vào gói), nhưng phải ĐỦ để chọn ĐÚNG món NGAY.

Các trục cần chốt TRƯỚC (bỏ trục nào KHÔNG áp dụng cho loại hàng này):
- **Sàn** (Tiki / Shopee / Lazada / Uniqlo) — mặc định Tiki nếu user không nói.
- **Loại sản phẩm** + từ khoá (vd "áo thun nam trơn").
- **Giới tính · Màu · Size** — với hàng THỜI TRANG (áo/quần/giày) HỎI NGAY Ở ĐẦU, ĐỪNG đợi tới trang sản phẩm mới hỏi.
- **Ngân sách** · **Tiêu chí** (rẻ nhất / đánh giá cao / chính hãng / giao nhanh).
- **Số lượng** (mặc định 1 — đừng hỏi).

Cách hỏi: `ask_user` với `options` = 2-3 **GÓI TRỌN VẸN** (vd "Áo thun nam · đen · size L · ≤200k · đánh giá cao"),
`options[0]` = gói đề xuất nhất. ĐỪNG hỏi lại thứ user ĐÃ nói trong yêu cầu. **Chỉ khi đã đủ thông tin → mới
navigate/search/lọc/chọn (một lần, đúng luôn).**

## ⚡ LỐI TẮT URL Tiki (ƯU TIÊN #1): điều hướng THẲNG vào kết quả
Né trang chủ + ô tìm hay bị popup. **Dựng URL tìm kiếm rồi `navigate` thẳng** (đường ĐỌC mở
tự do cho khách, không cần đăng nhập):

    https://tiki.vn/search?q=<TỪ KHOÁ>

- `q` = từ khoá; **dấu cách → `%20`** (vd `áo%20thun%20nam`).
- Tiki có thể **CHUYỂN HƯỚNG** từ khoá khớp danh mục sang trang danh mục `tiki.vn/<slug>/c<id>`
  — vẫn đúng nhóm hàng, **cứ tiếp tục** lọc & chọn ở đó.
- Trang sản phẩm dạng `tiki.vn/<slug>-p<productID>.html?spid=<sellerID>` — click thẳng từ kết quả, không cần dựng tay.

Các trục **LỌC GIÁ / chính hãng / đánh giá / giao nhanh** và **SẮP XẾP** (Bán chạy / Giá) **trên Tiki**
làm bằng **control TRÊN TRANG** (panel lọc + dropdown "Sắp xếp") — không phải tham số URL, **đừng bịa**.
**NGOẠI LỆ web hãng (Uniqlo / Adidas / Nike…):** bộ lọc thường LÀ **tham số URL** → **ƯU TIÊN** áp filter
bằng `navigate` tới URL có param (vd Uniqlo: `&priceRanges=199000-299000`, `&colorCodes=…`, `&sizeCodes=…`)
thay vì bấm dropdown lọc — nhiều dropdown là **radio tuỳ biến**: click chỉ "focus" mà KHÔNG "select" nên
kẹt. Nếu buộc dùng dropdown mà click không ăn → chuyển sang **URL param** (hoặc `evaluate`), ĐỪNG bấm lại nhiều lần.

## Quy trình từng bước (mục tiêu từng bước — KHÔNG bám selector cứng)
1. **Dựng + `navigate` URL Tiki** đúng từ khoá — CHỈ làm SAU KHI đã hỏi đủ (mục "HỎI ĐỦ TRƯỚC KHI THAO TÁC").
   Chưa đủ thông tin → quay lại hỏi, ĐỪNG navigate vội. Đóng popup nếu che màn. Đặt **Sắp xếp = Bán chạy**.
2. **Lọc theo ngân sách + tiêu chí**: đặt **GIÁ TỐI ĐA = ngân sách** (điền ô "đến"/max, để TRỐNG
   ô "từ"/min) để khớp đúng quy tắc chọn "≤ ngân sách" ở bước 3 — ĐỪNG đặt sàn dưới kẻo loại oan
   hàng rẻ hơn. Bật **chính hãng/Official** nếu user muốn, lọc **từ 4 sao** / **NOW giao nhanh** nếu user muốn.
3. **Chọn ứng viên theo QUY TẮC GIÁ**: trong các kết quả hợp tiêu chí, ưu tiên giá **GẦN ngân
   sách NHẤT nhưng ≤ ngân sách**; nếu hoà → tie-break theo **đánh giá cao / Official / đã bán nhiều**.
   Mở trang sản phẩm ứng viên #1 bằng cách **click thẳng vào ẢNH/TÊN sản phẩm** — ĐỪNG bấm nút phụ
   trên thẻ (vd "Tìm tương tự") vì dễ lạc trang.
4. **CỔNG XÁC MINH (trước khi cam kết món này)** — trên trang sản phẩm:
   - **Còn hàng?** Nếu thấy **"hết hàng" / "tạm hết"** → bỏ, quay lại chọn ứng viên kế tiếp.
   - **Đọc các TRỤC phân loại mà trang THẬT SỰ liệt kê** (Tiki hay có **Màu Sắc** + **Size**). Nếu
     trang KHÔNG hiện trục nào → **KHÔNG hỏi phân loại**, dù ví dụ dưới có nhắc màu/size. Chỉ hỏi
     về trục CÓ THẬT trên trang này.
   - Đối chiếu các trục đó với điều user ĐÃ nói. Trục nào còn thiếu mà user CHƯA chọn → sang tầng
     hỏi thứ hai (mục dưới). Nếu phân loại user muốn **không còn hàng** → coi như hết hàng, chọn ứng viên kế.
   Chỉ khi: còn hàng **VÀ** có đủ phân loại cần → mới cam kết món này.
5. **Chọn phân loại (Màu Sắc / Size) + số lượng** đúng theo yêu cầu (đã hỏi xong).

⛔ **CỔNG BẮT BUỘC — TRƯỚC khi "Thêm vào giỏ" phải qua HẾT 3 ô (chưa qua → KHÔNG được thêm):**
   1. **GIÁ ≤ NGÂN SÁCH** — giá món đang chọn ≤ ngân sách user? Vượt → BỎ, quay lại bước 3 chọn món
      khác ≤ ngân sách. ĐỪNG tự nhận "đã lọc giá" nếu chưa THỰC SỰ đặt mức GIÁ TỐI ĐA.
   2. **ĐÃ HỎI PHÂN LOẠI** — mọi trục trang hiện (Màu Sắc/Size/...) đã có giá trị do USER chọn?
      Trục nào user CHƯA nói → `ask_user` NGAY, KHÔNG tự chọn thay user.
   3. **CÒN HÀNG** — phân loại đã chọn không "hết hàng".
   Trong `memory`, ghi RÕ đã tick từng ô (vd "GIÁ 150k≤200k ✓ · đã hỏi Size ✓ · còn hàng ✓") rồi mới thêm.

6. **Thêm vào giỏ → mở giỏ hàng.** (Hành động GHI đầu tiên — gặp đăng nhập thì gọi `fill_login` rồi tiếp tục.)
   ⛔ **CỔNG BÀN-GIAO Ở GIỎ (flow người dùng muốn):** gọi
   `ask_user("Bạn muốn mình tiếp tục tới trang thanh toán không?", ["Có, tới trang thanh toán", "Không, dừng ở giỏ hàng"])`.
   - **"Không, dừng ở giỏ hàng"** → **DỪNG NGAY** tại giỏ (engine tự kèm tóm tắt + ảnh + link giỏ).
   - **"Có, tới trang thanh toán"** → bấm "Thanh toán"/"Mua hàng"/"Checkout" vào trang thanh toán → làm tiếp tới **màn nhập thẻ** rồi DỪNG (xem "Điểm DỪNG + GIỮ PHIÊN").
7. **Điền thông tin giao hàng**: nếu trang đòi địa chỉ mà hồ sơ CHƯA có → **BẮT BUỘC gọi `ask_user`**
   xin **địa chỉ đầy đủ** (tên · SĐT · tỉnh/thành · quận/huyện · phường/xã · số nhà-đường) rồi tự nhập.
   Đây là thông tin **THIẾT YẾU** — cứ hỏi (KHÔNG bị giới hạn số lần hỏi), **TUYỆT ĐỐI KHÔNG bịa** PII,
   KHÔNG bỏ qua, KHÔNG kẹt. Có thông tin user trả lời rồi MỚI nhập. Với ô **tỉnh/quận/phường
   là dropdown NHIỀU CẤP**: **click MỞ từng cấp → click CHỌN mục trong danh sách — ĐỪNG GÕ vào dropdown**
   (chỉ gõ nếu có ô tìm kiếm RÕ RÀNG bên trong nó); làm TUẦN TỰ tỉnh → quận → phường (chọn cấp trên xong cấp
   dưới mới hiện). Số nhà/đường gõ vào ô địa chỉ thường.
   Đọc lại xác nhận địa chỉ ĐỦ các cấp rồi mới bấm "Giao đến địa chỉ này". (Đừng bịa PII người thật; dùng đúng
   dữ liệu user cấp.)
8. **Phần thanh toán — TUYỆT ĐỐI KHÔNG nhận / KHÔNG nhập thông tin nhạy cảm (số thẻ · CVV · OTP).**
   Phương thức **không cần thẻ** (COD / ví / phương thức đã lưu) → cứ chọn theo ý người dùng, làm bình thường.
   Nhưng tới bước **cần SỐ THẺ / CVV** → **TỪ CHỐI nhận**, nói NGUYÊN VĂN:
   *"Mình không được phép nhận thông tin thẻ/nhạy cảm của bạn. Vui lòng tự thao tác khâu thanh toán qua link mình gửi bên dưới nhé."*
   → rồi DỪNG + sang "Điểm DỪNG + GIỮ PHIÊN" (engine kèm link + ảnh). **KHÔNG hỏi xin số thẻ, KHÔNG gõ số thẻ
   — kể cả khi người dùng chủ động đưa.** (Phần không-nhạy-cảm của form — tên, địa chỉ — vẫn điền theo dữ liệu user.)
10. ⛔ **CỔNG VOUCHER / MÃ GIẢM GIÁ (nếu trang CÓ) — tinh ý như nhân viên sale, nhưng KHÔNG hỏi dồn:**
    ở giỏ/checkout nếu thấy mục **mã giảm giá / voucher / khuyến mãi / "Phiếu giảm giá (N)" / ưu đãi**:
    - **Có voucher KHẢ DỤNG sẵn** (vd "Phiếu giảm giá (1)", danh sách ưu đãi áp được, nút "Áp dụng ưu đãi tốt
      nhất") → MỞ và **ÁP cái tốt nhất áp được** (giảm nhiều nhất). AN TOÀN — trước thanh toán, có xác nhận
      cuối, KHÔNG phải nút đặt-đơn → cứ áp. Đọc lại TỔNG sau khi giảm.
    - **Chỉ có ô NHẬP MÃ** (không có voucher sẵn) và user CHƯA đưa mã → interactive: hỏi GỌN đúng 1 câu
      "Bạn có mã giảm giá không?"; không có thì bỏ qua. Chế độ "tự lo"/autonomous → BỎ QUA, đừng hỏi.
    - Trang KHÔNG có mục voucher → BỎ QUA hẳn (đừng hỏi, đừng đi săn mã). Voucher chỉ xử lý **MỘT lần**.
11. **Bước trả tiền — XIN PHÉP rồi mới chốt.** Tới sát nút đặt-đơn/trả-tiền cuối → gọi
    `ask_user("Chốt đơn và trả tiền {sản phẩm · phân loại · SL · giá · địa chỉ · phương thức}? [Có / Không]")`.
    - **CÓ** + phương thức **không cần thẻ** (COD / ví / đã lưu) → bạn ĐƯỢC bấm đặt-đơn / hoàn tất (cổng mở sau khi user đồng ý).
    - **CÓ** nhưng **cần số thẻ** → **TỪ CHỐI nhận thẻ** (bước 8): báo "không được phép nhận thông tin nhạy cảm, bạn tự thao tác qua link" → dừng + bàn giao.
    - **KHÔNG** → DỪNG, không bấm gì thêm. **Dừng ở đâu hoàn toàn do NGƯỜI DÙNG quyết.**
    Rồi sang **"Điểm DỪNG + GIỮ PHIÊN"**.

## Hỏi người dùng: NGƯỠNG theo TÁC ĐỘNG (đây là phần quan trọng nhất)
Chỉ hỏi những gì **đổi MÓN/PHÂN LOẠI sẽ mua**, hoặc thứ mà nếu chọn sai user sẽ **từ chối kết
quả**. Những lựa chọn nhỏ, gần như nhau → **TỰ QUYẾT**, đừng hỏi.
- **TẦNG 1 — trước search** (gộp 1 câu): sàn / loại / giới tính nếu áp dụng / ngân sách / tiêu chí.
- **TẦNG 2 — trên trang sản phẩm**: hỏi về **trục phân loại mà trang LIỆT KÊ ra và user CHƯA
  nói** (vd áo lộ ra "Màu Sắc" + "Size" → user mới chỉ nói màu → hỏi **size**). TRANG là nguồn
  sự thật cho việc nên hỏi gì — KHÔNG dùng danh sách câu hỏi cứng theo loại hàng.
- **TỰ QUYẾT (không hỏi)**: hai shop giá sát nhau → chọn Official / điểm cao hơn; số lượng mặc
  định 1; màu/biến thể mà user đã nêu rõ.
- **DÀNH câu hỏi cho ngã rẽ thật**: hết hàng → hỏi phương án thay thế; hai ứng viên KHÁC HẲN
  nhau (vd hai model khác nhau) → đưa 2-3 lựa chọn cho user.

Giới hạn: **tương tác = tối đa 3 câu** — thiết kế đường chuẩn ~2 câu (1 ở tầng 1, 1 ở tầng 2),
chừa câu thứ 3 cho ngã rẽ. **Chế độ "tự lo" = tối đa 1 câu**: tự chọn default hợp lý (Official, biến
thể phổ biến, số lượng 1) rồi báo cáo ở cuối. NGOẠI LỆ: quy tắc giá CẦN ngân sách — nếu user KHÔNG
cho ngân sách, dùng đúng 1 câu đó để hỏi ngân sách; hoặc nếu không hỏi thì BỎ lọc giá, xếp theo
bán-chạy/đánh-giá và **nói rõ đã bỏ qua lọc giá** khi báo cáo.

## Friction hay gặp & cách xử lý
- **Popup voucher / mã giảm / thông báo / chọn vị trí giao**: đóng (X / "Để sau") rồi tiếp tục.
- **Chọn 1 mục radio / voucher / bộ lọc** (kiểu "◉ Tên lựa chọn"): **bấm vào TÊN/CHỮ của lựa chọn**
  (vd tên voucher "Chúc Mừng Sinh Nhật"), **ĐỪNG bấm vòng tròn rỗng** bên cạnh. Bấm vòng tròn thường
  chỉ *focus* mà KHÔNG chọn (radio tùy biến — đã trace: click cái dot rỗng → không select; click chữ → select).
- **Cần đăng nhập / lỗi tải giỏ** ("Không tải được giỏ hàng", "đã xảy ra lỗi", tường login): **MỞ form
  đăng nhập** (bấm "Đăng nhập"/"Login"; thử 2-3 lần nếu là lỗi tải) → gọi **`fill_login("<site>")`** để
  điền user+pass → bấm "Đăng nhập". `fill_login` báo chưa cấu hình tài khoản → DỪNG + báo, đừng tự gõ tay.
- **Sau bấm login**: kiểm tra lại — nếu đã vào (trang thành viên/tài khoản, hết tường) → ĐÃ login, **tiếp tục mua** (đừng tưởng fail).
- **Lằn ranh cứng**: **OTP / 2FA / CAPTCHA / "xác minh đó là bạn" / số thẻ**, hoặc **"tạo tài khoản"** →
  **DỪNG, không tự giải, không tạo acc** → báo. (Điền user+pass qua `fill_login` thì ĐƯỢC — tài khoản test đã uỷ quyền.)
- **CAPTCHA / reCAPTCHA / "tôi không phải robot"**: KHÔNG tự giải → báo người dùng.
- **"hết hàng" / hết phân loại mong muốn**: bỏ ứng viên đó, sang ứng viên kế; nếu cả loạt đều
  hết → `ask_user` hỏi nới tiêu chí (đổi màu/size/ngân sách).
- **Bị chuyển sang trang danh mục `/c<id>`** (Tiki tự map từ khoá): vẫn đúng nhóm hàng — cứ lọc
  & chọn ở đó. Chỉ khi kết quả lệch hẳn (sai loại, toàn phụ kiện) mới sửa từ khoá cụ thể hơn rồi search lại.
- **Lọc giá / sắp xếp không nhận / kẹt 2-3 lần ở cùng bước**: đổi cách (dùng dropdown thay vì gõ
  ô), đừng lặp; vẫn kẹt → `ask_expert`.

## Điểm DỪNG + GIỮ PHIÊN (DO NGƯỜI DÙNG QUYẾT — không có điểm dừng cứng, không tự đóng trình duyệt)
**Không có điểm dừng cố định** — bạn đi xa tới đâu là **do người dùng quyết** qua `ask_user`:
- Ở giỏ: "tới trang thanh toán?" → Không = dừng ở giỏ.
- Ở bước trả tiền: "Chốt đơn và trả tiền?" → **Có = bạn HOÀN TẤT đơn** (đặt + trả tiền; số thẻ do user nhập) · Không = dừng trước khi trả tiền.

Dù dừng ở đâu (giỏ / trang thanh toán / từ chối nhận thẻ / đã đặt xong COD) → **GIỮ PHIÊN, KHÔNG tự đóng
trình duyệt**: gọi `ask_user` lần cuối
`("Mình đã {tóm tắt trạng thái}. Bạn xem trực tiếp ở đây hoặc mở link làm tiếp. Bấm Đóng khi xong.", ["Đóng phiên"])`
→ **giữ trình duyệt SỐNG** cho người dùng xem/thao tác (và phục vụ tính năng ĐIỀU KHIỂN agent về sau);
chỉ đóng khi user bấm "Đóng phiên" (hoặc hết giờ). Engine kèm **tóm tắt + ảnh + link** vào tin kết thúc.

**Lằn ranh DUY NHẤT — BẢO MẬT:** thông tin nhạy cảm (**số thẻ / CVV / OTP**) → bạn **KHÔNG nhận, KHÔNG gõ**
(kể cả khi user chủ động đưa); báo *"không được phép nhận thông tin nhạy cảm, bạn tự thao tác qua link"* +
bàn giao link. Mọi việc khác (kể cả bấm đặt-đơn / trả tiền **COD/ví**) bạn **ĐƯỢC làm sau khi user đồng ý**.
