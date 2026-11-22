# Hướng dẫn cho agent — đọc file này trước tiên

Repo này là **module chọn công nghệ** cho agent đặt bàn trong chatbot chạy bằng browser-use. Module đo các runtime trình duyệt và các LLM, chọn ra tổ hợp tốt nhất, rồi giao cho các module sau dùng.

Có **2 agent** làm song song, mỗi agent của một người khác nhau.

## Bước 0 — Xác định mình là ai

| Nếu người dùng nói… | Bạn là | Nhánh git | Brief |
|---|---|---|---|
| "Agent 1", "runtime", "Chrome/Steel" | **Agent 1 — Runtime** | `agent1-runtime` | `docs/AGENT_1_RUNTIME.md` |
| "Agent 2", "LLM", "Claude/Grok", "cache" | **Agent 2 — LLM & cache** | `agent2-llm` | `docs/AGENT_2_LLM.md` |

Nếu người dùng chưa nói rõ bạn là agent nào thì **hỏi đúng một câu**: "Tôi là Agent 1 (runtime) hay Agent 2 (LLM)?". Không đoán.

## Bước 1 — Đọc theo thứ tự

1. `docs/00_CONTRACT.md`: các quyết định chung đã chốt. **Không được sửa.**
2. Brief của bạn (bảng ở trên).
3. `docs/status/agent1.md` và `docs/status/agent2.md`: xem người kia đang làm đến đâu.

Sau đó vào việc luôn. Không cần hỏi lại những gì đã ghi trong hợp đồng.

## Bước 2 — Git

```bash
git fetch origin
git switch agent1-runtime   # hoặc agent2-llm
git merge origin/main       # lấy phần người kia đã merge
```

- Chỉ làm trên nhánh của mình. Không push thẳng lên `main`.
- Mỗi khi xong một **mốc** (liệt kê trong brief), làm theo thứ tự:
  1. Commit.
  2. Push nhánh.
  3. Tạo PR vào `main` bằng `gh pr create`.
  4. Merge PR đó (`gh pr merge --squash`), với điều kiện PR chỉ đụng thư mục của mình.
- Commit message ngắn, có tiền tố `[A1]` hoặc `[A2]`. **Không thêm dòng `Co-Authored-By`.**
- PR có sửa `pyproject.toml` thì phải chạy `uv lock` và commit cả `uv.lock`. Nếu bị conflict ở `uv.lock`, lấy bản của `main` rồi chạy lại `uv lock`.

## Bước 3 — Báo trạng thái

Mỗi khi xong một mốc, cập nhật **file status của mình**: `docs/status/agent1.md` hoặc `docs/status/agent2.md`. Không sửa file status của người kia. File status ghi 4 mục:

- Đang làm gì
- Đã xong mốc nào
- Đang bị chặn bởi gì
- Người kia cần biết gì

Người kia đọc file này để biết khi nào được dùng phần của bạn.

## Luật chung

- **Không bịa số.** Chỉ dùng số đo thật. Thiếu khóa API thì ghi `skipped`.
- **Không chạy lặp trên web đặt bàn thật.** Chỉ dùng mock site trong `mock_sites/`.
- Tra tài liệu thư viện và dịch vụ **bản hiện hành** trước khi viết code (browser-use, Steel, xAI…). Không viết theo trí nhớ.
- Không sửa file của người kia. Bảng phân quyền ở mục 2 của hợp đồng.
- Muốn đổi hợp đồng thì ghi đề xuất vào `docs/CHANGES.md`, ghi tên mình, rồi **dừng lại hỏi người dùng**.
- Không commit `.env`.
