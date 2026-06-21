# Hướng dẫn Di chuyển Rule Detection Database sang Máy tính khác

Tài liệu này hướng dẫn chi tiết các bước để đóng gói, di chuyển và cài đặt ứng dụng **Rule Detection Database** sang một máy tính mới một cách nhanh chóng nhất.

---

## Giai đoạn 1: Đóng gói dữ liệu (Tại Máy hiện tại)

Tệp cơ sở dữ liệu đã được xuất sẵn ra tệp tin `rule_db_backup.sql` ở thư mục gốc. Để đóng gói, anh chỉ cần nén (Zip) thư mục dự án lại và loại bỏ các thư mục rác/tự sinh để giảm dung lượng file nén:

*   **Các tệp CẦN giữ lại và nén gửi đi:**
    *   📁 `backend/` (Toàn bộ mã nguồn API và giao diện web)
    *   📄 `rule_db_backup.sql` (Bản sao lưu dữ liệu rules & vector embeddings nặng ~68MB)
    *   📄 `docker-compose.yml` (Cấu hình container cơ sở dữ liệu)
    *   📄 `setup.ps1` và `setup.sh` (Kịch bản tự động cài đặt hệ thống)
    *   📄 `backup_db.ps1` / `backup_db.sh` và `restore_db.ps1` / `restore_db.sh`
    *   📄 `cron_sync.ps1` / `cron_sync.sh`
    *   📄 `requirements.txt`
    *   📄 `README.md` và `MIGRATION.md` (Chính là tệp này)

*   **Các thư mục NÊN xóa trước khi nén (vì sẽ tự sinh lại ở máy mới):**
    *   ❌ `.venv/` hoặc `.venv_linux/` (Thư mục ảo Python)
    *   ❌ `rules_repositories/` (Thư mục đệm lưu các repo rules đã tải về)
    *   ❌ `.last_sync` (Tệp đánh dấu thời gian đồng bộ gần nhất)

---

## Giai đoạn 2: Chuẩn bị Môi trường (Tại Máy tính mới)

Trước khi tiến hành cài đặt, hãy đảm bảo máy tính mới đã cài đặt các công cụ sau:

1.  **WSL2 (Windows Subsystem for Linux)**: Khuyên dùng phiên bản Ubuntu (Ubuntu 22.04 LTS hoặc 24.04 LTS).
2.  **Docker Desktop**: Đã cài đặt trên Windows và kích hoạt liên kết với WSL2 (WSL Integration).
3.  **Ollama**:
    *   Tải và cài đặt Ollama trên Windows.
    *   Thiết lập biến môi trường hệ thống của Windows: **`OLLAMA_HOST=0.0.0.0`** (bắt buộc để container database và WSL2 kết nối được với mô hình AI trên Windows).
    *   Khởi chạy Ollama Desktop và chạy lệnh sau trong cmd hoặc PowerShell để tải mô hình AI tạo vector:
        ```cmd
        ollama pull all-minilm
        ```
4.  **Git**: Cài đặt trên máy để phục vụ cập nhật rules.

---

## Giai đoạn 3: Thực hiện Cài đặt và Khởi chạy

Giải nén thư mục dự án trên máy mới (Ví dụ giải nén vào ổ `D:\ruleDetectionPublicDatabase`) và lựa chọn một trong hai phương án chạy dưới đây:

### Phương án A: Chạy Backend trên Windows Host (Khuyên dùng)

1.  Mở **PowerShell** với quyền Quản trị viên (**Run as Administrator**).
2.  Di chuyển vào thư mục dự án:
    ```powershell
    cd D:\ruleDetectionPublicDatabase
    ```
3.  Chạy lệnh cài đặt tự động:
    ```powershell
    Set-ExecutionPolicy Bypass -Scope Process -Force
    .\setup.ps1
    ```
    *   *Kịch bản `setup.ps1` sẽ tự động phát hiện tệp `rule_db_backup.sql` và khôi phục toàn bộ hơn 9,000 rules cùng vector embeddings vào Docker PostgreSQL trong WSL ngay lập tức.*
4.  Khởi chạy máy chủ Web:
    ```powershell
    .venv\Scripts\python.exe backend/main.py
    ```
5.  Mở trình duyệt truy cập: `http://localhost:8000` (hoặc cổng hiển thị trong log đầu ra).

---

### Phương án B: Chạy Backend bên trong WSL2 Linux

1.  Mở terminal **Ubuntu (WSL2)**.
2.  Di chuyển vào thư mục dự án (được Windows tự động gắn kết qua `/mnt/`):
    ```bash
    cd /mnt/d/ruleDetectionPublicDatabase
    ```
3.  Cấp quyền và chạy kịch bản cài đặt tự động:
    ```bash
    chmod +x setup.sh restore_db.sh backup_db.sh cron_sync.sh
    ./setup.sh
    ```
4.  Khởi chạy máy chủ Web:
    ```bash
    .venv_linux/bin/python backend/main.py
    ```
5.  Mở trình duyệt truy cập: `http://localhost:8000`.

---

## Giai đoạn 4: Nghiệm thu (Pre-launch Checklist)

*   [ ] **Giao diện Web**: Hiển thị chính xác logo **Rule Detection Database**, biểu đồ thống kê hiển thị số lượng > 9,000 rules.
*   [ ] **Tìm kiếm AI**: Tìm thử *"credential dumping"* bằng chế độ `semantic` hoặc `hybrid` cho kết quả khớp chính xác kèm độ tương đồng tỷ lệ phần trăm `% Match`.
*   [ ] **Gán nhãn thủ công**: Chọn một rule bất kỳ, thử thêm nhãn (Tag) và xóa nhãn hoạt động bình thường.
*   [ ] **Trình đồng bộ tự động**: Vào nút Cài đặt (Settings), bấm nút **Sync Repositories Now** để chạy thử đồng bộ hóa nền.
