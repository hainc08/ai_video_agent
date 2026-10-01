# CLAUDE.md — AI Video Agent

File này hướng dẫn Claude Code khi làm việc trong repo. Đọc hết trước khi viết code.

## Dự án là gì

Web app nhận một ý tưởng (1–3 câu tiếng Việt) và tự động tạo video ngắn 9:16 (15–60 giây)
cho Facebook Reels / TikTok / Shorts:

ý tưởng → Claude lập plan → người dùng duyệt → Veo sinh clip → kiểm tra → TTS + phụ đề → FFmpeg ghép MP4

Người dùng: chủ kênh "AI Văn Phòng" (tips AI cho dân văn phòng 25–40 tuổi), nội dung faceless,
tone chuyên nghiệp, lời thoại tiếng Việt.

## Tài liệu bắt buộc đọc

| File | Nội dung |
| --- | --- |
| `docs/REQUIREMENTS.md` | Yêu cầu chức năng FR-01..FR-12, phi chức năng, rủi ro |
| `docs/ARCHITECTURE.md` | Luồng agent, kiến trúc, trạng thái job, API |
| `docs/UI_SPEC.md` | 4 màn hình, trường dữ liệu, hành vi |
| `docs/ui-mockups/*.dc.html` | Mockup thiết kế tham khảo (màu, font, bố cục) |
| `docs/plan.schema.json` | JSON Schema của plan — hợp đồng giữa Claude và hệ thống |
| `prompts/planner_system.md` | System prompt cho bước lập plan |
| `TASKS.md` | Danh sách việc theo giai đoạn — làm theo thứ tự |

## Quyết định đã chốt (không tự ý đổi)

- Video: **Veo 3.1 qua Gemini API chính thức** (`google-genai` SDK). KHÔNG tự động hóa trang Google Flow,
  KHÔNG dùng API bên thứ ba bọc Flow.
- LLM: Claude API (Anthropic Python SDK), dùng **tool use** để ép output đúng `plan.schema.json`.
- Có bước người dùng duyệt plan trước khi gọi Veo (vì Veo tính tiền).
- Không sinh chữ trong video bằng Veo; chữ/phụ đề làm bằng FFmpeg.
- Sinh lại clip lỗi tối đa 1 lần/cảnh.
- Trần chi phí mỗi job, cấu hình được; vượt trần thì dừng.

## Tech stack

- Python 3.11+, chạy trên **Windows** (dùng `pathlib`, không hard-code `/`; subprocess FFmpeg không dùng shell=True).
- Backend: FastAPI + Uvicorn.
- Frontend: Jinja2 templates + HTMX + CSS thuần (không build step). Tiến trình realtime qua SSE.
- DB: SQLite qua SQLModel. File của job lưu ở `data/jobs/<job_id>/`.
- Hàng đợi: asyncio background task trong cùng process (MVP), giới hạn song song bằng `asyncio.Semaphore`.
- Validate: Pydantic v2. Test: pytest (+ pytest-asyncio).
- FFmpeg cài sẵn trên máy, đường dẫn trong `config.yaml`.

Nếu thấy lý do chính đáng để đổi stack, hỏi người dùng trước.

## Cấu trúc thư mục mục tiêu

```
app/
  main.py              # FastAPI app, routes HTML + API
  config.py            # đọc .env + config.yaml
  models.py            # SQLModel: Job, Scene, CostEntry
  schemas.py           # Pydantic: Plan, Scene, Brief (khớp docs/plan.schema.json)
  agent/
    planner.py         # Claude: idea -> Plan; revise(plan, feedback); rewrite_scene
    estimator.py       # ước tính chi phí/thời gian
    runner.py          # điều phối job, checkpoint, retry, SSE events
    qc.py              # kiểm tra clip (tồn tại, tỉ lệ, thời lượng qua ffprobe)
  providers/
    base.py            # VideoProvider, TTSProvider (Protocol)
    veo_gemini.py      # Veo 3.1 qua google-genai
    fake_video.py      # provider giả để dev/test không tốn tiền
    tts_*.py           # TTS tiếng Việt
  assembler/
    ffmpeg.py          # ghép clip, audio, phụ đề .ass, nhạc nền, logo
  templates/           # Jinja2, theo docs/ui-mockups
  static/              # css, htmx
data/                  # runtime, gitignore
tests/
```

## Quy tắc làm việc

1. Làm theo `TASKS.md`, hết giai đoạn nào báo lại và chạy test trước khi sang giai đoạn sau.
2. **Không bao giờ gọi API tốn tiền (Veo, TTS) trong test.** Dùng `fake_video.py` và mock.
   Chế độ mặc định khi dev: `VIDEO_PROVIDER=fake`.
3. Trước lần gọi Veo thật đầu tiên, hỏi người dùng xác nhận.
4. Mỗi bước của runner phải idempotent: bước đã xong (file tồn tại + trạng thái DB) thì bỏ qua khi chạy lại.
5. Ghi chi phí thực của mỗi lượt gọi API vào `CostEntry`.
6. API key chỉ đọc từ `.env`. Không log key, không commit `.env`.
7. Giao diện tiếng Việt, theo mockup: nền `#F4F2EC`, chữ `#17181C`, accent `#1D4ED8`, cảnh báo `#C2410C`,
   font Be Vietnam Pro (UI) và JetBrains Mono (prompt, log).
8. Tên model và đơn giá để trong `config.yaml`, không hard-code.
9. Code, tên biến, comment bằng tiếng Anh; chữ hiển thị cho người dùng bằng tiếng Việt.

## Lệnh thường dùng

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
pytest
```
