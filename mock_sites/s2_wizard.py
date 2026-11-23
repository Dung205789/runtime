"""s2_wizard (8802): 3 bước, date picker JS tự viết (không có <input type=date>), chọn khung giờ bằng nút."""

from __future__ import annotations

from fastapi import Request

from mock_sites.common import Store, error_json, make_app, page, read_fields, time_slots, validate_booking

store = Store()
app = make_app("s2_wizard", store)

SLOTS = time_slots(11, 21, 30)  # 11:00, 11:30, ..., 21:30

BODY = """
<h1>Quán Gió Bấc — Đặt bàn</h1>
<p id="stepper">Bước <span id="step-no">1</span>/3</p>

<section id="step1">
  <label for="party">Số người</label>
  <select id="party">__PARTY__</select>
  <label>Ngày</label>
  <input id="date-display" type="text" readonly placeholder="Bấm để chọn ngày">
  <div id="datepicker" style="display:none;border:1px solid #999;padding:8px;margin-top:4px">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <button type="button" id="prev-month" aria-label="Tháng trước">‹</button>
      <strong id="month-title"></strong>
      <button type="button" id="next-month" aria-label="Tháng sau">›</button>
    </div>
    <div id="days" style="display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin-top:8px"></div>
  </div>
  <button type="button" id="next1">Tiếp tục</button>
  <div id="err1" class="err" style="display:none"></div>
</section>

<section id="step2" style="display:none">
  <p>Chọn khung giờ:</p>
  <div id="slots" style="display:flex;flex-wrap:wrap;gap:6px">__SLOTS__</div>
  <p>Đã chọn: <span id="slot-picked">—</span></p>
  <button type="button" id="back2">Quay lại</button>
  <button type="button" id="next2">Tiếp tục</button>
  <div id="err2" class="err" style="display:none"></div>
</section>

<section id="step3" style="display:none">
  <label for="name">Họ tên</label><input id="name" type="text">
  <label for="phone">Số điện thoại</label><input id="phone" type="tel">
  <button type="button" id="back3">Quay lại</button>
  <button type="button" id="confirm">Xác nhận đặt bàn</button>
  <div id="err3" class="err" style="display:none"></div>
</section>

<div id="done" class="ok" style="display:none"></div>
"""

SCRIPT = """
const state = {date: null, time: null};
let view = {y: 2026, m: 10};  // tháng 11/2026 (m tính từ 0)
const WEEK = ['T2','T3','T4','T5','T6','T7','CN'];
const $ = id => document.getElementById(id);
const pad = n => String(n).padStart(2, '0');

function showStep(n) {
  [1,2,3].forEach(i => $('step' + i).style.display = i === n ? '' : 'none');
  $('step-no').textContent = n;
}
function renderCal() {
  $('month-title').textContent = 'Tháng ' + (view.m + 1) + ' / ' + view.y;
  const days = $('days');
  days.innerHTML = WEEK.map(w => '<span style="text-align:center;font-size:.8rem">' + w + '</span>').join('');
  const first = new Date(view.y, view.m, 1);
  const offset = (first.getDay() + 6) % 7;
  for (let i = 0; i < offset; i++) days.insertAdjacentHTML('beforeend', '<span></span>');
  const n = new Date(view.y, view.m + 1, 0).getDate();
  for (let d = 1; d <= n; d++) {
    const iso = view.y + '-' + pad(view.m + 1) + '-' + pad(d);
    const sel = iso === state.date ? ' style="background:#333;color:#fff"' : '';
    days.insertAdjacentHTML('beforeend',
      '<button type="button" class="day" data-date="' + iso + '"' + sel + '>' + d + '</button>');
  }
}
$('date-display').addEventListener('click', () => {
  const p = $('datepicker'); p.style.display = p.style.display === 'none' ? '' : 'none'; renderCal();
});
$('prev-month').onclick = () => { view.m--; if (view.m < 0) { view.m = 11; view.y--; } renderCal(); };
$('next-month').onclick = () => { view.m++; if (view.m > 11) { view.m = 0; view.y++; } renderCal(); };
$('days').addEventListener('click', e => {
  const b = e.target.closest('.day'); if (!b) return;
  state.date = b.dataset.date;
  const [y, m, d] = state.date.split('-');
  $('date-display').value = d + '/' + m + '/' + y;
  $('datepicker').style.display = 'none';
});
$('slots').addEventListener('click', e => {
  const b = e.target.closest('.slot'); if (!b) return;
  document.querySelectorAll('.slot').forEach(x => x.style.background = '');
  b.style.background = '#333'; b.style.color = '#fff';
  document.querySelectorAll('.slot').forEach(x => { if (x !== b) x.style.color = ''; });
  state.time = b.dataset.time; $('slot-picked').textContent = state.time;
});
function err(id, msg) { const e = $(id); e.textContent = msg; e.style.display = msg ? '' : 'none'; }
$('next1').onclick = () => { if (!state.date) return err('err1', 'Vui lòng chọn ngày.'); err('err1', ''); showStep(2); };
$('back2').onclick = () => showStep(1);
$('next2').onclick = () => { if (!state.time) return err('err2', 'Vui lòng chọn giờ.'); err('err2', ''); showStep(3); };
$('back3').onclick = () => showStep(2);
$('confirm').onclick = async () => {
  const body = {date: state.date, time: state.time, party_size: $('party').value,
                name: $('name').value, phone: $('phone').value};
  const r = await fetch('/api/book', {method: 'POST', headers: {'content-type': 'application/json'},
                                      body: JSON.stringify(body)});
  const j = await r.json();
  if (!j.ok) return err('err3', j.error);
  $('step3').style.display = 'none'; $('stepper').style.display = 'none';
  const done = $('done'); done.style.display = ''; done.id = 'confirmation';
  done.textContent = 'Đặt bàn thành công: ' + body.party_size + ' người, ' + body.date + ' ' + body.time +
                     ', ' + body.name + '.';
};
"""


@app.get("/")
async def index():
    party = "".join(f'<option value="{n}"{" selected" if n == 2 else ""}>{n} người</option>' for n in range(1, 13))
    slots = "".join(f'<button type="button" class="slot" data-time="{s}">{s}</button>' for s in SLOTS)
    return page("Đặt bàn — Gió Bấc", BODY.replace("__PARTY__", party).replace("__SLOTS__", slots), SCRIPT)


@app.post("/api/book")
async def book(request: Request):
    booking, err = validate_booking(await read_fields(request))
    if err:
        return error_json(err)
    if booking["time"] not in SLOTS:
        return error_json("Khung giờ không có.")
    store.add(**booking)
    return {"ok": True, "booking": booking}
