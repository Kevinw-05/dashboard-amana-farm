"""
Import Data dari dashboard: memeriksa berkas Excel, lalu menjalankan pra-ETL K-Means, ETL, dan rekonsiliasi.

Dipakai oleh tab "Import Data" di app.py (hanya Manajer Operasional). Hasilnya sama dengan menjalankan
pra_etl_kmeans.py, etl_dw.py, dan 03_rekonsiliasi.py di PowerShell, tetapi tanpa mengetik perintah.

Pengaman:
  1. Berkas diperiksa lebih dulu (sheet, kolom, tanggal, angka, kecocokan antarsheet) sebelum data lama disentuh.
  2. Isi Data Warehouse yang lama disalin ke memori sebelum dimuat ulang.
  3. Bila proses gagal atau rekonsiliasi tidak seluruhnya lulus, isi lama dipulihkan, sehingga dashboard tidak pernah kosong.
"""
import importlib
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime

import pandas as pd

import etl_dw
import pra_etl_kmeans

# Nama sheet dan kolom wajib pada berkas Excel
SHEET = {"ternak": "Data Ternak 2022-2026", "bb": "Data Pencatatan BB", "pakan": "Data Pakan Harian"}
KOLOM = {
    "ternak": ["id_kambing", "tanggal_lahir", "jenis_kelamin", "ras", "status", "tanggal_keluar"],
    "bb": ["id_kambing", "jenis_kelamin", "ras", "minggu_ke", "tanggal_penimbangan", "berat_badan_kg"],
    "pakan": ["Tanggal", "Total Hijauan (kg)", "Total Konsentrat (kg)", "Total Pakan Harian (kg)"],
}
# Nilai yang diterima pada kolom kategori
NILAI_SAH = {"ras": {"Boer", "Etawa", "PE"}, "jenis_kelamin": {"Jantan", "Betina"}, "status": {"Hidup", "Terjual", "Mati"}}
FOLDER_PRA = "hasil_pra_etl"     # hasil K-Means terbaru disalin ke sini setelah import berhasil
FOLDER_ARSIP = "arsip_impor"     # salinan setiap berkas yang berhasil diimpor


def _contoh(nilai, n=5):
    """Daftar singkat untuk pesan kesalahan, mis. 'KMB00001, KMB00007 (dan 3 lainnya)'."""
    nilai = [str(x) for x in nilai]
    teks = ", ".join(nilai[:n])
    return teks + (f" (dan {len(nilai) - n} lainnya)" if len(nilai) > n else "")


def periksa_excel(berkas):
    """Memeriksa berkas Excel. Mengembalikan (kesalahan, peringatan, ringkasan, data).
    Bila daftar kesalahan tidak kosong, berkas tidak boleh diproses. Nomor baris dalam pesan
    mengikuti nomor baris di Excel (baris 1 = judul kolom)."""
    salah, awas = [], []
    try:
        xls = pd.ExcelFile(berkas)
    except Exception as e:
        return ["Berkas tidak dapat dibaca sebagai Excel. Pastikan berkas disimpan dari Microsoft Excel dengan format .xlsx."], [], {}, {}

    hilang = [s for s in SHEET.values() if s not in xls.sheet_names]
    if hilang:
        return [f"Sheet tidak ditemukan: {', '.join(hilang)}. Nama sheet harus persis: "
                + ", ".join(SHEET.values()) + "."], [], {}, {}

    d = {k: pd.read_excel(xls, s) for k, s in SHEET.items()}
    for k, kol in KOLOM.items():
        kurang = [c for c in kol if c not in d[k].columns]
        if kurang:
            salah.append(f"Sheet '{SHEET[k]}' tidak memiliki kolom: {', '.join(kurang)}.")
    if salah:
        return salah, awas, {}, {}

    t, b, p = d["ternak"], d["bb"], d["pakan"]
    # ---- kolom tanggal dan angka harus terisi dengan benar ----
    for df, kolom, nama in [(t, "tanggal_lahir", SHEET["ternak"]), (b, "tanggal_penimbangan", SHEET["bb"]),
                            (p, "Tanggal", SHEET["pakan"])]:
        df[kolom] = pd.to_datetime(df[kolom], errors="coerce")
        rusak = df[df[kolom].isna()].index
        if len(rusak):
            salah.append(f"Sheet '{nama}', kolom {kolom}: {len(rusak)} baris kosong atau bukan tanggal "
                         f"(baris Excel {_contoh([i + 2 for i in rusak])}).")
    t["tanggal_keluar"] = pd.to_datetime(t["tanggal_keluar"], errors="coerce")
    for df, kolom, nama in [(b, "berat_badan_kg", SHEET["bb"]), (b, "minggu_ke", SHEET["bb"])] + \
                           [(p, c, SHEET["pakan"]) for c in KOLOM["pakan"][1:]]:
        df[kolom] = pd.to_numeric(df[kolom], errors="coerce")
        rusak = df[df[kolom].isna() | (df[kolom] < 0)].index
        if len(rusak):
            salah.append(f"Sheet '{nama}', kolom {kolom}: {len(rusak)} baris kosong, bukan angka, atau negatif "
                         f"(baris Excel {_contoh([i + 2 for i in rusak])}).")
    nol = b[b["berat_badan_kg"] == 0].index
    if len(nol):
        salah.append(f"Sheet '{SHEET['bb']}': {len(nol)} penimbangan berbobot 0 kg (baris Excel {_contoh([i + 2 for i in nol])}).")
    if salah:
        return salah, awas, {}, {}

    # ---- kolom kategori hanya boleh berisi nilai yang dikenal ----
    for kolom, sah in NILAI_SAH.items():
        for df, nama in ([(t, SHEET["ternak"])] + ([(b, SHEET["bb"])] if kolom != "status" else [])):
            lain = sorted(set(df[kolom].dropna().astype(str)) - sah)
            kosong = int(df[kolom].isna().sum())
            if lain or kosong:
                salah.append(f"Sheet '{nama}', kolom {kolom}: nilai harus {', '.join(sorted(sah))}"
                             + (f"; ditemukan {_contoh(lain)}" if lain else "") + (f"; {kosong} baris kosong" if kosong else "") + ".")

    # ---- id_kambing unik dan cocok antarsheet, tidak ada data ganda ----
    if t["id_kambing"].isna().any() or b["id_kambing"].isna().any():
        salah.append("Kolom id_kambing tidak boleh kosong.")
    ganda = t[t["id_kambing"].duplicated()]["id_kambing"]
    if len(ganda):
        salah.append(f"Sheet '{SHEET['ternak']}': id_kambing ganda: {_contoh(ganda.unique())}.")
    asing = sorted(set(b["id_kambing"].dropna()) - set(t["id_kambing"].dropna()))
    if asing:
        salah.append(f"Sheet '{SHEET['bb']}': id_kambing tidak terdaftar di sheet '{SHEET['ternak']}': {_contoh(asing)}.")
    ganda = b[b.duplicated(["id_kambing", "tanggal_penimbangan"], keep=False)]
    if len(ganda):
        salah.append(f"Sheet '{SHEET['bb']}': {len(ganda)} baris penimbangan ganda (kambing dan tanggal sama), "
                     f"misalnya {_contoh(ganda['id_kambing'].unique())}.")
    ganda = p[p["Tanggal"].duplicated()]["Tanggal"]
    if len(ganda):
        salah.append(f"Sheet '{SHEET['pakan']}': tanggal ganda: {_contoh(ganda.dt.strftime('%Y-%m-%d').unique())}.")
    tanpa = t[(t["status"] != "Hidup") & t["tanggal_keluar"].isna()]["id_kambing"]
    if len(tanpa):
        salah.append(f"Kambing berstatus Terjual/Mati harus memiliki tanggal_keluar: {_contoh(tanpa)}.")
    m = b.merge(t[["id_kambing", "tanggal_lahir"]], on="id_kambing", how="inner")
    sebelum = m[m["tanggal_penimbangan"] < m["tanggal_lahir"]]["id_kambing"].unique()
    if len(sebelum):
        salah.append(f"Ada penimbangan bertanggal sebelum tanggal lahir kambing: {_contoh(sebelum)}.")
    if salah:
        return salah, awas, {}, {}

    # ---- setiap hari pakan harus ada kambing aktif, karena menjadi pembagi pakan per ekor ----
    akhir_catat = max(p["Tanggal"].max(), b["tanggal_penimbangan"].max())
    mulai, akhir = etl_dw.periode_aktif(t, p["Tanggal"].min(), akhir_catat)
    kosong = [d for d in p["Tanggal"] if not ((mulai <= d) & (d <= akhir)).any()]
    if kosong:
        salah.append(f"Ada {len(kosong)} hari pakan tanpa kambing aktif, misalnya "
                     f"{_contoh([d.strftime('%Y-%m-%d') for d in kosong])}. Periksa tanggal lahir dan tanggal keluar.")
        return salah, awas, {}, {}

    # ---- peringatan: berkas tetap boleh diproses ----
    selisih = (p[KOLOM["pakan"][1]] + p[KOLOM["pakan"][2]] - p[KOLOM["pakan"][3]]).abs()
    if (selisih > 0.05).any():
        awas.append(f"{int((selisih > 0.05).sum())} hari pakan: Total Pakan Harian tidak sama dengan Hijauan + Konsentrat. "
                    "Yang dipakai adalah kolom Total Pakan Harian.")
    tanpa_timbang = sorted(set(t["id_kambing"]) - set(b["id_kambing"]))
    if tanpa_timbang:
        awas.append(f"{len(tanpa_timbang)} kambing belum memiliki data penimbangan: {_contoh(tanpa_timbang)}.")

    ringkas = {"kambing": len(t), "hidup": int((t["status"] == "Hidup").sum()), "penimbangan": len(b),
               "hari_pakan": len(p), "awal": min(p["Tanggal"].min(), b["tanggal_penimbangan"].min()), "akhir": akhir_catat}
    return salah, awas, ringkas, d


def ringkasan_dw(con):
    """Ringkasan isi Data Warehouse saat ini, untuk dibandingkan dengan berkas baru."""
    try:
        q = lambda s: pd.read_sql(s, con).iloc[0, 0]
        return {"kambing": int(q("select count(*) from dim_kambing")),
                "hidup": int(q("select count(*) from dim_kambing where status = 'Hidup'")),
                "penimbangan": int(q("select count(*) from fact_bobot_ternak")),
                "hari_pakan": int(q("select count(*) from fact_konsumsi_pakan")),
                "akhir": pd.to_datetime(q("select max(tanggal) from dim_waktu"))}
    except Exception:
        return {}


def _salin_isi(con):
    """Salinan isi tabel Data Warehouse saat ini (untuk dipulihkan bila import gagal)."""
    salinan = {}
    for n in etl_dw.URUTAN_MUAT:
        try:
            salinan[n] = pd.read_sql(f"select * from {n}", con)
        except Exception:
            pass                                   # tabel belum ada (database baru)
    return salinan


def _pulihkan(salinan, con):
    """Mengembalikan isi tabel Data Warehouse dari salinan yang dibuat _salin_isi()."""
    if not salinan:
        return
    if isinstance(con, sqlite3.Connection):
        for n, d in salinan.items():
            d.to_sql(n, con, index=False, if_exists="replace")
        con.commit()
    else:
        from sqlalchemy import text
        with con.begin() as c:
            c.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for n in reversed(etl_dw.URUTAN_MUAT):
                c.execute(text(f"TRUNCATE TABLE {n}"))
            c.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        for n in etl_dw.URUTAN_MUAT:
            if n in salinan and len(salinan[n]):
                salinan[n].to_sql(n, con, if_exists="append", index=False, chunksize=1000)


def proses_impor(berkas_excel, con, folder_program=".", nama_asli="data.xlsx", k=None, lapor=lambda teks, nilai: None):
    """Menjalankan pra-ETL K-Means, ETL, dan rekonsiliasi untuk berkas yang sudah lolos periksa_excel().
    k=None: K dipilih dengan aturan Elbow + Silhouette (sama seperti pra_etl_kmeans.py); angka: K ditetapkan sendiri.
    lapor(teks, nilai) dipanggil di setiap tahap untuk mengisi progress bar.
    Mengembalikan dict hasil. Bila gagal, isi Data Warehouse lama dipulihkan."""
    rekon = importlib.import_module("03_rekonsiliasi")    # nama berkas diawali angka, jadi diimpor dengan importlib
    sementara = tempfile.mkdtemp(prefix="impor_")
    excel = os.path.join(sementara, "data.xlsx")
    with open(excel, "wb") as f:
        f.write(berkas_excel if isinstance(berkas_excel, (bytes, bytearray)) else berkas_excel.read())
    pra = os.path.join(sementara, "pra")
    salinan, dimuat = {}, False      # dimuat = True setelah tabel Data Warehouse mulai ditimpa
    try:
        lapor("1/4 Menghitung fitur dan K-Means (pra-ETL)...", 0.1)
        k = pra_etl_kmeans.jalankan(excel, pra, k=k, cetak=False)
        lapor("2/4 Menyiapkan data (ETL: extract dan transform)...", 0.35)
        hasil = etl_dw.transformasi(excel, pra)
        lapor("3/4 Memuat ke Data Warehouse...", 0.55)
        salinan = _salin_isi(con)
        etl_dw.muat(hasil, con)
        dimuat = True
        lapor("4/4 Mencocokkan isi Data Warehouse dengan Excel (rekonsiliasi)...", 0.8)
        cek = rekon.periksa(excel, con, pra, cetak=False)
        lulus = sum(1 for c in cek if c[1] == "LULUS")
        if lulus != len(cek):
            _pulihkan(salinan, con)
            return {"berhasil": False, "pesan": f"Rekonsiliasi {lulus}/{len(cek)} lulus, sehingga data lama dipulihkan.",
                    "rekonsiliasi": cek, "k": k}
        # berhasil: perbarui folder hasil_pra_etl dan simpan salinan berkas di arsip_impor
        tujuan = os.path.join(folder_program, FOLDER_PRA)
        shutil.rmtree(tujuan, ignore_errors=True)
        shutil.copytree(pra, tujuan)
        os.makedirs(os.path.join(folder_program, FOLDER_ARSIP), exist_ok=True)
        dasar = os.path.splitext(os.path.basename(nama_asli))[0]
        arsip = os.path.join(FOLDER_ARSIP, f"{datetime.now():%Y%m%d_%H%M%S}_{dasar}.xlsx")
        shutil.copy(excel, os.path.join(folder_program, arsip))
        lapor("Selesai.", 1.0)
        return {"berhasil": True, "pesan": "Import berhasil.", "rekonsiliasi": cek, "k": k, "arsip": arsip,
                "jumlah": {n: len(d) for n, d in hasil.items()}}
    except Exception as e:
        if dimuat or salinan:
            try:
                _pulihkan(salinan, con)
            except Exception as e2:
                return {"berhasil": False, "pesan": f"Import gagal ({e}) dan pemulihan juga gagal ({e2}). "
                        "Jalankan ulang import atau ETL dari PowerShell.", "rekonsiliasi": [], "k": None}
        return {"berhasil": False, "pesan": f"Import gagal: {e}. Data lama tetap dipakai.", "rekonsiliasi": [], "k": None}
    finally:
        shutil.rmtree(sementara, ignore_errors=True)
