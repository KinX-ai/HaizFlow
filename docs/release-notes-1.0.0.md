# HaizFlow 1.0.0

[Tải bộ cài Windows](https://github.com/MachHongHai/HaizFlow/releases/download/v1.0.0/HaizFlow-1.0.0-Setup.exe)

## Thay đổi

- Thêm chuẩn hóa khung hình 9:16 nền mờ hoặc đầy khung trong Manual, Auto và Hàng loạt; video đã là 9:16 được giữ nguyên.
- Thêm tốc độ phát preview, zoom timeline và cải thiện điều khiển xuất/tiến trình; khóa Xuất khi tác vụ khác đang xử lý.
- Đưa Edge TTS trở lại lựa chọn giọng đọc; tăng độ bền khi kết nối lỗi, có thử lại giới hạn.
- Cải thiện nhiều người nói: câu ngắn, giọng cao/trẻ em và các câu chứa nhiều lượt nói; không lấy lựa chọn nữ mặc định làm kết quả nhận diện. Những lượt thiếu bằng chứng vẫn được đánh dấu chưa chắc chắn và dùng Nữ dịu dàng khi cần fallback. Không cam kết chính xác mọi giọng biến đổi/hoạt hình.
- Sửa âm cuối của câu TTS ngắn, số tiếng Việt và các âm bíp đã tái hiện. Không ép thời lượng tạo giọng; kiểm tra chất lượng trước khi lưu, thử lại có giới hạn. Cân các câu quá nhỏ theo cùng người nói, có giới hạn gain/peak; không thay âm lượng người dùng đã chọn.
- Cải thiện nhập tiếng Việt Windows Telex, dropdown đóng khi bấm lần hai và giao diện focus.
- Cảnh báo sửa phụ đề/Gemini một lần theo phiên; undo đúng nội dung cũ khôi phục trạng thái khớp giọng.
- Sửa play tự bật khi mở project và cải thiện thao tác timeline/preview.
- Danh sách đăng hiển thị mới nhất lên đầu; Đăng tất cả vẫn xử lý từ cũ tới mới.

## Cập nhật và tài nguyên

Hỗ trợ nâng trực tiếp từ **0.1.8, 0.1.9 và 0.1.10** qua **Phiên bản mới → Cập nhật**. Có delta riêng cho từng bản và Core đầy đủ dự phòng. Giữ dữ liệu dự án, thiết lập và model; không xóa release cũ.

Cài mới chỉ cần Setup.exe. Sau cập nhật, mở **Gói tài nguyên** và cập nhật bộ xử lý CPU/CUDA khi app yêu cầu: các sửa tạo giọng cần cả bộ xử lý mới, không chỉ Core. Gói OCR không đổi trong bản này. Giọng đã lưu trước đó không tự bị ghi đè; tạo lại giọng để áp dụng bản sửa âm thanh.

Windows x64, RAM lắp đặt từ 16 GB; RAM trống/Windows commit phải đủ khi xử lý. GPU 4 GB được hỗ trợ theo khả năng từng model; không cam kết tốc độ hay khả năng chạy mọi model trên mọi GPU.

OmniVoice checkpoint vẫn giới hạn phi thương mại. Chỉ dùng media/mẫu giọng có quyền sử dụng. Model phân loại âm sắc ECAPA q8 đi kèm Core theo MIT; đó là dự đoán âm sắc, không phải xác định giới tính cá nhân.

Bản Windows **chưa ký Authenticode**; Windows có thể cảnh báo hoặc chặn theo chính sách. Không tắt phần mềm bảo vệ. ThirdPartySources cung cấp nguồn thư viện tương ứng. Kiểm thử cục bộ/frozen không thay thế ma trận mọi máy Windows hoặc điều kiện mạng thực tế.
