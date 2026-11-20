# Panduan Deploy Dashboard: GitHub + Streamlit Community Cloud + TiDB Cloud

Versi online memakai tiga layanan gratis:

| Layanan | Fungsinya |
|---|---|
| **GitHub** (repository private) | Menyimpan kode program |
| **Streamlit Community Cloud** | Menjalankan dashboard dari isi repository GitHub, dengan alamat `nama.streamlit.app` |
| **TiDB Cloud Starter** | Database di internet (kompatibel MySQL), tempat Data Warehouse dan akun login disimpan |

**Mengapa database harus di TiDB, bukan berkas SQLite:** menu Import Data menulis data baru ke database. Server
Streamlit tidak menyimpan berkas secara permanen; setiap kali aplikasi tidur, dimulai ulang, atau kode di GitHub
diperbarui, berkas di server kembali seperti semula, dan berkas di folder program bahkan tidak boleh diubah
(muncul pesan "attempt to write a readonly database"). Database di TiDB Cloud tidak terpengaruh, sehingga hasil
import tersimpan permanen.

TiDB Cloud Starter gratis sampai 5 GiB penyimpanan dan 50 juta Request Unit per bulan, tanpa kartu kredit. Data
peternakan ini hanya beberapa MB. TiDB mewajibkan koneksi terenkripsi; program sudah mendukungnya lewat akhiran
`?ssl=true` pada alamat database (lihat db.py).

> **Sebelum mulai:** data ternak akan disimpan di server pihak ketiga (TiDB Cloud, GitHub, Streamlit) di luar negeri.
> Pastikan PT. Amana Albaroqh Farm mengizinkan, dan repository GitHub bersifat **Private**.

Waktu yang dibutuhkan: sekitar 30 sampai 45 menit.

---

## Langkah A - Buat database di TiDB Cloud

1. Buka https://tidbcloud.com dan daftar (bisa dengan akun Google atau GitHub).
2. Klik **Create Resource**, pilih jenis **Starter** (gratis), cloud **AWS**, region **Singapore (ap-southeast-1)**.
   Batas biaya (spending limit) biarkan 0.
3. Tunggu sampai status **Available**, lalu klik **Connect**. Klik **Reset Password** (atau Generate Password),
   lalu salin kata sandinya lewat tombol salin. Kata sandi hanya ditampilkan sekali. Catat:
   - **HOST** (bentuknya: `gateway01.ap-southeast-1.prod.aws.tidbcloud.com`)
   - **PORT**: `4000`
   - **USERNAME** (berawalan kode, bentuknya: `3xAbCdEf.root`)
   - **PASSWORD**
4. Sertifikat CA tidak perlu diunduh; program memakai sertifikat dari paket certifi.

Bila kata sandi memuat karakter `@ : / ? # %`, buat ulang sampai hanya berisi huruf dan angka. Hindari mengetik ulang
kata sandi: huruf `0`/`O` dan `l`/`I`/`1` mudah tertukar.

## Langkah B - Isi database TiDB dari laptop

Buka PowerShell di folder program, lalu jalankan satu per satu. Pada baris pertama, tempel kata sandi TiDB;
baris kedua dan ketiga menyusun alamat database secara otomatis.

```powershell
$SANDI = "TEMPEL_KATA_SANDI_TIDB"
$HOSTDB = "USERNAME_TIDB:$SANDI@HOST_TIDB:4000"
$env:DB_URL = "mysql+pymysql://$HOSTDB/dw_amana_farm?ssl=true"

pip install -r requirements.txt

# 1) Hitung K-Means (membuat folder hasil_pra_etl)
python pra_etl_kmeans.py --excel Data_Ternak_2022-2026.xlsx --out hasil_pra_etl

# 2) Buat database dan 9 tabel. Alamatnya TANPA nama database, karena dw_amana_farm belum ada.
python jalankan_ddl.py --db "mysql+pymysql://$HOSTDB/?ssl=true"

# 3) Isi data dari Excel
python etl_dw.py --excel Data_Ternak_2022-2026.xlsx --pra hasil_pra_etl --mysql $env:DB_URL

# 4) Pastikan data cocok dengan Excel (harus "RINGKASAN: 18/18 lulus")
python 03_rekonsiliasi.py --excel Data_Ternak_2022-2026.xlsx --pra hasil_pra_etl --mysql $env:DB_URL

# 5) Buat akun login, lalu atur kata sandinya
python buat_pengguna.py --db $env:DB_URL init
python buat_pengguna.py --db $env:DB_URL sandi manajer
python buat_pengguna.py --db $env:DB_URL sandi supervisor
python buat_pengguna.py --db $env:DB_URL sandi pakan

# 6) Coba dashboard di laptop dengan data dari TiDB
python -m streamlit run app.py
```

Ganti `USERNAME_TIDB` dan `HOST_TIDB` dengan data dari Langkah A. Perintah nomor 3 membutuhkan beberapa menit
karena data dikirim ke server. Pada nomor 5, kata sandi login diketik dua kali dan memang tidak tampil di layar;
bila salah ketik, jalankan ulang perintah yang sama.

Pada nomor 6 dashboard tampil di `localhost`: programnya berjalan di laptop, tetapi datanya diambil dari TiDB.
Bila sudah bisa login dan semua tab tampil, lanjutkan ke Langkah C. Variabel `$SANDI` dan `$env:DB_URL` hanya
berlaku di jendela PowerShell ini; setelah jendela ditutup, dashboard lokal kembali memakai MySQL XAMPP.

## Langkah C - Unggah program ke GitHub

1. Masuk ke https://github.com, klik **New repository**, beri nama misalnya `dashboard-amana-farm`,
   pilih **Private**, lalu **Create repository**.
2. Klik **uploading an existing file** (atau **Add file > Upload files**), lalu unggah berkas berikut dan klik
   **Commit changes**:

| Diunggah | Jangan diunggah |
|---|---|
| app.py, auth.py, queries.py, db.py, impor.py | Berkas Excel (.xlsx) |
| pra_etl_kmeans.py, etl_dw.py, 03_rekonsiliasi.py | Berkas database (.sqlite) |
| requirements.txt | Folder hasil_pra_etl dan arsip_impor |
| .streamlit/config.toml (opsional, untuk tema terang) | Berkas apa pun yang berisi kata sandi |

Berkas pra_etl_kmeans.py, etl_dw.py, dan 03_rekonsiliasi.py wajib ikut karena dipakai menu Import Data.
Untuk mengunggah config.toml, buat folder `.streamlit` lewat **Add file > Create new file** dengan nama
`.streamlit/config.toml`, lalu salin isinya.

## Langkah D - Jalankan di Streamlit Community Cloud

1. Buka https://share.streamlit.io dan masuk dengan akun GitHub.
2. Klik **Create app**, pilih repository `dashboard-amana-farm`, branch `main`, dan main file `app.py`.
3. Buka **Advanced settings > Secrets**, lalu isi satu baris berikut (lengkap dengan tanda kutip):

   ```toml
   DB_URL = "mysql+pymysql://USERNAME_TIDB:KATA_SANDI_TIDB@HOST_TIDB:4000/dw_amana_farm?ssl=true"
   ```
4. Klik **Deploy** dan tunggu beberapa menit.

Untuk mengubah Secrets di kemudian hari: di share.streamlit.io klik **⋮ > Settings > Secrets**, simpan, lalu
**Manage app > ⋮ > Reboot app**.

## Langkah E - Uji versi online

1. Buka alamat aplikasi dan login sebagai **manajer** dengan kata sandi dari Langkah B nomor 5.
2. Pastikan judul menampilkan "Data sampai ..." dan tab **Import Data** tersedia.
3. Di tab Import Data, kotak biru "Database saat ini berupa berkas SQLite" **tidak** boleh muncul. Bila muncul,
   Secrets belum berisi alamat TiDB.
4. Unggah `Data_Ternak_2022-2026.xlsx`, klik **Proses import**, dan pastikan muncul
   "Import berhasil ... rekonsiliasi 18/18 lulus".

---

## Memperbarui data

Cukup dari dashboard: login sebagai Manajer Operasional, buka tab **Import Data**, unggah berkas Excel terbaru
(berkas lengkap, bukan hanya data baru), periksa perbandingannya, lalu klik **Proses import**. Tidak perlu PowerShell
dan tidak perlu mengunggah apa pun ke GitHub. Akun login tidak terhapus.

Mengubah program: unggah ulang berkas .py yang berubah ke GitHub; Streamlit memperbarui aplikasi dalam sekitar
satu menit tanpa reboot. Mengganti kata sandi atau menambah akun: jalankan `buat_pengguna.py --db "ALAMAT_TIDB" ...`
dari laptop.

## Memberikan akses ke pengguna

Aplikasi dari repository private otomatis bersifat **private**. Di halaman aplikasi, klik **Share** (kanan atas),
lalu masukkan email pengguna. Mereka masuk dengan akun Google atau tautan email, lalu login dengan akun dashboard
sesuai perannya. Jadi ada dua lapis keamanan: undangan Streamlit dan login dashboard berbasis peran.

## Batasan layanan gratis

| Hal | Keterangan |
|---|---|
| Aplikasi tidur | Bila 12 jam tanpa pengunjung, aplikasi tidur. Pengunjung berikutnya klik tombol untuk membangunkan dan menunggu sekitar 1 menit. Data tetap aman di TiDB. |
| Aplikasi private | Hanya 1 aplikasi private per akun Streamlit. |
| Kuota TiDB | Bila kuota bulanan habis, koneksi baru ditolak sampai bulan berikutnya. Untuk data peternakan ini kuotanya jauh dari habis. |
| Lama proses import | Sekitar setengah sampai beberapa menit, karena data dikirim ke server TiDB. Jangan tutup halaman sampai muncul "Import berhasil". |
| Arsip berkas import | Salinan berkas di folder `arsip_impor` di server tidak tersimpan permanen. Simpan berkas Excel asli di komputer peternakan. |

## Jika ada masalah

| Pesan / gejala | Penyebab | Solusi |
|---|---|---|
| `Access denied for user` | Username atau kata sandi TiDB salah | Salin ulang dari halaman Connect TiDB; perhatikan awalan kode pada username |
| `Connections using insecure transport are prohibited` / error SSL | `?ssl=true` lupa ditulis | Tambahkan `?ssl=true` di akhir alamat |
| `Unknown database 'dw_amana_farm'` | Database belum dibuat | Jalankan Langkah B nomor 2 (alamat tanpa nama database) |
| `attempt to write a readonly database` saat import | Secrets masih memakai SQLite | Ganti Secrets dengan alamat TiDB (Langkah D), lalu Reboot app |
| Kotak biru "Database saat ini berupa berkas SQLite" | Secrets masih memakai SQLite | Sama seperti di atas |
| `ModuleNotFoundError` di Streamlit | Berkas .py atau requirements.txt belum diunggah | Unggah ulang berkas pada Langkah C |
| Tidak dapat terhubung ke database | Secrets salah atau belum disimpan | Periksa baris DB_URL di Secrets, lalu Reboot app |
| Login ditolak padahal kata sandi benar | Akun belum dibuat di TiDB | Ulangi Langkah B nomor 5 |
| Tab kosong padahal login berhasil | Data belum dimuat ke TiDB | Ulangi Langkah B nomor 3, atau import dari tab Import Data |
| Tampilan gelap | .streamlit/config.toml tidak ada di repository | Unggah berkas tersebut (opsional) |
