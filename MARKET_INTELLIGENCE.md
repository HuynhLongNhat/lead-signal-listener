# HADES Market Intelligence — standalone V1–V3 prototype

Mục tiêu: theo dõi thị trường và **phát hiện giả thuyết nỗi đau/cơ hội** từ bằng chứng công khai, *không tự nhận lead có nhu cầu mua*.

## Các thành phần

- **V1 — Web research:** SearXNG tìm kết quả, Trafilatura trích xuất nội dung công khai (khi cài dependency). Không cần LLM/token.
- **V2 — Lead Signal Listener:** đọc **read-only** `data/signals.db` của ứng dụng hiện có. Không cần Treg token để xử lý dữ liệu đã thu thập; nguồn mạng xã hội mới vẫn phụ thuộc Treg nếu cần.
- **V3 — Pain & opportunity:** bộ quy tắc tiếng Việt/Anh phát hiện các vấn đề, ý định mua ban đầu, giảm điểm quảng cáo; nhóm theo vấn đề, giữ URL + trích dẫn nguồn; SQLite chống trùng. **Heuristic, chưa có LLM, chưa xác minh nhu cầu thực tế.**

Chưa tích hợp HADES UI/API, không phát sinh API trả phí, không chạy tự động.

## Chạy thử độc lập (Python 3.10+)

```bash
# Trong thư mục repo (vẫn chạy app.py như cũ):
python -m pip install trafilatura

# Khởi động SearXNG riêng, bật `format=json` trong settings.yml.
# Đặt SEARXNG_URL vào http://127.0.0.1:8080 (mặc định).
python -m market_intelligence web --query '"quá tải tin nhắn" cửa hàng' --query '"khó tìm khách" doanh nghiệp' --limit 5

# Dùng dữ liệu đã có trong Lead Signal Listener — không gọi Treg API
python -m market_intelligence listener --listener-db data/signals.db

# Xem nhóm vấn đề và bằng chứng
python -m market_intelligence report

# Chạy test không cần Internet
python -m unittest discover -s tests -p 'test_market_intelligence.py' -v
```

Nếu chưa cài Trafilatura, dùng `--no-extract` để đọc snippet kết quả SearXNG; mode này **không** kiểm tra nội dung trang đầy đủ.

## Kiểm chứng chất lượng thực tế

1. Chọn **một ngành và một địa phương**. Dùng 5–10 truy vấn cụ thể.
2. Ghi lại số URL tìm được, số trùng, số URL nội dung trích xuất thất bại, số kết quả có tín hiệu.
3. Đọc thủ công ngẫu nhiên **30 kết quả** và gắn nhãn: vấn đề thật / suy đoán / quảng cáo / không liên quan.
4. Kiểm tra tên và vị trí doanh nghiệp từ nguồn độc lập nếu muốn tạo lead. **Bản này chưa có xác minh công ty hoặc khu vực từ dữ liệu đầu vào**; không gọi đây là lead qualified.
5. Chỉ thêm LLM khi độ chính xác của bộ lọc cơ bản đã đo được; gửi văn bản mới hoặc kết quả chưa chắc chắn để tiết kiệm token.

## Rủi ro/giới hạn

- SearXNG phải chạy riêng và bật JSON; tùy máy chủ tìm kiếm mà bị giới hạn truy vấn.
- Trafilatura có thể không đọc được trang JavaScript hoặc bị chặn; trường hợp đó dùng snippet với độ tin cậy thấp hơn.
- Chặn URL nội bộ/HTTP redirect và giới hạn 2 MB/trang nhưng **không thay thế chính sách outbound mạng** khi chạy ở máy chủ nhiều người dùng.
- Nhóm theo từ khóa, **không phải semantic clustering**. Chấm điểm *tín hiệu*, không phải xác suất mua.
- Không có API tự động tìm bài Facebook/Zalo miễn phí; dữ liệu LSL chỉ là những gì bạn đã thu thập hợp lệ.
- Dữ liệu được lưu tại `data/market_intelligence.db`; không lưu API keys.
