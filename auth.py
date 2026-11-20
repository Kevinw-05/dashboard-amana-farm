"""
Login dan hak akses per peran. Akun disimpan di tabel `pengguna` pada database Data Warehouse.

Kata sandi tidak disimpan sebagai teks biasa, melainkan sebagai hash PBKDF2-SHA256.
Akun dikelola dengan buat_pengguna.py (init / daftar / tambah / sandi / aktif).

Peran dan tab yang boleh dibuka:
  manajer    Manajer Operasional   : semua tab, termasuk Import Data
  supervisor Supervisor Peternakan : Bobot dan ADG, Segmentasi, Monitoring
  pakan      Tim Produksi Pakan    : Pakan dan FCR
"""
import hashlib
import hmac
import os
import sqlite3
import sys
import time

# Kode tab -> judul tab di dashboard
NAMA_TAB = {"bobot": "Bobot dan ADG", "segmen": "Segmentasi", "monitor": "Monitoring",
            "pakan": "Pakan dan FCR", "validasi": "Validasi K", "impor": "Import Data"}

# Hak akses: daftar tab yang ditampilkan untuk tiap peran
PERAN = {
    "manajer": {"nama": "Manajer Operasional", "tab": ["bobot", "segmen", "monitor", "pakan", "validasi", "impor"],
                "keterangan": "Akses penuh ke semua tab, termasuk Import Data"},
    "supervisor": {"nama": "Supervisor Peternakan", "tab": ["bobot", "segmen", "monitor"],
                   "keterangan": "Memantau bobot, ADG, segmentasi, dan status kambing"},
    "pakan": {"nama": "Tim Produksi Pakan", "tab": ["pakan"],
              "keterangan": "Memantau konsumsi pakan dan FCR"},
}

# Akun awal yang dibuat oleh "buat_pengguna.py init". Kata sandinya wajib diganti sebelum dipakai.
AKUN_AWAL = [
    ("manajer", "manajer", "Manajer@2026"),
    ("supervisor", "supervisor", "Supervisor@2026"),
    ("pakan", "pakan", "Pakan@2026"),
]

MAKS_GAGAL = 5            # login salah berturut-turut sebelum dikunci sementara
JEDA_KUNCI_DETIK = 60     # lama penguncian

# Struktur tabel akun untuk MySQL/TiDB dan untuk SQLite
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


# ---------------- Hash kata sandi ----------------
def buat_hash(kata_sandi, iterasi=200_000):
    """Hash PBKDF2-SHA256 dengan salt acak; disimpan sebagai algoritma$iterasi$salt$hash."""
    salt = os.urandom(16)
    d = hashlib.pbkdf2_hmac("sha256", kata_sandi.encode("utf-8"), salt, iterasi)
    return f"pbkdf2_sha256${iterasi}${salt.hex()}${d.hex()}"


def cek_kata_sandi(kata_sandi, hash_tersimpan):
    """True bila kata sandi cocok dengan hash yang tersimpan."""
    try:
        algo, iterasi, salt_hex, hash_hex = hash_tersimpan.split("$")
        if algo != "pbkdf2_sha256":
            return False
        d = hashlib.pbkdf2_hmac("sha256", kata_sandi.encode("utf-8"),
                                bytes.fromhex(salt_hex), int(iterasi))
        return hmac.compare_digest(d.hex(), hash_hex)
    except (ValueError, TypeError, AttributeError):
        return False


# Hash pembanding untuk username yang tidak ada, agar lama pemeriksaan sama dan username tidak bisa ditebak
_HASH_PALSU = buat_hash("bukan-sandi-sungguhan")


# ---------------- Akses database (SQLite atau MySQL) ----------------
def _sqlite(con):
    return isinstance(con, sqlite3.Connection)


def _baca(con, sql, params=None):
    """Menjalankan SELECT dan mengembalikan daftar dict."""
    params = params or {}
    if _sqlite(con):
        cur = con.execute(sql, params)
        kol = [c[0] for c in cur.description]
        return [dict(zip(kol, r)) for r in cur.fetchall()]
    from sqlalchemy import text
    with con.connect() as c:
        return [dict(r) for r in c.execute(text(sql), params).mappings().all()]


def _tulis(con, sql, params=None):
    """Menjalankan INSERT/UPDATE/CREATE dan mengembalikan jumlah baris yang berubah."""
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
    """Data satu akun, atau None bila tidak ada."""
    r = _baca(con, "select username, kode_peran, password_hash, aktif from pengguna where username = :u",
              {"u": username.strip()})
    return r[0] if r else None


def verifikasi(con, username, kata_sandi):
    """Memeriksa login. Mengembalikan {username, kode_peran, nama} bila benar; None bila salah atau akun nonaktif."""
    u = ambil_pengguna(con, username or "")
    ok = cek_kata_sandi(kata_sandi or "", u["password_hash"] if u else _HASH_PALSU)
    if not (u and ok and int(u["aktif"]) == 1 and u["kode_peran"] in PERAN):
        return None
    return {"username": u["username"], "kode_peran": u["kode_peran"], "nama": PERAN[u["kode_peran"]]["nama"]}


def tambah_atau_ganti(con, username, kode_peran, kata_sandi):
    """Menambah akun baru, atau mengganti peran dan kata sandi akun yang sudah ada."""
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
    """Judul tab yang boleh dibuka oleh peran ini."""
    return [NAMA_TAB[k] for k in PERAN[kode_peran]["tab"]]


def boleh(kode_peran, kunci_tab):
    """True bila peran ini boleh membuka tab tersebut."""
    return kunci_tab in PERAN.get(kode_peran, {}).get("tab", [])


# ---------------- Tampilan login ----------------
def wajib_login(con):
    """Menampilkan form login bila pengguna belum masuk, lalu menghentikan sisa halaman.
    Mengembalikan data pengguna bila sudah masuk."""
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
    """Nama, peran, dan tombol Keluar di sidebar."""
    import streamlit as st
    with st.sidebar:
        st.markdown(f"**{user['nama']}**")
        st.caption(f"{user['username']} | {PERAN[user['kode_peran']]['keterangan']}")
        if st.button("Keluar", use_container_width=True):
            for k in ("pengguna", "gagal", "terkunci_sampai"):
                st.session_state.pop(k, None)
            st.rerun()


# python auth.py hash : membuat hash kata sandi secara manual (jarang diperlukan)
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "hash":
        import getpass
        p1, p2 = getpass.getpass("Kata sandi baru: "), getpass.getpass("Ulangi: ")
        sys.exit(buat_hash(p1) if p1 and p1 == p2 else "Tidak sama atau kosong.")
    print("Kelola akun dengan: python buat_pengguna.py --help")
