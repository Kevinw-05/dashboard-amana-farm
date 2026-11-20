"""
auth.py - Login dan hak akses per peran; akun pengguna disimpan di tabel `pengguna` (MySQL).

Kata sandi TIDAK disimpan sebagai teks, melainkan hash PBKDF2-SHA256 (bawaan Python).
Kelola akun dengan buat_pengguna.py (init / daftar / tambah / sandi / aktif).

Peran (kode_peran di tabel -> hak akses tab):
  manajer    Manajer Operasional   : semua tab
  supervisor Supervisor Peternakan : Bobot dan ADG, Segmentasi
  pakan      Tim Produksi Pakan    : Pakan dan FCR
"""
import hashlib
import hmac
import os
import sqlite3
import sys
import time

NAMA_TAB = {"bobot": "Bobot dan ADG", "segmen": "Segmentasi", "monitor": "Monitoring",
            "pakan": "Pakan dan FCR", "validasi": "Validasi K", "impor": "Import Data"}

PERAN = {
    "manajer": {"nama": "Manajer Operasional", "tab": ["bobot", "segmen", "monitor", "pakan", "validasi", "impor"],
                "keterangan": "Akses penuh ke semua tab, termasuk Import Data"},
    "supervisor": {"nama": "Supervisor Peternakan", "tab": ["bobot", "segmen", "monitor"],
                   "keterangan": "Memantau bobot, ADG, segmentasi, dan status kambing"},
    "pakan": {"nama": "Tim Produksi Pakan", "tab": ["pakan"],
              "keterangan": "Memantau konsumsi pakan dan FCR"},
}

# Akun awal (dipakai buat_pengguna.py init). HANYA untuk demo: ganti kata sandinya.
AKUN_AWAL = [
    ("manajer", "manajer", "Manajer@2026"),
    ("supervisor", "supervisor", "Supervisor@2026"),
    ("pakan", "pakan", "Pakan@2026"),
]

MAKS_GAGAL = 5
JEDA_KUNCI_DETIK = 60

DDL_MYSQL = """CREATE TABLE IF NOT EXISTS pengguna (
  id_pengguna INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(30) NOT NULL UNIQUE,
  kode_peran VARCHAR(20) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  aktif TINYINT NOT NULL DEFAULT 1,
  dibuat TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)"""
DDL_SQLITE = """CREATE TABLE IF NOT EXISTS pengguna (
  id_pengguna INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  kode_peran TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  aktif INTEGER NOT NULL DEFAULT 1,
  dibuat TEXT DEFAULT CURRENT_TIMESTAMP
)"""


# ------------------------------------------------------------------ hash sandi
def buat_hash(kata_sandi, iterasi=200_000):
    salt = os.urandom(16)
    d = hashlib.pbkdf2_hmac("sha256", kata_sandi.encode("utf-8"), salt, iterasi)
    return f"pbkdf2_sha256${iterasi}${salt.hex()}${d.hex()}"


def cek_kata_sandi(kata_sandi, hash_tersimpan):
    try:
        algo, iterasi, salt_hex, hash_hex = hash_tersimpan.split("$")
        if algo != "pbkdf2_sha256":
            return False
        d = hashlib.pbkdf2_hmac("sha256", kata_sandi.encode("utf-8"),
                                bytes.fromhex(salt_hex), int(iterasi))
        return hmac.compare_digest(d.hex(), hash_hex)
    except (ValueError, TypeError, AttributeError):
        return False


_HASH_PALSU = buat_hash("bukan-sandi-sungguhan")   # supaya waktu cek sama walau username tidak ada


# ------------------------------------------------------------------ akses DB
def _sqlite(con):
    return isinstance(con, sqlite3.Connection)


def _baca(con, sql, params=None):
    """Mengembalikan list dict. Mendukung koneksi sqlite3 dan SQLAlchemy Engine."""
    params = params or {}
    if _sqlite(con):
        cur = con.execute(sql, params)
        kol = [c[0] for c in cur.description]
        return [dict(zip(kol, r)) for r in cur.fetchall()]
    from sqlalchemy import text
    with con.connect() as c:
        return [dict(r) for r in c.execute(text(sql), params).mappings().all()]


def _tulis(con, sql, params=None):
    params = params or {}
    if _sqlite(con):
        n = con.execute(sql, params).rowcount
        con.commit()
        return n
    from sqlalchemy import text
    with con.begin() as c:
        return c.execute(text(sql), params).rowcount


def buat_tabel(con):
    _tulis(con, DDL_SQLITE if _sqlite(con) else DDL_MYSQL)


def ambil_pengguna(con, username):
    r = _baca(con, "select username, kode_peran, password_hash, aktif from pengguna where username = :u",
              {"u": username.strip()})
    return r[0] if r else None


def verifikasi(con, username, kata_sandi):
    """Mengembalikan dict {username, kode_peran, nama} bila benar; None bila salah/nonaktif."""
    u = ambil_pengguna(con, username or "")
    ok = cek_kata_sandi(kata_sandi or "", u["password_hash"] if u else _HASH_PALSU)
    if not (u and ok and int(u["aktif"]) == 1 and u["kode_peran"] in PERAN):
        return None
    return {"username": u["username"], "kode_peran": u["kode_peran"], "nama": PERAN[u["kode_peran"]]["nama"]}


def tambah_atau_ganti(con, username, kode_peran, kata_sandi):
    if kode_peran not in PERAN:
        raise ValueError(f"kode_peran harus salah satu dari {list(PERAN)}")
    h = buat_hash(kata_sandi)
    if ambil_pengguna(con, username):
        _tulis(con, "update pengguna set kode_peran=:p, password_hash=:h, aktif=1 where username=:u",
               {"p": kode_peran, "h": h, "u": username})
        return "diperbarui"
    _tulis(con, "insert into pengguna (username, kode_peran, password_hash, aktif) values (:u,:p,:h,1)",
           {"u": username, "p": kode_peran, "h": h})
    return "ditambahkan"


def tab_untuk(kode_peran):
    return [NAMA_TAB[k] for k in PERAN[kode_peran]["tab"]]


def boleh(kode_peran, kunci_tab):
    return kunci_tab in PERAN.get(kode_peran, {}).get("tab", [])


# --------------------------------------------------------------------- tampilan
def wajib_login(con):
    """Panggil di app.py sesudah koneksi dibuat. Menampilkan login bila belum masuk
    dan menghentikan sisa halaman. Mengembalikan dict pengguna bila sudah masuk."""
    import streamlit as st

    p = st.session_state.get("pengguna")
    if p and p.get("kode_peran") in PERAN:
        return p

    kiri, tengah, kanan = st.columns([1, 1.4, 1])
    with tengah:
        st.markdown("## Dashboard Monitoring Bobot Ternak")
        st.caption("PT. Amana Albaroqh Farm")

        sisa = st.session_state.get("terkunci_sampai", 0) - time.time()
        if sisa > 0:
            st.error(f"Terlalu banyak percobaan salah. Coba lagi dalam {int(sisa) + 1} detik.")
            st.stop()

        with st.form("form_login"):
            username = st.text_input("Username")
            sandi = st.text_input("Kata sandi", type="password")
            kirim = st.form_submit_button("Masuk", use_container_width=True)

        if kirim:
            try:
                user = verifikasi(con, username, sandi)
            except Exception as e:
                st.error("Tabel pengguna belum siap atau database tidak terjangkau. "
                         "Jalankan: python buat_pengguna.py init  (lihat README). "
                         f"Detail: {e}")
                st.stop()
            if user:
                st.session_state["pengguna"] = user
                st.session_state["gagal"] = 0
                st.rerun()
            else:
                n = st.session_state.get("gagal", 0) + 1
                st.session_state["gagal"] = n
                if n >= MAKS_GAGAL:
                    st.session_state["terkunci_sampai"] = time.time() + JEDA_KUNCI_DETIK
                    st.session_state["gagal"] = 0
                    st.error(f"Terlalu banyak percobaan salah. Terkunci {JEDA_KUNCI_DETIK} detik.")
                else:
                    st.error(f"Username atau kata sandi salah. Sisa percobaan: {MAKS_GAGAL - n}.")
    st.stop()


def kotak_pengguna(user):
    import streamlit as st
    with st.sidebar:
        st.markdown(f"**{user['nama']}**")
        st.caption(f"{user['username']} | {PERAN[user['kode_peran']]['keterangan']}")
        if st.button("Keluar", use_container_width=True):
            for k in ("pengguna", "gagal", "terkunci_sampai"):
                st.session_state.pop(k, None)
            st.rerun()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "hash":
        import getpass
        p1, p2 = getpass.getpass("Kata sandi baru: "), getpass.getpass("Ulangi: ")
        sys.exit(buat_hash(p1) if p1 and p1 == p2 else "Tidak sama atau kosong.")
    print("Kelola akun dengan: python buat_pengguna.py --help")
