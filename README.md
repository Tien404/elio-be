# ELIO Backend

Python/FastAPI · SQL Server · pyodbc

- [Hướng dẫn triển khai](docs/GUIDE.md): kiến trúc, nghiệp vụ, database, thứ tự làm và contract cần làm rõ.
- [API Explorer](docs/api-explorer.html):78 operations,44 ưu tiên MVP; request, quyền, response và service tương ứng.

## Cài đặt

Python3.12+. Chạy tại thư mục project:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.lock.txt
python -m pip install --no-deps --no-build-isolation -e .
cp .env.example .env
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

PowerShell: `py -3.12 -m venv .venv`, `.venv\Scripts\Activate.ps1`, `Copy-Item .env.example .env`.
Swagger: http://127.0.0.1:8000/docs . ReDoc: http://127.0.0.1:8000/redoc .

## Kết nối SQL Server

1. Chuẩn bị SQL Server instance và database dev cách ly, ví dụ elio_dev.
2. Cài [Microsoft ODBC Driver18](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server) đúng kiến trúc; macOS/Linux cần ODBC driver manager. Client Mac ARM64 kết nối SQL Server trên Windows/Linux x64.
3. Đặt trong .env bằng credentials riêng:

```dotenv
ELIO_ODBC_CONNECTION_STRING='DRIVER={ODBC Driver 18 for SQL Server};SERVER=tcp:YOUR_HOST,1433;DATABASE=elio_dev;UID=YOUR_APP_USER;PWD=YOUR_PRIVATE_PASSWORD;Encrypt=yes;TrustServerCertificate=no;'
```

Dùng account ứng dụng giới hạn quyền; schema scripts dùng quyền DDL riêng. Local self-signed certificate có thể dùng TrustServerCertificate=yes chỉ trong dev. Không commit .env hoặc private files.

```sh
python -c "import pyodbc; print(pyodbc.drivers())"
python -m scripts.check_database
```

Check chỉ đọc, exit0 khi kết nối/check thành công; exit1 khi chưa sẵn sàng. Không tự tạo schema.

## Kiểm tra

```sh
python -m pytest -q
ruff check .
ruff format --check .
python -m app.worker --check
```
