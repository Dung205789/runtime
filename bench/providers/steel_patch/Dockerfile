# Image steel-browser đã vá lỗi Live View (dùng cho steel_selfhost).
#
# Lỗi của image gốc (build 2026-11-21, digest ghim ở dưới):
#   - plugins/browser-socket/handlers/cast.handler: chỉ nhận websocket ở đường /v1/sessions/cast
#   - plugins/browser-socket/casting.handler: lại lấy id phiên từ /v1/sessions/{id}/cast
#   => id thành "cast?tabInfo=true", không khớp phiên đang chạy, server đóng kết nối ("Cast Session cast not found"),
#      trang Live View (/v1/sessions/debug) không nhận được khung hình nào.
# Vá: khi đường là /v1/sessions/cast (không có id) thì dùng phiên đang chạy — mỗi container chỉ có 1 phiên.
# Build: uv run python -m bench.providers.steel_selfhost build   (up() tự build nếu chưa có)

FROM ghcr.io/steel-dev/steel-browser@sha256:70c8895466515012b86833a84fbd7e8d5152bf2dd8a51a851d6b63c03534e216

RUN f=/app/api/build/plugins/browser-socket/casting.handler.js \
 && grep -q 'if (!session || session.id !== id) {' "$f" \
 && sed -i 's/if (!session || session.id !== id) {/if (!session || (session.id !== id \&\& !id.startsWith("cast"))) {/' "$f" \
 && grep -q 'startsWith("cast")' "$f"

LABEL bench.patch="steel-liveview-cast-id"
