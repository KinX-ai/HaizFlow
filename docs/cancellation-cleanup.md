# Hủy tác vụ và dọn file tạm

- Lượt xuất ghi token của từng lần enqueue mà nó tạo. Hủy chỉ gỡ các video
  đang chờ thuộc lượt đó và pause đúng tác vụ active có cùng token. Không dựa
  vào dự án/video đang hiển thị; token cũ không thể dừng lần chạy mới.
- Đang hủy dựng vẫn tính là export busy đến khi producer chạy xong `finally`.
  Cache hoàn thành, các câu TTS đã tạo và file xuất cũ được giữ để chạy tiếp.
- Mỗi lần tải kênh dùng thư mục UUID riêng. Hủy/lỗi tải, lỗi import và callback
  đến sau lệnh hủy đều dọn đúng thư mục đó; không đụng thư mục lần tải mới.
- File xuất dở, thư mục xuất đoạn và thư mục tải bị khóa tạm thời được ghi vào
  `pending-temporary-cleanup.json`, thử dọn lại ở nền và khi mở app sau đó.
  Chỉ xử lý đường dẫn đã ghi nhận; không quét/xóa các cache khác. Kiểm tra
  identity, containment, symlink/junction và project lồng trước khi dọn.
- Không thể xóa ngay khi Windows vẫn giữ khóa hoặc ổ đĩa bị ngắt. File dở
  không được coi là kết quả/cache hợp lệ; dọn lại khi truy cập được.
- Dừng tải gói tài nguyên vẫn giữ phần tải để resume theo cơ chế hiện có;
  thao tác bỏ lượt tải riêng mới xóa phần tải đó.

Kiểm thử: hủy FFmpeg thật khi dựng, hủy giữa lúc copy, callback tải kênh muộn,
chạy lại cùng video, chuyển dự án, giữ file xuất/cache hoàn thành, journal
khởi động lại và khóa file thật bằng Windows `CreateFileW` không chia sẻ.
