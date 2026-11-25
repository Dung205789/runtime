# Kết quả: Claude đặt bàn trên 5 web nhà hàng

## Haiku tự điền, theo từng web

| Web | Điền đúng (đúng / chấm được) | Thời gian điển hình | Lần chậm nhất (trong các lần đúng) | Chi phí Claude (TB mỗi lần) |
|---|---:|---:|---:|---:|
| Lẩu Phan | 5/5 | 58.1 s | 83.5 s | $0.0031 |
| Tòng | 5/5 | 41.2 s | 45.1 s | $0.0031 |
| Chao Xian | 5/5 | 37.8 s | 48.3 s | $0.0032 |
| Lẩu Wang | 3/3 (+2 không chấm được) | 70.0 s | 91.7 s | $0.0074 |
| King BBQ | 5/5 | 42.0 s | 77.1 s | $0.0038 |

## Ba cách điền form

| Cách điền form | Làm gì | Điền đúng | Thời gian điển hình | Lần chậm (p95) | Chi phí Claude (TB mỗi lần) |
|---|---|---:|---:|---:|---:|
| Haiku tự điền | Haiku đọc trang và tự quyết định từng bước. Có gọi Claude. | 23/23 | 45.1 s | 83.5 s | $0.0041 |
| Chạy script, qua agent | Chạy lại script đã ghi, nhưng vẫn khởi động agent browser-use. Không gọi Claude. | 25/25 | 22.6 s | 40.1 s | $0.0000 |
| Chạy script trực tiếp | Chạy lại script đã ghi thẳng trên trình duyệt, bỏ qua agent. Không gọi Claude, nhanh nhất. | 25/25 | 8.5 s | 16.4 s | $0.0000 |

## Bao lâu thì có lời khi dùng script

| Web | Chi phí ghi nhớ (Haiku làm 1 lần + viết script) | Tiết kiệm mỗi lần (so với Haiku tự điền) | Có lời từ lần đặt thứ |
|---|---:|---:|---:|
| Lẩu Phan | $0.0089 | $0.0031 | 3 |
| Tòng | $0.0296 | $0.0031 | 10 |
| Chao Xian | $0.0089 | $0.0032 | 3 |
| Lẩu Wang | $0.0129 | $0.0061 | 3 |
| King BBQ | $0.0132 | $0.0038 | 4 |

## Ảnh từng bước

### Lẩu Phan

https://lauphan.com/dat-ban?type=lauphan · script bản v2 · điền xong trong 12.5 s · chạy lại bản này 5 lần, đúng 5 lần

**Bước 1** (giây thứ 4.9): Mở trang đặt bàn. Form còn giá trị mặc định, chưa điền gì.

| Ô trên form | Giá trị |
|---|---|
| Cơ sở | Chọn |
| Số người | 1 |
| Ngày | Hôm nay |
| Giờ | Chọn |

![Lẩu Phan, bước 1](img/real_lauphan_main_01.jpg)

**Bước 2** (giây thứ 5.2): Chọn / điền cơ sở Lẩu Phan Hoàng Quốc Việt.

![Lẩu Phan, bước 2](img/real_lauphan_main_02.jpg)

**Bước 3** (giây thứ 6.5): Chọn / điền số người 3.

![Lẩu Phan, bước 3](img/real_lauphan_main_03.jpg)

**Bước 4** (giây thứ 8.0): Chọn / điền ngày Ngày mai.

![Lẩu Phan, bước 4](img/real_lauphan_main_04.jpg)

**Bước 5** (giây thứ 9.3): Chọn / điền giờ 18:00.

![Lẩu Phan, bước 5](img/real_lauphan_main_05.jpg)

**Bước 6** (giây thứ 9.6): Gõ tên khách Khach Thu Nghiem.

![Lẩu Phan, bước 6](img/real_lauphan_main_06.jpg)

**Bước 7** (giây thứ 9.9): Gõ số điện thoại 0000000000.

![Lẩu Phan, bước 7](img/real_lauphan_main_07.jpg)

**Bước 8** (giây thứ 15.7): Kết thúc: form đã điền đủ. Dừng trước nút Đặt bàn, không gửi.

| Ô trên form | Giá trị |
|---|---|
| Cơ sở | Lẩu Phan Hoàng Quốc Việt |
| Số người | 3 |
| Ngày | Ngày mai |
| Giờ | 18:00 |
| Tên khách | Khach Thu Nghiem |
| Số điện thoại | 0000000000 |

![Lẩu Phan, bước 8](img/real_lauphan_main_08.jpg)

### Tòng

https://tong.com.vn/dat-ban · script bản v1 · điền xong trong 10.0 s · chạy lại bản này 4 lần, đúng 4 lần

**Bước 1** (giây thứ 7.7): Mở trang đặt bàn. Form còn giá trị mặc định, chưa điền gì.

| Ô trên form | Giá trị |
|---|---|
| Cơ sở | Tòng Livehouse |
| Số người | 1 |
| Ngày | Hôm nay |
| Giờ | Chọn |

![Tòng, bước 1](img/real_tong_main_01.jpg)

**Bước 2** (giây thứ 8.1): Chọn / điền số người 3.

![Tòng, bước 2](img/real_tong_main_02.jpg)

**Bước 3** (giây thứ 8.3): Chọn / điền ngày Ngày mai.

![Tòng, bước 3](img/real_tong_main_03.jpg)

**Bước 4** (giây thứ 9.4): Chọn / điền giờ 18:00.

![Tòng, bước 4](img/real_tong_main_04.jpg)

**Bước 5** (giây thứ 9.7): Gõ tên khách Khach Thu Nghiem.

![Tòng, bước 5](img/real_tong_main_05.jpg)

**Bước 6** (giây thứ 10.0): Gõ số điện thoại 0000000000.

![Tòng, bước 6](img/real_tong_main_06.jpg)

**Bước 7** (giây thứ 13.2): Kết thúc: form đã điền đủ. Dừng trước nút Đặt bàn, không gửi.

| Ô trên form | Giá trị |
|---|---|
| Cơ sở | Tòng Livehouse |
| Số người | 3 |
| Ngày | Ngày mai |
| Giờ | 18:00 |
| Tên khách | Khach Thu Nghiem |
| Số điện thoại | 0000000000 |

![Tòng, bước 7](img/real_tong_main_07.jpg)

### Chao Xian

https://chaoxian.com.vn/dat-ban · script bản v1 · điền xong trong 10.3 s · chạy lại bản này 4 lần, đúng 4 lần

**Bước 1** (giây thứ 7.6): Mở trang đặt bàn. Form còn giá trị mặc định, chưa điền gì.

| Ô trên form | Giá trị |
|---|---|
| Cơ sở | Chọn |
| Số người | 1 |
| Ngày | Hôm nay |
| Giờ | Chọn |

![Chao Xian, bước 1](img/real_chaoxian_main_01.jpg)

**Bước 2** (giây thứ 7.9): Chọn / điền cơ sở Chao Xian Kim Mã.

![Chao Xian, bước 2](img/real_chaoxian_main_02.jpg)

**Bước 3** (giây thứ 8.1): Chọn / điền số người 3.

![Chao Xian, bước 3](img/real_chaoxian_main_03.jpg)

**Bước 4** (giây thứ 8.4): Chọn / điền ngày Ngày mai.

![Chao Xian, bước 4](img/real_chaoxian_main_04.jpg)

**Bước 5** (giây thứ 9.4): Chọn / điền giờ 18:00.

![Chao Xian, bước 5](img/real_chaoxian_main_05.jpg)

**Bước 6** (giây thứ 9.7): Gõ tên khách Khach Thu Nghiem.

![Chao Xian, bước 6](img/real_chaoxian_main_06.jpg)

**Bước 7** (giây thứ 10.1): Gõ số điện thoại 0000000000.

![Chao Xian, bước 7](img/real_chaoxian_main_07.jpg)

**Bước 8** (giây thứ 13.6): Kết thúc: form đã điền đủ. Dừng trước nút Đặt bàn, không gửi.

| Ô trên form | Giá trị |
|---|---|
| Cơ sở | Chao Xian Kim Mã |
| Số người | 3 |
| Ngày | Ngày mai |
| Giờ | 18:00 |
| Tên khách | Khach Thu Nghiem |
| Số điện thoại | 0000000000 |

![Chao Xian, bước 8](img/real_chaoxian_main_08.jpg)

### Lẩu Wang

https://lauwang.vn/dat-ban/ · script bản v2 · điền xong trong 7.4 s · chạy lại bản này 5 lần, đúng 5 lần

**Bước 1** (giây thứ 4.0): Mở trang đặt bàn. Form còn giá trị mặc định, chưa điền gì.

| Ô trên form | Giá trị |
|---|---|
| Giờ | Giờ |
| Cơ sở | Chọn cơ sở |

![Lẩu Wang, bước 1](img/real_lauwang_main_01.jpg)

**Bước 2** (giây thứ 4.4): Chọn / điền cơ sở 51A Hồ Tùng Mậu, HN.

![Lẩu Wang, bước 2](img/real_lauwang_main_02.jpg)

**Bước 3** (giây thứ 4.8): Chọn / điền ngày 26/11/2026.

![Lẩu Wang, bước 3](img/real_lauwang_main_03.jpg)

**Bước 4** (giây thứ 5.2): Chọn / điền số người lớn 3.

![Lẩu Wang, bước 4](img/real_lauwang_main_04.jpg)

**Bước 5** (giây thứ 6.5): Chọn / điền giờ 18:00.

![Lẩu Wang, bước 5](img/real_lauwang_main_05.jpg)

**Bước 6** (giây thứ 7.0): Chọn / điền tên khách Khach Thu Nghiem.

![Lẩu Wang, bước 6](img/real_lauwang_main_06.jpg)

**Bước 7** (giây thứ 7.4): Chọn / điền số điện thoại 0000000000.

![Lẩu Wang, bước 7](img/real_lauwang_main_07.jpg)

**Bước 8** (giây thứ 10.9): Kết thúc: form đã điền đủ. Dừng trước nút Đặt bàn, không gửi.

| Ô trên form | Giá trị |
|---|---|
| Tên khách | Khach Thu Nghiem |
| Số điện thoại | 0000000000 |
| Ngày | 26/11/2026 |
| Giờ | 18:00 |
| Cơ sở | 51A Hồ Tùng Mậu, HN |
| Số người lớn | 3 |

![Lẩu Wang, bước 8](img/real_lauwang_main_08.jpg)

### King BBQ

https://kingbbq.vn/dat-ban/ · script bản v2 · điền xong trong 30.4 s · chạy lại bản này 5 lần, đúng 5 lần

**Bước 1** (giây thứ 20.2): Mở trang đặt bàn. Form còn giá trị mặc định, chưa điền gì.

| Ô trên form | Giá trị |
|---|---|
| Ngày | 25/11/2026 |
| Giờ | Chọn giờ đặt bàn |
| Phút | 00 ‘ |
| Nhà hàng | — Chọn nhà hàng — |
| Số người | 2 |

![King BBQ, bước 1](img/real_kingbbq_main_01.jpg)

**Bước 2** (giây thứ 21.6): Chọn / điền nhà hàng --- Chọn nhà hàng ---.

![King BBQ, bước 2](img/real_kingbbq_main_02.jpg)

**Bước 3** (giây thứ 22.5): Chọn / điền nhà hàng King Deli1 Bà Triệu - Tầng 5, Vincom Center, 191 Bà Triệu, Hai Bà Trưng, Hà Nội.

![King BBQ, bước 3](img/real_kingbbq_main_03.jpg)

**Bước 4** (giây thứ 23.3): Gõ ngày 26/11/2026.

![King BBQ, bước 4](img/real_kingbbq_main_04.jpg)

**Bước 5** (giây thứ 24.4): Gõ số người 3.

![King BBQ, bước 5](img/real_kingbbq_main_05.jpg)

**Bước 6** (giây thứ 25.5): Gõ tên khách Khach Thu Nghiem.

![King BBQ, bước 6](img/real_kingbbq_main_06.jpg)

**Bước 7** (giây thứ 26.1): Gõ số điện thoại 0000000000.

![King BBQ, bước 7](img/real_kingbbq_main_07.jpg)

**Bước 8** (giây thứ 26.7): Gõ email benchmark@example.invalid.

![King BBQ, bước 8](img/real_kingbbq_main_08.jpg)

**Bước 9** (giây thứ 28.5): Chọn / điền giờ 18 H.

![King BBQ, bước 9](img/real_kingbbq_main_09.jpg)

**Bước 10** (giây thứ 33.7): Kết thúc: form đã điền đủ. Dừng trước nút Đặt bàn, không gửi.

| Ô trên form | Giá trị |
|---|---|
| Tên khách | Khach Thu Nghiem |
| Email | benchmark@example.invalid |
| Số điện thoại | 0000000000 |
| Ngày | 26/11/2026 |
| Giờ | 18 H |
| Phút | 00 ‘ |
| Nhà hàng | King Deli1 Bà Triệu - Tầng 5, Vincom Center, 191 Bà Triệu, Hai Bà Trưng, Hà Nội |
| Số người | 3 |

![King BBQ, bước 10](img/real_kingbbq_main_10.jpg)

#### King BBQ: một lần script bản v1 từ chối

Lỗi: `RuntimeError: UNAVAILABLE: không có chi nhánh khớp chính xác (line 42)`

**Bước 1** (giây thứ 5.9): Mở trang đặt bàn. Form còn giá trị mặc định, chưa điền gì.

| Ô trên form | Giá trị |
|---|---|
| Ngày | 25/11/2026 |
| Giờ | Chọn giờ đặt bàn |
| Phút | 00 ‘ |
| Nhà hàng | — Chọn nhà hàng — |
| Số người | 2 |

![King BBQ, bước 1](img/real_kingbbq_run_loi_01.jpg)

**Bước 2** (giây thứ 9.1): Kết thúc: form đã điền đủ. Dừng trước nút Đặt bàn, không gửi.

| Ô trên form | Giá trị |
|---|---|
| Ngày | 25/11/2026 |
| Giờ | Chọn giờ đặt bàn |
| Phút | 00 ‘ |
| Nhà hàng | --- Chọn nhà hàng --- |
| Số người | 2 |

![King BBQ, bước 2](img/real_kingbbq_run_loi_02.jpg)
