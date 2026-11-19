"""
Koneksi basis data yang dipakai bersama oleh app.py, etl_dw.py, 03_rekonsiliasi.py, buat_pengguna.py, dan jalankan_ddl.py.

Bentuk alamat (DB_URL):
  Lokal (XAMPP)   : mysql+pymysql://root:@localhost/dw_amana_farm
  Cloud (TLS)     : mysql+pymysql://USER:PASSWORD@HOST:4000/dw_amana_farm?ssl=true
  Tanpa MySQL     : sqlite:///dw_amana_farm.sqlite   (uji, atau hosting di Streamlit Community Cloud)

Tambahan ?ssl=true mengaktifkan koneksi terenkripsi (TLS) dengan sertifikat CA dari paket certifi.
Layanan MySQL di cloud (misalnya TiDB Cloud) mewajibkan TLS; MySQL lokal di XAMPP tidak memerlukannya.
"""
import os
import sqlite3
import ssl
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def _pisah_ssl(url):
    """Mengembalikan (url tanpa parameter ssl, True bila ssl=true)."""
    bagian = urlsplit(url)
    param = parse_qsl(bagian.query, keep_blank_values=True)
    pakai_ssl = any(k.lower() == "ssl" and v.lower() in ("1", "true", "yes") for k, v in param)
    sisa = [(k, v) for k, v in param if k.lower() != "ssl"]
    return urlunsplit(bagian._replace(query=urlencode(sisa))), pakai_ssl


def konteks_tls():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:                       # tanpa certifi: pakai sertifikat bawaan sistem operasi
        return ssl.create_default_context()


def buat_koneksi(url, thread_aman=False):
    """sqlite:/// -> sqlite3.Connection; selain itu -> SQLAlchemy Engine (dengan TLS bila ?ssl=true)."""
    if url.startswith("sqlite:///"):
        berkas = url.replace("sqlite:///", "", 1)
        if not os.path.isabs(berkas):                 # relatif terhadap folder program, bukan folder kerja
            berkas = os.path.join(os.path.dirname(os.path.abspath(__file__)), berkas)
        if not os.path.exists(berkas):
            raise FileNotFoundError(f"File database tidak ditemukan: {berkas}")
        return sqlite3.connect(berkas, check_same_thread=not thread_aman)
    from sqlalchemy import create_engine
    url, pakai_ssl = _pisah_ssl(url)
    connect_args = {"ssl": konteks_tls()} if pakai_ssl else {}
    # pool_pre_ping & pool_recycle: koneksi ke server cloud yang terputus saat idle dibuka ulang otomatis
    return create_engine(url, connect_args=connect_args, pool_pre_ping=True, pool_recycle=280)
