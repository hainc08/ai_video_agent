# Yêu cầu hệ thống: AI Agent tạo video ngắn (Claude × Veo)

Cập nhật 30/09/2026. Bản gốc (có sơ đồ): https://claude.ai/code/artifact/10e71b75-6790-40ac-a04c-dd55b34daf29

## 1. Tổng quan & mục tiêu

Agent dùng Claude làm "bộ não": nhận một ý tưởng thô, tự lập kế hoạch sản xuất, sinh video bằng Veo 3.1
(qua Gemini API), rồi ghép thành video ngắn 9:16 dài 15–60 giây, sẵn sàng đăng Reels / TikTok / Shorts.

Mục tiêu MVP:

- Từ 1 câu ý tưởng → 1 file MP4 hoàn chỉnh, không thao tác tay ngoài bước duyệt plan.
- End-to-end ≤ 20 phút cho video 30 giây (4–6 cảnh).
- Trần chi phí mỗi video cấu hình được (mặc định 5 USD).
- Người dùng duyệt plan trước khi tốn tiền sinh video.

## 2. Phạm vi

| Hạng mục | MVP | Giai đoạn sau |
| --- | --- | --- |
| Nhận ý tưởng (text) qua **giao diện web** | Có | Google Sheet, Telegram |
| Lập plan: brief, kịch bản, phân cảnh, prompt | Có | Nhiều biến thể A/B |
| Duyệt plan (human-in-the-loop) | Có | Công tắc "Tự động duyệt" |
| Sinh clip qua Veo 3.1 (Gemini API) | Có | Ảnh tham chiếu (image-to-video) |
| TTS tiếng Việt | Có | Clone giọng |
| Phụ đề + nhạc nền + ghép MP4 | Có | Template thương hiệu |
| Tự kiểm tra & sinh lại cảnh lỗi | Cơ bản (1 lần) | Chấm bằng vision model |
| Đăng Facebook/TikTok | Không | Nối workflow n8n hiện có |

Ghi chú: bản đầu của tài liệu để MVP chạy CLI; nay đã chốt làm giao diện web ngay trong MVP (xem `UI_SPEC.md`).

## 3. Luồng hoạt động

Xem `ARCHITECTURE.md`. Tóm tắt: nhập ý tưởng → Claude lập plan → ước tính chi phí → người dùng duyệt
(hoặc góp ý để Claude viết lại, lặp không giới hạn) → Veo sinh clip song song → kiểm tra từng clip
(lỗi → Claude chỉnh prompt, sinh lại tối đa 1 lần) → TTS + phụ đề → FFmpeg ghép MP4.

## 4. Yêu cầu chức năng

| Mã | Yêu cầu | Tiêu chí chấp nhận |
| --- | --- | --- |
| FR-01 | Nhận ý tưởng 1–3 câu + tham số: thời lượng, tỉ lệ, phong cách, giọng đọc, trần chi phí | Thiếu tham số → mặc định 30 giây, 9:16, tone chuyên nghiệp, 5 USD |
| FR-02 | Phân tích ý tưởng: khán giả, thông điệp, hook 3 giây, CTA | Plan có đủ 4 trường |
| FR-03 | Viết lời thoại tiếng Việt khớp thời lượng | ≈ 2,5–3 từ/giây; lệch ≤ 10% |
| FR-04 | Chia cảnh 4–8 giây: mô tả hình ảnh, góc máy, chuyển động | Tổng thời lượng cảnh = mục tiêu ± 2 giây; mỗi cảnh ∈ {4, 6, 8} giây (giới hạn Veo) |
| FR-05 | Prompt Veo tiếng Anh cho từng cảnh + style guide chung | ≤ 1.000 ký tự; không yêu cầu chữ hiển thị trong hình |
| FR-06 | Ước tính chi phí & thời gian trước khi chạy | Hiển thị USD dự kiến; chặn nếu vượt trần |
| FR-07 | Chờ duyệt / sửa plan | Duyệt; sửa tay từng cảnh; góp ý để Claude viết lại cả plan hoặc 1 cảnh |
| FR-08 | Gọi Veo, song song có giới hạn, theo dõi job | Tối đa N job đồng thời (mặc định 3); timeout mỗi job |
| FR-09 | Kiểm tra clip: tải được, đúng tỉ lệ, đúng thời lượng | Lỗi → sinh lại tối đa 1 lần với prompt đã chỉnh |
| FR-10 | TTS tiếng Việt từ lời thoại | Audio khớp thứ tự cảnh |
| FR-11 | Ghép: nối clip, lồng tiếng, phụ đề burn-in, nhạc nền, logo | MP4 H.264, 1080×1920, ≤ 100 MB |
| FR-12 | Lưu artifact theo job: plan.json, prompt, clip, audio, log, chi phí | Chạy lại từ bất kỳ bước nào, không làm lại bước đã xong |
| FR-13 | Giao diện web 4 màn hình (xem `UI_SPEC.md`) | Theo dõi tiến trình realtime; tải MP4 và plan.json |

## 5. Tích hợp video

Đã chốt: **Veo 3.1 qua Gemini API** (`google-genai`). Google Flow không có API chính thức; không tự động
hóa trình duyệt, không dùng dịch vụ bên thứ ba.

- Interface `VideoProvider`: `submit(prompt, config) -> op_id`, `poll(op_id) -> status`, `download(op_id, path)`.
- Tham số: tỉ lệ 9:16, thời lượng 4/6/8 giây, độ phân giải, bật/tắt audio gốc.
- Model mặc định trong config: `veo-3.1-generate-preview` (kiểm tra lại tên và đơn giá trên
  https://ai.google.dev/gemini-api/docs/video trước khi chạy thật).
- Retry có backoff khi lỗi mạng/quota; bị chặn bởi bộ lọc an toàn → không retry nguyên văn, chuyển Claude viết lại prompt.
- Ghi chi phí thực từng lượt gọi.

## 6. Yêu cầu phi chức năng

| Nhóm | Yêu cầu |
| --- | --- |
| Chi phí | Trần mỗi job và mỗi ngày; vượt trần thì dừng và báo |
| Độ tin cậy | Mỗi bước idempotent, có checkpoint; job lỗi giữa chừng chạy tiếp được |
| Quan sát | Log có cấu trúc theo job_id; ghi token Claude, giây video, thời gian từng bước |
| Bảo mật | Key trong `.env`, không commit, không log |
| Nội dung | Không nhân vật/logo/nhạc có bản quyền; không tạo người thật nhận diện được |
| Môi trường | Windows, Python 3.11+, FFmpeg cài sẵn |
| Mở rộng | Provider video, TTS, LLM thay được qua cấu hình |

## 7. Rủi ro

| Rủi ro | Giảm thiểu |
| --- | --- |
| Cảnh không nhất quán | Style guide chung trong mọi prompt; giai đoạn 2 dùng ảnh tham chiếu |
| Prompt bị chặn | Claude viết lại, tối đa 1 lần |
| Vượt chi phí | Ước tính trước, trần cứng, 720p cho bản nháp |
| Chữ AI bị méo | Không sinh chữ trong Veo; phụ đề bằng FFmpeg |

## 8. Câu hỏi còn mở

- [x] Phương án tích hợp: Veo qua Gemini API.
- [ ] Dịch vụ TTS: FPT.AI, Google Cloud TTS hay ElevenLabs? (làm interface trước, chọn sau)
- [ ] Ngân sách tối đa mỗi video? (mặc định 5 USD)
- [ ] Dùng audio gốc của Veo hay chỉ TTS + nhạc nền? (mặc định tắt audio Veo nếu API cho phép)

## 9. Nghiệm thu MVP

5 ý tưởng khác nhau → 5 MP4 đạt FR-01 đến FR-13, mỗi video ≤ 20 phút và dưới trần chi phí.
