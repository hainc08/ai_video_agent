# TASKS

Làm theo thứ tự. Cuối mỗi giai đoạn: chạy `pytest`, cập nhật dấu [x], tóm tắt cho người dùng.

## Giai đoạn 0 — Khung dự án
- [x] Tạo cấu trúc thư mục theo CLAUDE.md, `requirements.txt`, `app/config.py` đọc `.env` + `config.yaml`
- [x] Kiểm tra FFmpeg/ffprobe có chạy được; báo lỗi rõ ràng nếu thiếu
- [x] FastAPI chạy được, trang `/` trả về template trống
- [x] SQLModel: `Job`, `Scene`, `CostEntry`; tạo DB SQLite khi khởi động

## Giai đoạn 1 — Planner (Claude)
- [x] `app/schemas.py`: Pydantic models khớp `docs/plan.schema.json`
- [x] `planner.create_plan(idea, options)`: gọi Claude với tool `submit_plan` (input_schema = plan schema),
      system prompt từ `prompts/planner_system.md`
- [x] Validate kết quả; nếu sai (tổng thời lượng lệch, số từ lệch > 10%) → gửi lỗi lại cho Claude sửa, tối đa 2 lần
- [x] `planner.revise(plan, feedback)` và `planner.rewrite_scene(plan, scene_id, feedback)`
- [x] `estimator.estimate(plan, config)` → chi phí USD và phút, đọc đơn giá từ config
- [x] Test với Claude được mock (fixture JSON mẫu)

## Giai đoạn 2 — Giao diện màn 1 & 2
- [x] Template base + header 4 bước theo `docs/UI_SPEC.md` và mockup
- [x] Màn 1: form ý tưởng → `POST /api/jobs` → redirect `/jobs/{id}`
- [x] Trạng thái "Claude đang lập plan…" (HTMX poll hoặc SSE)
- [x] Màn 2: brief, danh sách cảnh, sửa inline, viết lại cảnh, góp ý viết lại plan, ước tính, nút duyệt
- [x] Khóa nút duyệt khi vượt trần

## Giai đoạn 3 — Sinh video
- [ ] `providers/base.py`: `VideoProvider` protocol
- [ ] `providers/fake_video.py`: tạo clip màu có số cảnh bằng FFmpeg, đúng tỉ lệ/thời lượng (dùng khi dev)
- [ ] `providers/veo_gemini.py`: `generate_videos` + poll operation + tải file; model/tỉ lệ/thời lượng từ config
- [ ] `runner.py`: chạy song song (Semaphore), timeout, backoff, ghi `CostEntry`, dừng khi chạm trần
- [ ] `qc.py`: ffprobe kiểm tra tỉ lệ, thời lượng; lỗi → `planner.rewrite_scene` → sinh lại 1 lần
- [ ] SSE `/api/jobs/{id}/events`; Màn 3 theo mockup
- [ ] **Hỏi người dùng trước khi chạy Veo thật lần đầu**

## Giai đoạn 4 — Âm thanh & ghép
- [ ] `TTSProvider` protocol + 1 provider (hỏi người dùng chọn dịch vụ) + provider giả (im lặng đúng độ dài)
- [ ] Phụ đề `.ass` từ `subtitle_vi` và thời điểm cảnh, font hỗ trợ tiếng Việt
- [ ] `assembler/ffmpeg.py`: nối clip, trộn TTS + nhạc nền (ducking), burn phụ đề, logo góc; xuất 1080×1920 H.264
- [ ] Màn 4: video player, tải MP4/plan.json, caption, số liệu thực

## Giai đoạn 5 — Ổn định
- [ ] Chạy tiếp job từ bước lỗi (idempotent)
- [ ] Hủy job giữa chừng
- [ ] Trần chi phí theo ngày
- [ ] Nghiệm thu: 5 ý tưởng → 5 MP4 (xem REQUIREMENTS §9)

## Sau MVP
- [ ] Công tắc "Tự động duyệt"
- [ ] Nút "Đăng lên Facebook" gọi webhook n8n
- [ ] Ảnh tham chiếu cho nhân vật/bối cảnh nhất quán
