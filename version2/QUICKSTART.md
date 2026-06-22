# Hướng dẫn cài đặt — Rule Detection Database V2

> **Không cần Docker. Không cần Ollama. Chỉ cần Python.**

---

## Yêu cầu tối thiểu

| Thứ cần có | Ghi chú |
|---|---|
| Windows 10/11 | hoặc Linux/macOS |
| Python 3.10+ | [python.org](https://www.python.org/downloads/) |
| Git | [git-scm.com](https://git-scm.com/) |
| Kết nối internet | Chỉ cần cho lần cài đầu tiên |

---

## Các bước cài đặt

### Bước 1 — Tải source code

```powershell
git clone <url-repo>
cd ruleDetectionPublicDatabase\version2
```

---

### Bước 2 — Chạy script cài đặt tự động

```powershell
.\setup.ps1
```

Script sẽ tự động làm:
- ✅ Tạo môi trường Python ảo (`.venv`)
- ✅ Cài tất cả thư viện (`pip install`)
- ✅ Tải model AI embedding (~46 MB, chỉ lần đầu)
- ✅ Tạo database SQLite (`rule_db.db`)
- ✅ Kéo rules từ GitHub và tạo index

> ⏱️ Lần đầu chạy mất khoảng **10–20 phút** (do tải rules từ các GitHub repo).  
> Các lần sau chỉ mất vài giây vì đã có cache.

---

### Bước 3 — Khởi động server

```powershell
.venv\Scripts\python.exe backend\main.py
```

---

### Bước 4 — Mở trình duyệt

```
http://localhost:8000
```

Xong! 🎉

---

## Cập nhật rules mới nhất (tuỳ chọn)

Chạy lệnh sau để đồng bộ rules mới từ GitHub:

```powershell
.venv\Scripts\python.exe backend\ingest.py
```

> Rules cũng tự động cập nhật mỗi đêm 2:00 AM nếu đã đăng ký Task Scheduler trong bước 2.

---

## Khắc phục sự cố nhanh

| Lỗi | Cách sửa |
|---|---|
| `ModuleNotFoundError` | Chạy lại: `.venv\Scripts\python.exe -m pip install -r requirements.txt` |
| Port 8000 bị chiếm | Thay đổi `APP_PORT=8001` trong file `.env` |
| Tìm kiếm không có kết quả | Chạy lại `ingest.py` để index rules |
| Model AI chưa tải | Kết nối internet rồi chạy lại `setup.ps1` |
