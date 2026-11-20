"""
Menguji logika login tanpa membuka browser:  python uji_auth.py
Memakai database SQLite sementara, sehingga database utama tidak tersentuh.
"""
import os, sqlite3, tempfile
import auth

f = os.path.join(tempfile.mkdtemp(), "uji.sqlite")
con = sqlite3.connect(f)
auth.buat_tabel(con)
for u, p, s in auth.AKUN_AWAL:
    auth.tambah_atau_ganti(con, u, p, s)

# (username, kata sandi, peran yang diharapkan; None = harus ditolak)
kasus = [
    ("manajer", "Manajer@2026", "manajer"),
    ("supervisor", "Supervisor@2026", "supervisor"),
    ("pakan", "Pakan@2026", "pakan"),
    ("manajer", "salah", None),
    ("manajer", "", None),
    ("pakan", "Manajer@2026", None),
    ("tidak_ada", "x", None),
    ("", "", None),
    ("manajer' OR '1'='1", "x", None),          # percobaan SQL injection harus ditolak
]
gagal = 0
for u, s, harap in kasus:
    r = auth.verifikasi(con, u, s)
    ok = (r["kode_peran"] if r else None) == harap
    gagal += not ok
    print("OK   " if ok else "GAGAL", repr(u), repr(s), "->", r["nama"] if r else None)

# akun nonaktif ditolak
auth._tulis(con, "update pengguna set aktif=0 where username='pakan'")
ok = auth.verifikasi(con, "pakan", "Pakan@2026") is None; gagal += not ok; print("OK   " if ok else "GAGAL", "akun nonaktif ditolak")
auth._tulis(con, "update pengguna set aktif=1 where username='pakan'")
# setelah kata sandi diganti, kata sandi lama ditolak dan yang baru diterima
auth.tambah_atau_ganti(con, "pakan", "pakan", "Baru#123")
ok = auth.verifikasi(con, "pakan", "Pakan@2026") is None and auth.verifikasi(con, "pakan", "Baru#123"); gagal += not ok
print("OK   " if ok else "GAGAL", "ganti kata sandi")
# database hanya menyimpan hash, bukan kata sandi asli
isi = str(auth._baca(con, "select * from pengguna"))
ok = "Manajer@2026" not in isi and "pbkdf2_sha256" in isi; gagal += not ok; print("OK   " if ok else "GAGAL", "DB hanya berisi hash")
# hak akses tab per peran
assert auth.tab_untuk("pakan") == ["Pakan dan FCR"]
assert auth.tab_untuk("supervisor") == ["Bobot dan ADG", "Segmentasi", "Monitoring"]
assert auth.boleh("manajer", "validasi") and not auth.boleh("supervisor", "pakan")
print("SEMUA LULUS" if not gagal else f"{gagal} GAGAL")
