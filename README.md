# runtime: chọn runtime trình duyệt và LLM cho agent đặt bàn

Module này đo và so sánh các runtime trình duyệt (Chrome local, Steel self-host, Steel Cloud, Browser Use Cloud, Kernel) và các LLM chạy trong browser-use (Claude, Grok). Có đo cả khi chưa cache và khi đã cache. Từ kết quả đó, module chọn ra một tổ hợp để các module sau trong pipeline dùng.

## Giao việc cho agent

Mở agent trong repo này, rồi gõ một câu:

- Người làm runtime: **"Bạn là Agent 1. Làm theo AGENTS.md."**
- Người làm LLM: **"Bạn là Agent 2. Làm theo AGENTS.md."**

Agent sẽ tự đọc `AGENTS.md`, sau đó đến hợp đồng chung và brief của mình. Nó làm việc trên nhánh riêng và cập nhật `docs/status/`.

## Chuẩn bị máy

1. Cài [uv](https://docs.astral.sh/uv/), Docker Desktop và Google Chrome.
2. Copy `.env.example` thành `.env`, rồi điền khóa API của mình. Thiếu khóa nào thì ứng viên đó được ghi là `skipped`.
3. Chạy `uv sync`, sau đó `uv run playwright install chromium`.

## Tài liệu

| File | Nội dung |
|---|---|
| `AGENTS.md` | Điểm bắt đầu cho agent: vai trò, quy trình git, luật |
| `docs/00_CONTRACT.md` | Quyết định chung đã chốt: ứng viên, bộ test, cách đo, tiêu chí chọn |
| `docs/AGENT_1_RUNTIME.md` | Brief của Agent 1 |
| `docs/AGENT_2_LLM.md` | Brief của Agent 2 |
| `docs/status/` | Mỗi agent tự cập nhật tiến độ của mình |
| `reports/DECISION.md` | Kết quả cuối (sinh ra khi đo xong) |

## Thứ tự phụ thuộc

```text
A1: mock_sites ──► merge main ──► đo runtime ─────────────────┐
A2: adapter LLM ──(chờ mock_sites)──► đo LLM & cache ──► merge ┴─► A1: chạy chéo + DECISION.md
```
