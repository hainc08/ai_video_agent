# AI Video Agent

Nhập ý tưởng → Claude lập plan → bạn duyệt → Veo 3.1 sinh clip → ghép MP4 9:16.

Repo này hiện chỉ gồm **tài liệu và cấu hình** để Claude Code viết code.

## Có gì trong gói

```
CLAUDE.md                 hướng dẫn cho Claude Code (tự đọc khi mở repo)
TASKS.md                  việc cần làm theo 5 giai đoạn
docs/REQUIREMENTS.md      yêu cầu hệ thống
docs/ARCHITECTURE.md      luồng agent, kiến trúc, API
docs/UI_SPEC.md           đặc tả 4 màn hình
docs/ui-mockups/          mockup thiết kế tham khảo
docs/plan.schema.json     cấu trúc plan
prompts/planner_system.md system prompt cho Claude lập plan
.env.example              mẫu API key
config.example.yaml       mẫu cấu hình model, đơn giá, giới hạn chi phí
```

## Chuẩn bị trên Windows

1. Cài Python 3.11+ và FFmpeg (thêm vào PATH; gõ `ffmpeg -version` để kiểm tra).
2. Cài Claude Code theo hướng dẫn: https://docs.claude.com/en/docs/claude-code/overview
3. Lấy API key:
   - Claude: https://console.anthropic.com
   - Gemini (Veo): Google AI Studio, bật thanh toán cho project
4. Giải nén gói, sao chép `.env.example` → `.env` và `config.example.yaml` → `config.yaml`, điền key.
   Có thể để trống key Gemini lúc đầu — mặc định dùng provider giả, không tốn tiền.

## Giao cho Claude Code

Mở terminal trong thư mục dự án, chạy `claude`, rồi gửi:

> Đọc CLAUDE.md và các file trong docs/. Tóm tắt lại hiểu biết của bạn và kế hoạch cho Giai đoạn 0–1
> trong TASKS.md, rồi bắt đầu Giai đoạn 0. Dừng lại báo cáo khi xong mỗi giai đoạn.

Mẹo:

- Làm từng giai đoạn, kiểm tra chạy được rồi mới đi tiếp.
- Giai đoạn 3 Claude Code sẽ hỏi trước khi gọi Veo thật. Lúc đó điền `price_usd_per_second`
  trong `config.yaml` và đổi `VIDEO_PROVIDER=veo` trong `.env`.
- Thử với video 15 giây, 720p trước để tiết kiệm.
