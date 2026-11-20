"""
Koneksi ke database Data Warehouse. Dipakai bersama oleh app.py, impor.py, etl_dw.py, 03_rekonsiliasi.py,
buat_pengguna.py, dan jalankan_ddl.py, sehingga cara terhubung cukup diatur di satu tempat.

Bentuk alamat database (DB_URL):
  MySQL lokal (XAMPP) : mysql+pymysql://root:@localhost/dw_amana_farm
  TiDB Cloud (online) : mysql+pymysql://USER:PASSWORD@HOST:4000/dw_amana_farm?ssl=true
  SQLite (uji)        : sqlite:///dw_uji.sqlite

Akhiran ?ssl=true membuat koneksi terenkripsi (TLS). TiDB Cloud mewajibkannya; MySQL lokal tidak.
"""
import os
import sqlite3
import ssl
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def _pisah_ssl(url):
    """Memisahkan parameter ssl dari alamat. Mengembalikan (alamat tanpa ssl, True bila ssl=true)."""
    bagian = urlsplit(url)
    param = parse_qsl(bagian.query, keep_blank_values=True)
    pakai_ssl = any(k.lower() == "ssl" and v.lower() in ("1", "true", "yes") for k, v in param)
    sisa = [(k, v) for k, v in param if k.lower() != "ssl"]
    return urlunsplit(bagian._replace(query=urlencode(sisa))), pakai_ssl


def konteks_tls():
    """Pengaturan TLS dengan daftar sertifikat dari paket certifi (agar sama di Windows dan server Linux)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:                       # tanpa certifi: pakai sertifikat bawaan sistem operasi
        return ssl.create_default_context()


def buat_koneksi(url, thread_aman=False):
    """Membuka koneksi sesuai alamat.
    sqlite:///... menghasilkan sqlite3.Connection; alamat MySQL menghasilkan SQLAlchemy Engine.
    thread_aman=True dipakai dashboard, karena Streamlit dapat memakai koneksi yang sama dari beberapa thread."""
    if url.startswith("sqlite:///"):
        berkas = url.replace("sqlite:///", "", 1)
        if not os.path.isabs(berkas):                 # path relatif dihitung dari folder program
            berkas = os.path.join(os.path.dirname(os.path.abspath(__file__)), berkas)
        if not os.path.exists(berkas):
            raise FileNotFoundError(f"File database tidak ditemukan: {berkas}")
        return sqlite3.connect(berkas, check_same_thread=not thread_aman)
    from sqlalchemy import create_engine
    url, pakai_ssl = _pisah_ssl(url)
    connect_args = {"ssl": konteks_tls()} if pakai_ssl else {}
    # pool_pre_ping dan pool_recycle: koneksi yang terputus karena lama tidak dipakai dibuka ulang otomatis
    return create_engine(url, connect_args=connect_args, pool_pre_ping=True, pool_recycle=280)
