# Kiến trúc

## Luồng agent

```mermaid
flowchart TD
    A[Người dùng nhập ý tưởng] --> B[Claude lập plan: brief, kịch bản, cảnh, prompt]
    B --> C[Ước tính chi phí và thời gian]
    C --> D{Duyệt plan?}
    D -- góp ý / sửa --> B
    D -- duyệt --> E[Veo sinh clip từng cảnh, song song]
    E --> F{Clip đạt?}
    F -- lỗi, lần 1 --> G[Claude chỉnh prompt] --> E
    F -- đạt --> H[TTS tiếng Việt + phụ đề]
    H --> I[FFmpeg ghép MP4 9:16]
```

Vòng "sửa plan" không giới hạn (chưa tốn tiền video). Vòng "sinh lại clip" tối đa 1 lần/cảnh.

## Thành phần

```mermaid
flowchart TB
    UI[Web UI: Jinja2 + HTMX + SSE] --> API[FastAPI]
    API --> P[Planner - Claude API + tool use]
    API --> G[Cổng duyệt + Estimator]
    API --> R[Job runner - asyncio, checkpoint, retry]
    R --> V[VideoProvider - Veo 3.1 / fake]
    R --> T[TTSProvider]
    R --> X[Assembler - FFmpeg]
    R --> DB[(SQLite)]
    V & T & X --> FS[data/jobs/job_id/]
```

## Trạng thái job

```
draft -> planning -> awaiting_approval -> generating -> assembling -> done
                 \-> (revise) -> planning
bất kỳ -> failed | cancelled
```

Trạng thái cảnh: `planned -> generating -> generated -> qc_failed -> regenerating -> approved | failed`

## Thư mục job

```
data/jobs/<job_id>/
  plan.json            # bản plan mới nhất (plan.v1.json, plan.v2.json... khi viết lại)
  clips/scene_01.mp4
  audio/scene_01.wav
  subtitles.ass
  music.mp3            # nếu có
  final.mp4
  log.jsonl
```

## API

| Method | Path | Mô tả |
| --- | --- | --- |
| POST | `/api/jobs` | Tạo job từ ý tưởng + tùy chọn → chạy planner |
| GET | `/api/jobs` | Danh sách job gần đây |
| GET | `/api/jobs/{id}` | Chi tiết job + plan + trạng thái cảnh |
| POST | `/api/jobs/{id}/revise` | `{feedback}` → Claude viết lại cả plan |
| PATCH | `/api/jobs/{id}/scenes/{n}` | Sửa tay một cảnh |
| POST | `/api/jobs/{id}/scenes/{n}/rewrite` | Claude viết lại một cảnh |
| POST | `/api/jobs/{id}/approve` | Duyệt → bắt đầu sinh video (kiểm tra trần chi phí) |
| POST | `/api/jobs/{id}/cancel` | Hủy |
| GET | `/api/jobs/{id}/events` | SSE: tiến trình, log, chi phí |
| GET | `/api/jobs/{id}/video` | Tải final.mp4 |
| GET | `/api/jobs/{id}/plan.json` | Tải plan |

Trang HTML: `/` (nhập ý tưởng), `/jobs/{id}` (hiển thị màn hình 2, 3 hoặc 4 theo trạng thái).

## Veo qua Gemini API (tham khảo)

Gọi là thao tác bất đồng bộ: `client.models.generate_videos(model=..., prompt=..., config=...)` trả về
operation, poll bằng `client.operations.get(operation)` đến khi `done`, rồi tải file.
Tài liệu: https://ai.google.dev/gemini-api/docs/video
