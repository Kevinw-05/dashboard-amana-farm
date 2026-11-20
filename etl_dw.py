"""
ETL Data Warehouse: Extract dari Excel dan hasil pra-ETL, Transform menjadi tabel dimensi dan fakta,
lalu Load ke MySQL (atau SQLite untuk uji).

Urutan lengkap: pra_etl_kmeans.py -> 01_ddl_mysql.sql -> etl_dw.py -> 03_rekonsiliasi.py

    python etl_dw.py --excel Data_Ternak_2022-2026.xlsx --pra hasil_pra_etl
    python etl_dw.py --excel Data_Ternak_2022-2026.xlsx --pra hasil_pra_etl --mysql "ALAMAT_DATABASE"
    python etl_dw.py --excel Data_Ternak_2022-2026.xlsx --pra hasil_pra_etl --sqlite dw_uji.sqlite

Tanpa --mysql maupun --sqlite, data dimuat ke MySQL lokal: mysql+pymysql://root:@localhost/dw_amana_farm
"""
import argparse, os, sqlite3
import pandas as pd
from pra_etl_kmeans import kelompok_umur   # rentang umur harus sama persis dengan tahap pra-ETL

# Urutan pengisian tabel: dimensi lebih dulu, baru fakta (mengikuti foreign key)
URUTAN_MUAT = ["dim_waktu", "dim_kambing", "dim_usia", "dim_segmen", "fact_bobot_ternak", "fact_konsumsi_pakan",
               "hasil_klaster", "hasil_validasi_k"]


def periode_aktif(ternak, awal_catat, akhir_catat):
    """Masa aktif tiap kambing untuk menghitung populasi aktif harian.
    Mulai  = tanggal lahir, atau tanggal pencatatan pertama bagi kambing yang lahir sebelum pencatatan dimulai.
    Akhir  = tanggal keluar (terjual/mati), atau tanggal data terakhir bagi kambing yang masih hidup.
    Kedua batas diambil dari data, sehingga tetap benar ketika Excel diperbarui."""
    mulai = ternak.tanggal_lahir.where(ternak.tanggal_lahir >= awal_catat, awal_catat)
    akhir = ternak.tanggal_keluar.where(ternak.status != "Hidup", akhir_catat)
    return mulai, akhir


def transformasi(excel, pra, rentang="halus"):
    """Extract dan Transform. Mengembalikan {nama_tabel: DataFrame} untuk semua tabel di URUTAN_MUAT."""
    ternak = pd.read_excel(excel, "Data Ternak 2022-2026", parse_dates=["tanggal_lahir", "tanggal_keluar"])
    bb = pd.read_excel(excel, "Data Pencatatan BB", parse_dates=["tanggal_penimbangan"])
    pakan = pd.read_excel(excel, "Data Pakan Harian", parse_dates=["Tanggal"])
    usia = pd.read_csv(f"{pra}/dim_usia.csv")
    seg = pd.read_csv(f"{pra}/dim_segmen.csv")
    lab = pd.read_csv(f"{pra}/label_klaster.csv")
    val = pd.read_csv(f"{pra}/validasi_k.csv")

    # dim_waktu: satu baris per tanggal yang muncul di data penimbangan atau data pakan
    t = pd.DataFrame({"tanggal": sorted(pd.concat([bb.tanggal_penimbangan, pakan.Tanggal]).drop_duplicates())})
    t.insert(0, "id_waktu", range(1, len(t) + 1))
    t["hari"] = t.tanggal.dt.day; t["minggu_ke_tahun"] = t.tanggal.dt.isocalendar().week.astype(int)
    t["bulan"] = t.tanggal.dt.month; t["nama_bulan"] = t.tanggal.dt.month_name()
    t["kuartal"] = t.tanggal.dt.quarter; t["tahun"] = t.tanggal.dt.year

    # dim_kambing: atribut tetap tiap kambing
    dk = ternak[["id_kambing", "tanggal_lahir", "jenis_kelamin", "ras", "status", "tanggal_keluar"]]

    # fact_bobot_ternak: satu baris per penimbangan, dengan ADG, umur, rentang umur, dan segmen
    f = bb.sort_values(["id_kambing", "tanggal_penimbangan"]).merge(
        ternak[["id_kambing", "tanggal_lahir"]], on="id_kambing")
    f["selisih_hari"] = f.groupby("id_kambing").tanggal_penimbangan.diff().dt.days
    f["selisih_bobot_kg"] = f.groupby("id_kambing").berat_badan_kg.diff().round(2)
    f["adg_kg_hari"] = f.selisih_bobot_kg / f.selisih_hari
    f["umur_hari"] = (f.tanggal_penimbangan - f.tanggal_lahir).dt.days
    f["rentang_umur"] = kelompok_umur(f.umur_hari, rentang).astype(str)
    f = f.merge(usia[["id_usia", "rentang_umur"]], on="rentang_umur")
    f = f.merge(t[["id_waktu", "tanggal"]], left_on="tanggal_penimbangan", right_on="tanggal")
    lab2 = lab[["id_kambing", "kelompok_umur", "segmen"]].rename(columns={"kelompok_umur": "rentang_umur"})
    f = f.merge(lab2, on=["id_kambing", "rentang_umur"], how="left").merge(
        seg[["id_segmen", "nama_segmen"]], left_on="segmen", right_on="nama_segmen", how="left")
    f["id_segmen"] = f.id_segmen.fillna(0).astype(int)
    fb = f[["id_kambing", "id_waktu", "id_usia", "id_segmen", "minggu_ke", "umur_hari",
            "berat_badan_kg", "selisih_hari", "selisih_bobot_kg", "adg_kg_hari"]]

    # hasil_klaster: satu baris per kambing per rentang umur yang ikut K-Means (bahan peta klaster)
    hk = lab.merge(usia[["id_usia", "rentang_umur"]], left_on="kelompok_umur", right_on="rentang_umur") \
            .merge(seg[["id_segmen", "nama_segmen"]], left_on="segmen", right_on="nama_segmen")
    hk = hk[["id_kambing", "id_usia", "id_segmen", "n_timbang", "n_adg", "rata_adg", "rata_bobot",
             "rasio_adg_asli", "rasio_bobot_asli", "rasio_adg", "rasio_bobot"]]
    assert len(hk) == len(lab), "label klaster tidak cocok dengan dim_usia / dim_segmen"

    # fact_konsumsi_pakan: satu baris per hari; pakan per ekor = total pakan / populasi aktif
    mulai, akhir = periode_aktif(ternak, pakan.Tanggal.min(), max(pakan.Tanggal.max(), bb.tanggal_penimbangan.max()))
    p = pakan.merge(t[["id_waktu", "tanggal"]], left_on="Tanggal", right_on="tanggal")
    p["populasi_aktif"] = p.Tanggal.map(lambda d: int(((mulai <= d) & (d <= akhir)).sum()))
    p = p.rename(columns={"Total Hijauan (kg)": "total_hijauan_kg", "Total Konsentrat (kg)": "total_konsentrat_kg",
                          "Total Pakan Harian (kg)": "total_pakan_kg"})
    p["pakan_per_ekor_kg"] = (p.total_pakan_kg / p.populasi_aktif).round(3)
    fp = p[["id_waktu", "total_hijauan_kg", "total_konsentrat_kg", "total_pakan_kg", "populasi_aktif", "pakan_per_ekor_kg"]]

    return {"dim_waktu": t, "dim_kambing": dk, "dim_usia": usia, "dim_segmen": seg, "fact_bobot_ternak": fb,
            "fact_konsumsi_pakan": fp, "hasil_klaster": hk, "hasil_validasi_k": val.rename(columns={"K": "k"})}


def muat_sqlite(hasil, con):
    """Load ke SQLite. Tabel Data Warehouse dibuat ulang; tabel pengguna (akun login) tidak disentuh."""
    for n in URUTAN_MUAT:
        d = hasil[n].copy()
        for c in d.columns:
            if pd.api.types.is_datetime64_any_dtype(d[c]):
                d[c] = d[c].dt.strftime("%Y-%m-%d")
        d.to_sql(n, con, index=False, if_exists="replace")
    con.commit()


def muat_mysql(hasil, eng):
    """Load ke MySQL/TiDB: kosongkan tabel (TRUNCATE), lalu isi ulang. Tabel pengguna tidak disentuh."""
    from sqlalchemy import text
    with eng.begin() as c:
        c.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for n in reversed(URUTAN_MUAT):
            c.execute(text(f"TRUNCATE TABLE {n}"))
        c.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    for n in URUTAN_MUAT:
        hasil[n].to_sql(n, eng, if_exists="append", index=False, chunksize=1000)


def muat(hasil, con):
    """Load ke koneksi dari db.buat_koneksi(), baik SQLite maupun MySQL/TiDB."""
    if isinstance(con, sqlite3.Connection):
        muat_sqlite(hasil, con)
    else:
        muat_mysql(hasil, con)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", required=True); ap.add_argument("--pra", required=True)
    ap.add_argument("--sqlite", help="muat ke berkas SQLite (uji tanpa MySQL)")
    ap.add_argument("--mysql", default=None, help="alamat MySQL/TiDB; bawaan mysql+pymysql://root:@localhost/dw_amana_farm"); ap.add_argument("--rentang", default="halus")
    a = ap.parse_args()
    if not a.sqlite and not a.mysql:
        a.mysql = "mysql+pymysql://root:@localhost/dw_amana_farm"
    hasil = transformasi(a.excel, a.pra, a.rentang)
    if a.sqlite:
        con = sqlite3.connect(a.sqlite)
        muat_sqlite(hasil, con)
        for n in URUTAN_MUAT[:-1]:
            print("sqlite", n, con.execute(f"select count(*) from {n}").fetchone()[0])
    if a.mysql:
        from db import buat_koneksi
        muat_mysql(hasil, buat_koneksi(a.mysql))          # alamat TiDB Cloud diakhiri ?ssl=true
        for n in URUTAN_MUAT:
            print("mysql", n, len(hasil[n]))
        print("MySQL terisi.")


if __name__ == "__main__":
    main()
