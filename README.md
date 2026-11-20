# Dashboard Monitoring Bobot Ternak dan Segmentasi K-Means
PT. Amana Albaroqh Farm

Program ini mengolah data pencatatan kambing (Excel) menjadi Data Warehouse, mengelompokkan performa kambing
dengan K-Means, dan menampilkannya di dashboard Streamlit yang dilengkapi login per peran.

Alur data:

```
Excel  ->  pra_etl_kmeans.py  ->  etl_dw.py  ->  Data Warehouse (MySQL / TiDB)  ->  app.py (dashboard)
           (K-Means)              (ETL)                                              03_rekonsiliasi.py (pemeriksaan)
```

Setelah program berjalan, data terbaru cukup diunggah lewat menu **Import Data** di dashboard, tanpa PowerShell.

## Isi folder

| Berkas | Fungsi |
|---|---|
| app.py | Dashboard Streamlit: angka ringkasan dan enam tab (lihat bagian "Isi dashboard") |
| queries.py | Query SQL yang dipakai dashboard |
| auth.py | Login, penyimpanan kata sandi (hash), dan hak akses tab per peran |
| impor.py | Menu Import Data: memeriksa berkas Excel, lalu menjalankan K-Means, ETL, dan rekonsiliasi |
| db.py | Koneksi database bersama (MySQL lokal, TiDB Cloud, atau SQLite untuk uji) |
| pra_etl_kmeans.py | Tahap pra-ETL: fitur kambing, penentuan K (Elbow + Silhouette), K-Means |
| etl_dw.py | ETL: Excel + hasil pra-ETL menjadi tabel dimensi dan fakta |
| 03_rekonsiliasi.py | Mencocokkan isi Data Warehouse dengan Excel (18 pemeriksaan) |
| 01_ddl_mysql.sql | Membuat database dw_amana_farm dan 9 tabelnya |
| jalankan_ddl.py | Menjalankan 01_ddl_mysql.sql tanpa phpMyAdmin (untuk TiDB Cloud) |
| buat_pengguna.py | Membuat dan mengelola akun login |
| uji_auth.py | Menguji logika login tanpa browser |
| requirements.txt | Daftar paket Python |
| .streamlit/config.toml | Tema tampilan dashboard (terang) |
| .streamlit/secrets.toml.contoh | Contoh isi Secrets untuk versi online |
| .gitignore | Berkas yang tidak ikut diunggah ke GitHub (data, database lokal, kata sandi) |
| PANDUAN_DEPLOY.md | Cara menjalankan dashboard secara online |

Folder **.streamlit** sering tersembunyi di Windows Explorer karena namanya diawali titik. Bila tidak ikut tersalin,
dashboard tetap berjalan, hanya warnanya mengikuti tema komputer.

## Persiapan (sekali saja)

1. Taruh `Data_Ternak_2022-2026.xlsx` di folder ini, di samping berkas .py.
2. Buka PowerShell di folder ini: buka folder di File Explorer, klik kolom alamat, ketik `powershell`, tekan Enter.
3. Pasang paket:
   ```
   pip install -r requirements.txt
   ```
4. Nyalakan MySQL di XAMPP Control Panel (tombol **Start** pada baris MySQL). Kata sandi root dianggap kosong;
   bila memakai kata sandi, lihat bagian "Mengganti alamat database".

Jalankan perintah di bawah satu per satu dan tunggu tiap perintah selesai.

## Langkah 1 - Hitung K-Means

```
python pra_etl_kmeans.py --excel Data_Ternak_2022-2026.xlsx --out hasil_pra_etl
```

Berhasil bila muncul `Dipakai: K=4` dan folder **hasil_pra_etl** berisi 9 berkas:

| Berkas | Isi |
|---|---|
| label_klaster.csv | Segmen, rasio ADG, dan rasio bobot tiap kambing per rentang umur |
| dim_usia.csv | 7 rentang umur (isi tabel dim_usia) |
| dim_segmen.csv | 5 segmen termasuk Tidak Diklaster (isi tabel dim_segmen) |
| validasi_k.csv | WCSS dan Silhouette untuk K = 2 sampai 8 |
| fitur_semua_fase.csv | Fitur semua kambing per rentang umur, termasuk yang tidak ikut dikelompokkan |
| centroid.csv | Pusat tiap klaster (dalam satuan rasio) |
| keputusan_k.txt | Aturan dan alasan pemilihan K |
| validasi_k.png | Grafik Elbow dan Silhouette |
| scatter_klaster.png | Peta klaster (rasio ADG terhadap rasio bobot) |

Aturan pemilihan K: K kandidat adalah titik siku kurva WCSS (Elbow), dan dipakai bila nilai Silhouette-nya minimal
97% dari Silhouette tertinggi. Bila tidak, dipilih K terkecil yang memenuhi batas tersebut.

## Langkah 2 - Buat tabel di MySQL

Buka http://localhost/phpmyadmin, pilih tab **Import**, pilih `01_ddl_mysql.sql`, lalu klik **Import**.
Berhasil bila database **dw_amana_farm** memiliki 9 tabel:

- 4 dimensi: dim_waktu, dim_kambing, dim_usia, dim_segmen
- 2 fakta: fact_bobot_ternak, fact_konsumsi_pakan
- 2 pendukung K-Means: hasil_klaster, hasil_validasi_k
- 1 akun login: pengguna

Langkah ini mengosongkan delapan tabel pertama. Tabel **pengguna** tidak dihapus, sehingga akun login tetap ada.
Bila phpMyAdmin menampilkan `Note: #1050 Table 'pengguna' already exists`, itu hanya pemberitahuan, bukan error.

## Langkah 3 - Muat data (ETL)

```
python etl_dw.py --excel Data_Ternak_2022-2026.xlsx --pra hasil_pra_etl
```

Berhasil bila di akhir tertulis `MySQL terisi.` dengan jumlah baris: dim_waktu 1695, dim_kambing 158, dim_usia 7,
dim_segmen 5, fact_bobot_ternak 15367, fact_konsumsi_pakan 1695, hasil_klaster 650, hasil_validasi_k 7.

## Langkah 4 - Rekonsiliasi (memastikan data cocok dengan Excel)

```
python 03_rekonsiliasi.py --excel Data_Ternak_2022-2026.xlsx --pra hasil_pra_etl --mysql "mysql+pymysql://root:@localhost/dw_amana_farm"
```

Berhasil bila keluaran diakhiri `RINGKASAN: 18/18 lulus`. Hasilnya juga disimpan di `hasil_rekonsiliasi.csv`.

## Langkah 5 - Buat akun login

```
python buat_pengguna.py init
```

Berhasil bila muncul `manajer: ditambahkan`, `supervisor: ditambahkan`, dan `pakan: ditambahkan`.
Perintah ini aman diulang; akun yang sudah ada dilewati.

## Langkah 6 - Jalankan dashboard

```
python -m streamlit run app.py
```

Browser membuka http://localhost:8501 dan menampilkan halaman login. Hentikan dengan Ctrl+C di PowerShell.
Gunakan `python -m streamlit`, bukan `streamlit` saja, agar PowerShell pasti menemukannya.

## Login dan hak akses

| Username | Peran | Kata sandi awal | Tab yang tampil |
|---|---|---|---|
| manajer | Manajer Operasional | Manajer@2026 | Semua tab: Bobot dan ADG, Segmentasi, Monitoring, Pakan dan FCR, Validasi K, Import Data |
| supervisor | Supervisor Peternakan | Supervisor@2026 | Bobot dan ADG, Segmentasi, Monitoring |
| pakan | Tim Produksi Pakan | Pakan@2026 | Pakan dan FCR |

Kata sandi awal wajib diganti sebelum dashboard dipakai di peternakan.

| Tujuan | Perintah |
|---|---|
| Lihat daftar akun | `python buat_pengguna.py daftar` |
| Ganti kata sandi | `python buat_pengguna.py sandi manajer` |
| Tambah akun (peran: manajer, supervisor, atau pakan) | `python buat_pengguna.py tambah budi supervisor` |
| Nonaktifkan akun | `python buat_pengguna.py aktif budi 0` |
| Aktifkan lagi | `python buat_pengguna.py aktif budi 1` |

- Kata sandi disimpan sebagai hash PBKDF2-SHA256, bukan teks biasa.
- Setelah 5 kali salah berturut-turut, login dikunci selama 60 detik. Tombol **Keluar** ada di sidebar.
- Tab yang boleh dibuka tiap peran diatur pada `PERAN` di auth.py.
- Untuk database selain MySQL lokal tanpa kata sandi, tambahkan `--db "ALAMAT"` sebelum perintah, misalnya
  `python buat_pengguna.py --db "mysql+pymysql://root:abc123@localhost/dw_amana_farm" init`.
- Menguji logika login tanpa browser: `python uji_auth.py` (hasil yang benar: `SEMUA LULUS`).

## Isi dashboard

Bagian atas menampilkan angka ringkasan: total kambing, kambing hidup, rata-rata ADG, bobot rata-rata kambing hidup,
pakan per ekor, dan persentase status ternak (hidup, terjual, mati). Setiap tab diawali kotak "Halaman ini menjawab",
dan sidebar berisi penjelasan istilah.

| Tab | Isi |
|---|---|
| Bobot dan ADG | Tren bobot dan ADG bulanan, dapat difilter per ras dan kategori usia; rata-rata ADG per ras dan usia |
| Segmentasi | Komposisi segmen, peta klaster, dan daftar kambing per segmen (dapat diunduh sebagai CSV) |
| Monitoring | Status tiap kambing dan bagan kendali ADG bulanan serta pakan per ekor |
| Pakan dan FCR | Konsumsi pakan harian, pakan per ekor, dan FCR bulanan tingkat populasi |
| Validasi K | Kurva Elbow dan Silhouette serta alasan pemilihan K |
| Import Data | Memperbarui data dari berkas Excel (hanya Manajer Operasional) |

**Status monitoring** diturunkan dari segmen pada rentang umur terbaru tiap kambing:

| Segmen | Status |
|---|---|
| Performa Tinggi, Rata-rata | Normal |
| Tumbuh Cepat Bobot Rendah, Bobot Tinggi Tumbuh Lambat | Waspada |
| Perlu Perhatian | Perlu Tindakan |
| Tidak Diklaster (kurang dari 3 nilai ADG) | Belum Dinilai |

Daftar diurutkan dari skor terendah (skor = rata-rata rasio ADG dan rasio bobot; 1,0 = setara kambing sebaya).
Bagan kendali memakai garis tengah (CL) = rata-rata semua bulan dan batas atas/bawah = CL ± 3 simpangan baku;
titik di luar batas dilingkari merah. Aturan status dapat diubah pada `STATUS_SEGMEN` di app.py.

## Memperbarui data (menu Import Data)

1. Login sebagai **manajer**, buka tab **Import Data**.
2. Unggah berkas Excel **lengkap** (seluruh data sejak awal pencatatan ditambah data terbaru), dengan nama sheet dan
   kolom yang sama seperti `Data_Ternak_2022-2026.xlsx`.
3. Sistem memeriksa berkas. Bila ada kesalahan, muncul daftar perbaikan beserta nomor baris Excel, dan data saat ini
   tidak berubah.
4. Periksa tabel perbandingan "Saat ini" dan "Berkas baru". Bila jumlah data berkurang, centang konfirmasi.
5. Klik **Proses import**. Sistem menjalankan K-Means, ETL, dan rekonsiliasi secara berurutan.

Bila berhasil, semua tab langsung memakai data baru, berkas disalin ke folder **arsip_impor**, dan folder
**hasil_pra_etl** diperbarui. Bila proses gagal atau rekonsiliasi tidak seluruhnya lulus, isi Data Warehouse
dikembalikan seperti sebelum import. K dipilih ulang dengan aturan yang sama seperti Langkah 1; nilai K dapat
ditetapkan sendiri di "Pengaturan lanjutan". Bila K berubah, dashboard memberi tahu.

## Mengganti alamat database

Bentuk alamat: `mysql+pymysql://USER:PASSWORD@HOST/dw_amana_farm`
Contoh MySQL dengan kata sandi "abc123": `mysql+pymysql://root:abc123@localhost/dw_amana_farm`

- ETL: tambahkan `--mysql "ALAMAT"` pada perintah etl_dw.py.
- Rekonsiliasi: ganti alamat pada perintah Langkah 4.
- Akun: tambahkan `--db "ALAMAT"` pada perintah buat_pengguna.py.
- Dashboard: jalankan `$env:DB_URL = "ALAMAT"` di PowerShell, lalu `python -m streamlit run app.py`.

Variabel `$env:DB_URL` hanya berlaku di jendela PowerShell tempat perintah itu dijalankan.

## Uji tanpa MySQL (opsional)

```
python etl_dw.py --excel Data_Ternak_2022-2026.xlsx --pra hasil_pra_etl --sqlite dw_uji.sqlite
python buat_pengguna.py --db sqlite:///dw_uji.sqlite init
$env:DB_URL = "sqlite:///dw_uji.sqlite"
python -m streamlit run app.py
```

## Menjalankan secara online

Ikuti **PANDUAN_DEPLOY.md**: kode disimpan di GitHub (repository private), dashboard dijalankan di Streamlit
Community Cloud, dan database disimpan di TiDB Cloud (kompatibel MySQL). Database online harus berupa MySQL/TiDB,
karena server Streamlit tidak menyimpan berkas secara permanen sehingga hasil Import Data ke berkas SQLite akan hilang.

## Jika ada masalah

| Pesan | Penyebab | Solusi |
|---|---|---|
| `the following arguments are required` | Perintah tidak lengkap | Salin perintah utuh dari panduan ini |
| `streamlit is not recognized` | PowerShell tidak menemukan streamlit | Pakai `python -m streamlit run app.py` |
| `No such file ... xlsx` | Excel tidak ada di folder ini | Salin Data_Ternak_2022-2026.xlsx ke folder ini |
| `Can't connect to MySQL server` / `Access denied` | MySQL belum menyala atau kata sandi salah | Start MySQL di XAMPP, atau ganti alamat database |
| `Table ... doesn't exist` | Tabel belum dibuat | Jalankan Langkah 2 |
| `ModuleNotFoundError` | Paket belum terpasang | `pip install -r requirements.txt` |
| Halaman login: "Tabel pengguna belum siap" | Akun belum dibuat | Jalankan Langkah 5 |
| Dashboard berwarna gelap | Folder .streamlit tidak ikut tersalin | Salin folder .streamlit ke folder program |
