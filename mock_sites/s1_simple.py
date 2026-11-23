"""s1_simple (8801): form một trang, input ngày/giờ native, submit kiểu form truyền thống."""

from __future__ import annotations

from html import escape

from fastapi import Request

from mock_sites.common import Store, make_app, page, read_fields, validate_booking

store = Store()
app = make_app("s1_simple", store)

FORM = """
<h1>Nhà hàng Bến Sông — Đặt bàn</h1>
<form method="post" action="/book">
  <label for="date">Ngày</label><input id="date" name="date" type="date" required>
  <label for="time">Giờ</label><input id="time" name="time" type="time" required>
  <label for="party_size">Số người</label>
  <input id="party_size" name="party_size" type="number" min="1" max="20" value="2" required>
  <label for="name">Họ tên</label><input id="name" name="name" type="text" required>
  <label for="phone">Số điện thoại</label><input id="phone" name="phone" type="tel" required>
  <button type="submit" id="submit">Đặt bàn</button>
</form>
"""


@app.get("/")
async def index():
    return page("Đặt bàn — Bến Sông", FORM)


@app.post("/book")
async def book(request: Request):
    booking, err = validate_booking(await read_fields(request))
    if err:
        return page("Lỗi", f'<h1>Không đặt được</h1><div class="err">{escape(err)}</div><p><a href="/">Quay lại</a></p>')
    store.add(**booking)
    b = {k: escape(str(v)) for k, v in booking.items()}
    return page(
        "Đã đặt bàn",
        f'<h1>Đặt bàn thành công</h1><div class="ok" id="confirmation">'
        f'Bàn {b["party_size"]} người, ngày {b["date"]} lúc {b["time"]}, tên {b["name"]}, SĐT {b["phone"]}.</div>',
    )
