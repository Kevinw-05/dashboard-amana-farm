"""
Mengelola akun login dashboard. Akun disimpan di tabel `pengguna` pada database Data Warehouse.

  python buat_pengguna.py init                     # buat tabel dan 3 akun awal (aman diulang)
  python buat_pengguna.py daftar                   # lihat daftar akun
  python buat_pengguna.py tambah budi supervisor   # tambah akun atau ganti peran (kata sandi ditanyakan)
  python buat_pengguna.py sandi manajer            # ganti kata sandi
  python buat_pengguna.py aktif budi 0             # nonaktifkan akun (1 = aktifkan lagi)

Database: --db "mysql+pymysql://root:@localhost/dw_amana_farm" (bawaan), alamat TiDB Cloud,
atau --db sqlite:///dw_uji.sqlite untuk uji. Alamat juga boleh diberikan lewat variabel DB_URL.
Peran: manajer | supervisor | pakan
"""
import argparse
import getpass
import os
import sqlite3
import sys

import auth


def sambung(url):
    """Koneksi ke database akun. Untuk SQLite, berkas dibuat bila belum ada."""
    if url.startswith("sqlite:///"):
        return sqlite3.connect(url.replace("sqlite:///", "", 1))
    from db import buat_koneksi
    return buat_koneksi(url)


def minta_sandi():
    """Meminta kata sandi dua kali tanpa menampilkannya di layar."""
    a, b = getpass.getpass("Kata sandi: "), getpass.getpass("Ulangi kata sandi: ")
    if not a or a != b:
        sys.exit("Kata sandi kosong atau tidak sama. Dibatalkan.")
    return a


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--db", default=os.environ.get("DB_URL", "mysql+pymysql://root:@localhost/dw_amana_farm"))
    sp = ap.add_subparsers(dest="perintah", required=True)
    sp.add_parser("init"); sp.add_parser("daftar")
    t = sp.add_parser("tambah"); t.add_argument("username"); t.add_argument("peran", choices=list(auth.PERAN))
    g = sp.add_parser("sandi"); g.add_argument("username")
    n = sp.add_parser("aktif"); n.add_argument("username"); n.add_argument("nilai", type=int, choices=[0, 1])
    a = ap.parse_args()

    con = sambung(a.db)
    auth.buat_tabel(con)
    if a.perintah == "init":
        for u, p, s in auth.AKUN_AWAL:
            if auth.ambil_pengguna(con, u):
                print(f"  {u}: sudah ada, dilewati")
            else:
                auth.tambah_atau_ganti(con, u, p, s); print(f"  {u}: ditambahkan")
        print("Selesai. Kata sandi awal tercantum di README; segera ganti dengan: python buat_pengguna.py sandi <username>")
    elif a.perintah == "daftar":
        for r in auth._baca(con, "select username, kode_peran, aktif from pengguna order by id_pengguna"):
            print(f"  {r['username']:15s} {r['kode_peran']:12s} aktif={r['aktif']}")
    elif a.perintah == "tambah":
        print(f"  {a.username}: {auth.tambah_atau_ganti(con, a.username, a.peran, minta_sandi())}")
    elif a.perintah == "sandi":
        u = auth.ambil_pengguna(con, a.username)
        if not u:
            sys.exit("Username tidak ditemukan.")
        print(f"  {a.username}: {auth.tambah_atau_ganti(con, a.username, u['kode_peran'], minta_sandi())}")
    elif a.perintah == "aktif":
        if not auth._tulis(con, "update pengguna set aktif=:v where username=:u", {"v": a.nilai, "u": a.username}):
            sys.exit("Username tidak ditemukan.")
        print(f"  {a.username}: aktif={a.nilai}")


if __name__ == "__main__":
    main()
