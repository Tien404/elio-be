# ELIO Backend

Python 3.12+ · FastAPI · MySQL 8.4 · PyMySQL.

Backend cho hệ thống quản lý học tập ELIO: tài khoản và phân quyền, học phần và lớp học,
đội ngũ giảng dạy, học liệu, bài tập cá nhân/nhóm, chấm điểm, quiz, thông báo và tiến độ học tập.

## Chuẩn bị

Cài Python 3.12+, Docker Desktop và Git. Mở Docker Desktop trước khi chạy database.
Các lệnh bên dưới chạy trong thư mục backend.

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.lock.txt
python -m pip install --no-deps --no-build-isolation -e .
cp .env.example .env
```

Windows PowerShell: dùng `py -3.12 -m venv .venv`, `.venv\Scripts\Activate.ps1` và `Copy-Item .env.example .env`.

## Database

```sh
docker compose up -d --wait
python -m scripts.migrate
python -m scripts.seed
python -m scripts.check_database
```

Compose chạy MySQL tại `127.0.0.1:3307`, lưu dữ liệu trong volume `mysql_data`.
Mỗi thành viên chạy database riêng; chia sẻ cấu trúc và dữ liệu mẫu bằng migrations/seed trong Git.

| Biến trong `.env`                | Giá trị lấy ở đâu                                                               |
| -------------------------------- | ------------------------------------------------------------------------------- |
| `MYSQL_PASSWORD`                 | Tự đặt mật khẩu cho user MySQL `elio`; Compose dùng khi tạo volume lần đầu      |
| `MYSQL_ROOT_PASSWORD`            | Tự đặt mật khẩu quản trị MySQL; Compose dùng khi tạo volume lần đầu             |
| `ELIO_DATABASE_URL`              | `mysql://elio:MẬT_KHẨU@127.0.0.1:3307/elio_dev`; mật khẩu khớp `MYSQL_PASSWORD` |
| `ELIO_PRIVATE_FILES_DIR`         | Thư mục lưu file tải lên trên máy chạy backend, mặc định `./data/private`       |
| `ELIO_SELF_REGISTRATION_ENABLED` | Bật/tắt tự đăng ký tài khoản sinh viên, mặc định `false`                        |

Nếu mật khẩu trong URL chứa `@`, `#`, `:`, `/` hoặc `%`, URL-encode phần mật khẩu.
Đổi biến mật khẩu sau khi volume đã tạo không tự đổi mật khẩu bên trong MySQL.
Không commit `.env` hoặc dữ liệu private. Backend dùng PyMySQL, không cần ODBC.

`python -m scripts.migrate` áp dụng các file `sql/migrations` theo thứ tự và bỏ qua migration đã ghi nhận.
Với database đã có dữ liệu, sao lưu trước khi nâng cấp rồi chạy cùng lệnh migrate; không cần xóa schema.
MySQL DDL không rollback toàn bộ migration; nếu áp dụng bị lỗi, kiểm tra schema trước khi chạy tiếp.
Dữ liệu mẫu chỉ chạy với database có tên kết thúc bằng `_dev`; chạy lại không đặt lại mật khẩu hoặc tạo trùng lớp mẫu.

| Tài khoản mẫu        | Mật khẩu khi tạo mới |
| -------------------- | -------------------- |
| `admin@elio.local`   | `ElioDemo@2026`      |
| `teacher@elio.local` | `ElioDemo@2026`      |
| `student@elio.local` | `ElioDemo@2026`      |

Seed tạo bốn lớp Open (CS1001, CS2001, CS2002, CS2003), học liệu TEXT và bài tập có hạn nộp tương đối với ngày tạo. Join codes lần lượt: `ELIO26`, `SQL261`, `WEB261`, `TST261`. Chạy lại seed giữ nguyên dữ liệu và mật khẩu hiện có.
Các tài khoản/mật khẩu này chỉ dùng cho dev local.

## Chạy API

```sh
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Swagger: http://127.0.0.1:8000/docs . Kiểm tra kết nối/schema: http://127.0.0.1:8000/health/ready .
Frontend chạy riêng tại `http://localhost:5173`, proxy `/api` sang backend.
API giữ session cookie và CSRF; các phiên bản ghi dùng contract trong Swagger.

Dừng database bằng `docker compose stop`; chạy lại bằng `docker compose start`.
`docker compose down` giữ volume; **`docker compose down -v` xóa dữ liệu database**.

## Kiểm tra

```sh
python -m pytest -q
ruff check .
ruff format --check .
```

```sh
docker run -d --name elio-mysql-test -p 127.0.0.1:13307:3306 -e MYSQL_ROOT_PASSWORD=elio_test_root -e MYSQL_DATABASE=elio_test -e MYSQL_USER=elio_test -e MYSQL_PASSWORD=elio_test_password mysql:8.4
```

Đợi database sẵn sàng. Trong terminal test, đặt `ELIO_DATABASE_URL` và `ELIO_TEST_DATABASE_URL` cùng bằng
`mysql://elio_test:elio_test_password@127.0.0.1:13307/elio_test`, rồi chạy `python -m scripts.migrate` và `python -m pytest -q`.
macOS: `export TÊN_BIẾN='giá_trị'`; PowerShell: `$env:TÊN_BIẾN='giá_trị'`.

## Tác vụ nền

Chạy định kỳ các lệnh sau bằng cùng cấu hình database và thư mục tệp riêng của API,
ví dụ mỗi phút. Mỗi lần xử lý một batch; gọi tiếp nếu còn dữ liệu chờ xử lý.

```sh
python -m app.worker --process-quizzes
python -m app.worker --cleanup-staging
```

Worker quiz chốt các lượt làm hết giờ, công bố điểm theo cấu hình của quiz và gửi thông báo
vào inbox. Nếu snapshot câu hỏi không thể chấm, kết quả báo `GRADING_ERROR` thay vì gán điểm 0.
Worker staging xóa các tệp tải lên đã hết hạn nhưng chưa được gắn vào nội dung hoặc bài nộp.

## API contract

Swagger mô tả request, response và quyền truy cập của các endpoint. Bản OpenAPI trong
[app/contracts/openapi.json](app/contracts/openapi.json) và danh mục thao tác trong
[app/contracts/catalog.json](app/contracts/catalog.json) được xuất từ các route đang chạy:

```sh
python -m scripts.export_openapi
```

Chạy lệnh này khi thay đổi contract API. Bộ test đối chiếu tài liệu đã xuất với schema runtime.

Phiên đăng nhập dùng cookie và CSRF token. Các thao tác có kiểm soát phiên bản dùng `If-Match`;
xác nhận nộp bài dùng `Idempotency-Key` để có thể thử lại hoặc tra biên nhận khi mất phản hồi.
Tùy chọn tự đăng ký được công bố qua `/api/v1/auth/options` để frontend hiển thị chức năng phù hợp.
