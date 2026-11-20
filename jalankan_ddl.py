"""
Membuat database dw_amana_farm beserta tabelnya dengan menjalankan 01_ddl_mysql.sql, tanpa phpMyAdmin.
Dipakai terutama untuk database online (TiDB Cloud).

    python jalankan_ddl.py --db "mysql+pymysql://USER:PASSWORD@HOST:4000/?ssl=true"

Alamat ditulis tanpa nama database, karena database dw_amana_farm dibuat oleh skrip SQL itu sendiri.
Alamat juga boleh diberikan lewat variabel DB_URL.
"""
import argparse
import os
import re

from sqlalchemy import text

from db import buat_koneksi


def perintah_sql(path):
    """Membaca berkas SQL dan memecahnya menjadi daftar perintah (komentar -- dibuang)."""
    isi = open(path, encoding="utf-8").read()
    isi = "\n".join(baris for baris in isi.splitlines() if not baris.strip().startswith("--"))
    isi = re.sub(r"--[^\n]*", "", isi)                # komentar di belakang perintah
    return [p.strip() for p in isi.split(";") if p.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("DB_URL"), help="alamat server (lihat db.py)")
    ap.add_argument("--sql", default="01_ddl_mysql.sql")
    a = ap.parse_args()
    if not a.db:
        ap.error("isi --db atau variabel DB_URL")
    eng = buat_koneksi(a.db)
    daftar = perintah_sql(a.sql)
    with eng.begin() as c:
        for p in daftar:
            c.execute(text(p))
    print(f"Selesai: {len(daftar)} perintah SQL dijalankan.")
    with eng.connect() as c:
        tabel = [r[0] for r in c.execute(text("SHOW TABLES FROM dw_amana_farm"))]
    print(f"Tabel di dw_amana_farm ({len(tabel)}): {', '.join(tabel)}")


if __name__ == "__main__":
    main()
