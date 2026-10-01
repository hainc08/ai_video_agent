# Đặc tả giao diện

Mockup gốc: https://claude.ai/artifact/VYxDuuSuDpw4omWJ7Sks45
Bản HTML tham khảo trong `docs/ui-mockups/` (định dạng .dc.html của công cụ thiết kế — dùng để lấy màu,
font, khoảng cách, bố cục; các `{{...}}`, `<sc-for>`, `<x-dc>` là cú pháp của công cụ, không copy nguyên).

## Hệ thống hình ảnh

| Token | Giá trị |
| --- | --- |
| Nền trang | `#F4F2EC` |
| Bề mặt (card) | `#FFFFFF`, viền `#DAD6CC`, bo 12–16px |
| Chữ chính / phụ | `#17181C` / `#5B5E66` |
| Accent (nút chính, trạng thái xong) | `#1D4ED8`, nền nhạt `#E3EAFB` |
| Đang chạy / cảnh báo | `#C2410C`, nền nhạt `#FDF0E1`, chữ `#9A3412` |
| Font | Be Vietnam Pro (400/500/600/700); JetBrains Mono cho prompt và log |
| Nút / ô nhập | cao ≥ 44px |

Header chung: logo "AV", tên "AI Văn Phòng · Video Agent", thanh tiến trình 4 bước
(Ý tưởng → Duyệt plan → Đang tạo → Hoàn tất; bước xong nền xanh nhạt có dấu ✓, bước hiện tại nền đen),
góc phải "Veo 3.1 · Gemini API".

## Màn 1 — Nhập ý tưởng (`/`)

- Ô "Ý tưởng" (textarea, bắt buộc, 1–3 câu).
- Thời lượng: 15 / 30 / 60 giây (mặc định 30). Tỉ lệ: 9:16 / 1:1 / 16:9 (mặc định 9:16).
- Giọng đọc (select), Phong cách hình ảnh (select), Trần chi phí (USD, mặc định 5).
- Nút "Lập kế hoạch" → `POST /api/jobs` → chuyển sang `/jobs/{id}`, hiển thị trạng thái "Claude đang lập plan…".
- Cột phải: "Agent sẽ làm gì" (4 bước), "Video gần đây" (danh sách job; trạng thái rỗng khi chưa có).

## Màn 2 — Duyệt plan (`/jobs/{id}`, trạng thái `awaiting_approval`)

- Tiêu đề = ý tưởng; dòng meta: thời lượng · tỉ lệ · số cảnh · giọng.
- 4 ô brief: Khán giả, Hook 3 giây, Thông điệp, CTA.
- Danh sách cảnh: số cảnh, mốc thời gian, lời thoại, mô tả hình ảnh, prompt Veo (mono, rút gọn, bấm để xem đủ),
  nút "Sửa" (sửa tay inline) và "Viết lại" (Claude viết lại cảnh).
- Cột phải: ước tính (tổng giây, số lượt gọi Veo gồm tối đa sinh lại, thời gian, chi phí dự kiến vs trần),
  ô "Góp ý cho Claude" + nút "Yêu cầu viết lại plan", nút chính "Duyệt & tạo video",
  link "Quay lại sửa ý tưởng".
- Nếu chi phí dự kiến > trần: nút duyệt bị khóa, hiện cảnh báo màu cam.

## Màn 3 — Đang tạo (trạng thái `generating` / `assembling`)

- Cột trái: 6 bước (Lập plan, Duyệt plan, Sinh clip bằng Veo "x/5 cảnh xong", Kiểm tra clip,
  Giọng đọc + phụ đề, Ghép MP4) với trạng thái xong / đang chạy / chờ.
- Thanh chi phí đã dùng / trần. Nút "Hủy job".
- Cột phải: lưới thẻ 9:16 theo cảnh (Đạt / Đang sinh / Sinh lại lần 1/1 / Hàng đợi / Lỗi); khi clip xong hiện
  thumbnail hoặc video nhỏ.
- Khung nhật ký nền tối, font mono, cập nhật qua SSE.

## Màn 4 — Hoàn tất (trạng thái `done`)

- Trình phát video 9:16 (thẻ `<video>` từ `/api/jobs/{id}/video`).
- Nút "Tải MP4", "Tạo lại một cảnh", "Tải plan.json".
- "Caption gợi ý" (Claude sinh cùng plan, người dùng sửa được).
- 3 ô số liệu: thời gian thực, chi phí thực, số cảnh phải sinh lại.
- Link "Tạo video mới". (Giai đoạn 2: nút "Đăng lên Facebook" gọi webhook n8n.)

## Trạng thái lỗi

- `failed`: hiện bước lỗi, thông báo dễ hiểu, nút "Chạy tiếp từ bước lỗi".
- Mất kết nối SSE: tự kết nối lại, không mất trạng thái (trạng thái lấy từ DB).
