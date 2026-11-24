"""s3_spa (8803): SPA, khung giờ tải bằng fetch sau khi chọn ngày (trễ ngẫu nhiên 300–1500 ms), modal cookie che form."""

from __future__ import annotations

import asyncio
import random
import re

from fastapi import Request

from mock_sites.common import Store, error_json, make_app, page, read_fields, time_slots, validate_booking

store = Store()
app = make_app("s3_spa", store)

SLOTS = time_slots(11, 21, 15)  # mỗi 15 phút, 11:00–21:30

BODY = """
<div id="app"><p>Đang tải…</p></div>
<div id="cookie-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:10">
  <div style="background:#fff;max-width:420px;margin:20vh auto;padding:20px">
    <h2>Chúng tôi dùng cookie</h2>
    <p>Trang này dùng cookie để cải thiện trải nghiệm. Bạn có đồng ý không?</p>
    <button type="button" id="cookie-accept">Đồng ý</button>
    <button type="button" id="cookie-reject">Từ chối</button>
  </div>
</div>
"""

SCRIPT = """
const $ = id => document.getElementById(id);
const state = {time: null};
function render() {
  $('app').innerHTML = `
    <h1>Bếp Nhà Mây — Đặt bàn online</h1>
    <label for="date">Ngày</label><input id="date" type="date">
    <label for="party">Số người</label>
    <select id="party">${Array.from({length: 12}, (_, i) => `<option value="${i+1}"${i===1?' selected':''}>${i+1}</option>`).join('')}</select>
    <p>Khung giờ còn trống:</p>
    <div id="slots"><em>Chọn ngày để xem giờ.</em></div>
    <label for="name">Họ tên</label><input id="name" type="text">
    <label for="phone">Số điện thoại</label><input id="phone" type="tel">
    <button type="button" id="submit">Gửi yêu cầu đặt bàn</button>
    <div id="msg"></div>`;
  $('date').addEventListener('change', loadSlots);
  $('submit').addEventListener('click', submit);
}
let req = 0;
async function loadSlots() {
  const my = ++req; state.time = null;
  $('slots').innerHTML = '<em id="slots-loading">Đang tải khung giờ…</em>';
  const r = await fetch('/api/slots?date=' + encodeURIComponent($('date').value));
  const j = await r.json();
  if (my !== req) return;
  if (!j.slots || !j.slots.length) { $('slots').innerHTML = '<em>Không có giờ trống.</em>'; return; }
  $('slots').innerHTML = j.slots.map(s => `<button type="button" class="slot" data-time="${s}">${s}</button>`).join(' ');
  $('slots').querySelectorAll('.slot').forEach(b => b.addEventListener('click', () => {
    $('slots').querySelectorAll('.slot').forEach(x => { x.style.background = ''; x.style.color = ''; });
    b.style.background = '#333'; b.style.color = '#fff'; state.time = b.dataset.time;
  }));
}
async function submit() {
  const msg = $('msg');
  if (!state.time) { msg.className = 'err'; msg.textContent = 'Vui lòng chọn khung giờ.'; return; }
  const body = {date: $('date').value, time: state.time, party_size: $('party').value,
                name: $('name').value, phone: $('phone').value};
  const r = await fetch('/api/book', {method: 'POST', headers: {'content-type': 'application/json'},
                                      body: JSON.stringify(body)});
  const j = await r.json();
  if (!j.ok) { msg.className = 'err'; msg.textContent = j.error; return; }
  $('app').innerHTML = `<h1>Đã nhận đặt bàn</h1><div class="ok" id="confirmation">
    ${body.party_size} người, ${body.date} lúc ${body.time}, tên ${body.name.replace(/</g, '&lt;')}.</div>`;
}
function closeModal(choice) {
  try { localStorage.setItem('cookie_consent', choice); } catch (e) {}
  $('cookie-modal').style.display = 'none';
}
$('cookie-accept').onclick = () => closeModal('accepted');
$('cookie-reject').onclick = () => closeModal('rejected');
setTimeout(() => {
  render();
  let seen = null; try { seen = localStorage.getItem('cookie_consent'); } catch (e) {}
  if (!seen) setTimeout(() => { $('cookie-modal').style.display = ''; }, 400);
}, 300);
"""


@app.get("/")
async def index():
    return page("Bếp Nhà Mây", BODY, SCRIPT)


@app.get("/api/slots")
async def slots(date: str = ""):
    await asyncio.sleep(random.uniform(0.3, 1.5))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return {"slots": []}
    return {"slots": SLOTS}


@app.post("/api/book")
async def book(request: Request):
    booking, err = validate_booking(await read_fields(request))
    if err:
        return error_json(err)
    if booking["time"] not in SLOTS:
        return error_json("Khung giờ không có.")
    store.add(**booking)
    return {"ok": True, "booking": booking}
