-- Data Warehouse PT. Amana Albaroqh Farm (skema fact constellation, model dimensional Kimball)
-- Lokal: impor berkas ini lewat phpMyAdmin. Online (TiDB Cloud): python jalankan_ddl.py --db "ALAMAT"
-- Setelah itu isi datanya dengan etl_dw.py.
-- Perhatian: delapan tabel Data Warehouse dihapus lalu dibuat ulang kosong. Tabel pengguna tidak dihapus.
CREATE DATABASE IF NOT EXISTS dw_amana_farm CHARACTER SET utf8mb4;
USE dw_amana_farm;

SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS hasil_klaster;
DROP TABLE IF EXISTS fact_konsumsi_pakan;
DROP TABLE IF EXISTS fact_bobot_ternak;
DROP TABLE IF EXISTS dim_segmen;
DROP TABLE IF EXISTS dim_usia;
DROP TABLE IF EXISTS dim_kambing;
DROP TABLE IF EXISTS dim_waktu;
DROP TABLE IF EXISTS hasil_validasi_k;
SET FOREIGN_KEY_CHECKS = 1;

-- Dimensi waktu: satu baris per tanggal
CREATE TABLE dim_waktu (
  id_waktu INT AUTO_INCREMENT PRIMARY KEY,
  tanggal DATE NOT NULL UNIQUE,
  hari TINYINT, minggu_ke_tahun TINYINT, bulan TINYINT,
  nama_bulan VARCHAR(12), kuartal TINYINT, tahun SMALLINT
);

-- Dimensi kambing: atribut tetap tiap kambing
CREATE TABLE dim_kambing (
  id_kambing VARCHAR(10) PRIMARY KEY,
  tanggal_lahir DATE NOT NULL,
  jenis_kelamin VARCHAR(10) NOT NULL,
  ras VARCHAR(20) NOT NULL,
  status VARCHAR(10) NOT NULL,
  tanggal_keluar DATE NULL
);

-- Dimensi usia: satu baris per rentang umur (diisi dari dim_usia.csv hasil pra-ETL)
CREATE TABLE dim_usia (
  id_usia INT PRIMARY KEY,
  rentang_umur VARCHAR(30) NOT NULL,
  kategori_usia VARCHAR(10) NOT NULL,
  umur_min_hari INT NOT NULL,
  umur_maks_hari INT NULL
);

-- Dimensi segmen: hasil K-Means (diisi dari dim_segmen.csv). id_segmen 0 = Tidak Diklaster
CREATE TABLE dim_segmen (
  id_segmen INT PRIMARY KEY,
  nama_segmen VARCHAR(40) NOT NULL,
  rasio_adg_centroid DECIMAL(8,4) NULL,
  rasio_bobot_centroid DECIMAL(8,4) NULL,
  jumlah_anggota INT,
  keterangan VARCHAR(120)
);

-- Fakta bobot. Grain: satu penimbangan per kambing per minggu
-- id_usia dan id_segmen: rentang umur dan segmen kambing pada saat penimbangan itu
CREATE TABLE fact_bobot_ternak (
  id_fact_bobot INT AUTO_INCREMENT PRIMARY KEY,
  id_kambing VARCHAR(10) NOT NULL,
  id_waktu INT NOT NULL,
  id_usia INT NOT NULL,
  id_segmen INT NOT NULL,
  minggu_ke INT,
  umur_hari INT,
  berat_badan_kg DECIMAL(6,2) NOT NULL,
  selisih_hari INT NULL,
  selisih_bobot_kg DECIMAL(6,2) NULL,   -- pertambahan bobot sejak penimbangan sebelumnya
  adg_kg_hari DECIMAL(10,6) NULL,       -- = selisih_bobot_kg / selisih_hari; kosong pada penimbangan pertama
  FOREIGN KEY (id_kambing) REFERENCES dim_kambing(id_kambing),
  FOREIGN KEY (id_waktu) REFERENCES dim_waktu(id_waktu),
  FOREIGN KEY (id_usia) REFERENCES dim_usia(id_usia),
  FOREIGN KEY (id_segmen) REFERENCES dim_segmen(id_segmen),
  UNIQUE KEY uq_kambing_waktu (id_kambing, id_waktu)
);

-- Fakta pakan. Grain: satu baris per hari, total seluruh kandang
CREATE TABLE fact_konsumsi_pakan (
  id_fact_pakan INT AUTO_INCREMENT PRIMARY KEY,
  id_waktu INT NOT NULL UNIQUE,
  total_hijauan_kg DECIMAL(8,2),
  total_konsentrat_kg DECIMAL(8,2),
  total_pakan_kg DECIMAL(8,2),
  populasi_aktif INT,
  pakan_per_ekor_kg DECIMAL(8,3),
  FOREIGN KEY (id_waktu) REFERENCES dim_waktu(id_waktu)
);

-- Nilai WCSS dan Silhouette per K untuk tab Validasi K (diisi dari validasi_k.csv)
CREATE TABLE hasil_validasi_k (
  k INT PRIMARY KEY,
  inertia_wcss DOUBLE, silhouette DOUBLE, k_terpilih TINYINT
);

-- Hasil K-Means per kambing per rentang umur (satu baris = satu titik pada peta klaster)
-- rasio_* = perbandingan dengan rata-rata kambing sebaya (1,0 = setara rata-rata)
-- rasio_*_asli = nilai sebelum dipotong pada persentil 1-99; rasio_* = nilai yang dipakai K-Means
CREATE TABLE hasil_klaster (
  id_kambing VARCHAR(10) NOT NULL,
  id_usia INT NOT NULL,
  id_segmen INT NOT NULL,
  n_timbang INT, n_adg INT,
  rata_adg DECIMAL(10,6), rata_bobot DECIMAL(8,3),
  rasio_adg_asli DECIMAL(12,6), rasio_bobot_asli DECIMAL(12,6),
  rasio_adg DECIMAL(12,6), rasio_bobot DECIMAL(12,6),
  PRIMARY KEY (id_kambing, id_usia),
  FOREIGN KEY (id_kambing) REFERENCES dim_kambing(id_kambing),
  FOREIGN KEY (id_usia) REFERENCES dim_usia(id_usia),
  FOREIGN KEY (id_segmen) REFERENCES dim_segmen(id_segmen)
);

-- Akun login dashboard. Tidak dihapus oleh skrip ini, sehingga akun tetap ada saat Data Warehouse dibangun ulang.
-- Isi akun awal dengan:  python buat_pengguna.py init
CREATE TABLE IF NOT EXISTS pengguna (
  id_pengguna INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(30) NOT NULL UNIQUE,
  kode_peran VARCHAR(20) NOT NULL,          -- manajer | supervisor | pakan
  password_hash VARCHAR(255) NOT NULL,      -- PBKDF2-SHA256, bukan kata sandi asli
  aktif TINYINT NOT NULL DEFAULT 1,
  dibuat TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
