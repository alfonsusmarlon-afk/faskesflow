# Klinik SKEM - FaskesFlow 🏥

Sistem Administrasi Pasien, Manajemen Antrean, Verifikasi Berkas, dan Rujukan Terintegrasi ke Faskes Tingkat 2 berbasis Web.

## 🚀 Fitur Utama

- **Portal Pasien (Patient Portal):**
  - Ringkasan pendaftaran kunjungan & pemantauan nomor antrean secara realtime.
  - Pendaftaran mandiri dengan fitur simpan draft otomatis.
  - Tindakan perbaikan berkas terintegrasi jika ditemukan kekurangan dokumen.
  - Pemantauan resep obat farmasi dan status peracikan obat.
  - Riwayat kunjungan & rujukan ke faskes tingkat 2.
  - Manajemen multi-profil pasien (keluarga/tanggungan).

- **Portal Petugas Klinik (Facility Portal):**
  - Dashboard operasional kunjungan klinik.
  - Verifikasi pendaftaran online & permintaan perbaikan berkas ke pasien.
  - Manajemen antrean loket dan pemanggilan antrean berikutnya secara realtime.
  - Modul resep obat & farmasi (input resep, peracikan, penyerahan obat, cetak, dan hapus resep).
  - Alur rujukan elektronik ke Fasilitas Kesehatan Tingkat 2.
  - Pendaftaran pasien walk-in langsung di tempat.

- **Portal Admin Sistem (System Portal):**
  - Dashboard performa sistem dan log aktivitas.
  - Manajemen akun dan hak akses pengguna.
  - Konfigurasi poli, layanan klinik, dan faskes rujukan mitra.

## 🛠️ Teknologi & Arsitektur

- **Backend:** Python (Flask Framework), Werkzeug (ProxyFix)
- **Frontend:** Jinja2 Template Engine, HTML5 Semantic, Modern Responsive CSS
- **Autentikasi:** Session-based Authentication & Dukungan Google Identity Services (OAuth 2.0)
- **State Management:** In-memory operational store & realtime client polling API

## LOGIN WEBSITE
pasien
-username : pasien@local
-password : password123

petugas faskes
-username : petugas@local
-password : password123

admin
-username : admin@local
-password : password123

## 💻 Cara Menjalankan Aplikasi

1. **Clone repository:**
   ```bash
   git clone <URL_REPOSITORY_ANDA>
   cd rujukready
   ```

2. **Buat dan aktifkan virtual environment (opsional namun disarankan):**
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # Linux/macOS:
   source venv/bin/activate
   ```

3. **Install dependensi:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Jalankan aplikasi:**
   ```bash
   python app.py
   ```

5. **Akses di browser:**
   Buka `http://127.0.0.1:5001`

