"""Kumpulan query dashboard (SQL standar: jalan di MySQL dan SQLite)."""
import pandas as pd

def _q(con, sql, params=None):
    return pd.read_sql(sql, con, params=params)

def kpi(con):
    """rata_bobot_terakhir = rata-rata bobot penimbangan TERAKHIR tiap kambing yang masih hidup."""
    return _q(con, """
      select (select count(*) from dim_kambing) as total_kambing,
             (select count(*) from dim_kambing where status='Hidup') as hidup,
             (select count(*) from dim_kambing where status='Mati') as mati,
             (select count(*) from dim_kambing where status='Terjual') as terjual,
             (select avg(adg_kg_hari) from fact_bobot_ternak) as rata_adg,
             (select avg(f.berat_badan_kg) from fact_bobot_ternak f
                join (select id_kambing, max(id_waktu) as mw from fact_bobot_ternak group by id_kambing) m
                  on m.id_kambing=f.id_kambing and m.mw=f.id_waktu
                join dim_kambing k on k.id_kambing=f.id_kambing where k.status='Hidup') as rata_bobot_terakhir,
             (select pakan_per_ekor_kg from fact_konsumsi_pakan
                where id_waktu=(select max(id_waktu) from fact_konsumsi_pakan)) as pakan_per_ekor_terakhir""").iloc[0]

def tren_bobot(con, ras=None, kategori=None):
    sql = """select w.tahun, w.bulan, avg(f.berat_badan_kg) as rata_bobot, avg(f.adg_kg_hari) as rata_adg
             from fact_bobot_ternak f join dim_waktu w on w.id_waktu=f.id_waktu
             join dim_kambing k on k.id_kambing=f.id_kambing
             join dim_usia u on u.id_usia=f.id_usia
             where (:ras is null or k.ras=:ras) and (:kat is null or u.kategori_usia=:kat)
             group by w.tahun, w.bulan order by w.tahun, w.bulan"""
    return _q_named(con, sql, {"ras": ras, "kat": kategori})

def _q_named(con, sql, params):
    # SQLAlchemy engine butuh text(); sqlite3 memakai :nama langsung
    try:
        from sqlalchemy import text
        from sqlalchemy.engine import Engine
        if isinstance(con, Engine):
            return pd.read_sql(text(sql), con, params=params)
    except ImportError:
        pass
    return pd.read_sql(sql, con, params=params)

def adg_per_ras_usia(con):
    return _q(con, """select k.ras, u.kategori_usia, avg(f.adg_kg_hari) as rata_adg, count(*) as n
             from fact_bobot_ternak f join dim_kambing k on k.id_kambing=f.id_kambing
             join dim_usia u on u.id_usia=f.id_usia where f.adg_kg_hari is not null
             group by k.ras, u.kategori_usia order by k.ras, u.kategori_usia""")

def segmentasi(con):
    """Satu baris per kambing per rentang umur (unit klasterisasi)."""
    return _q(con, """select f.id_kambing, k.ras, k.jenis_kelamin, k.status, u.rentang_umur, s.nama_segmen as segmen,
             s.rasio_adg_centroid, s.rasio_bobot_centroid, max(w.tanggal) as tgl_terakhir,
             count(*) as n_timbang, avg(f.adg_kg_hari) as rata_adg, avg(f.berat_badan_kg) as rata_bobot
             from fact_bobot_ternak f join dim_kambing k on k.id_kambing=f.id_kambing
             join dim_waktu w on w.id_waktu=f.id_waktu
             join dim_usia u on u.id_usia=f.id_usia join dim_segmen s on s.id_segmen=f.id_segmen
             group by f.id_kambing, k.ras, k.jenis_kelamin, k.status, u.rentang_umur, u.id_usia, s.nama_segmen,
                      s.rasio_adg_centroid, s.rasio_bobot_centroid order by f.id_kambing, u.id_usia""")

def komposisi_segmen(con):
    return _q(con, "select nama_segmen as segmen, jumlah_anggota, rasio_adg_centroid, rasio_bobot_centroid, keterangan from dim_segmen order by id_segmen")

def pakan_fcr_bulanan(con):
    """FCR populasi = total pakan / total pertambahan bobot (sum adg*selisih_hari). Hanya valid tingkat populasi."""
    return _q(con, """select p.tahun, p.bulan, p.pakan, g.gain,
             case when g.gain > 0 then p.pakan / g.gain end as fcr
             from (select w.tahun, w.bulan, sum(c.total_pakan_kg) as pakan
                   from fact_konsumsi_pakan c join dim_waktu w on w.id_waktu=c.id_waktu group by w.tahun, w.bulan) p
             join (select w.tahun, w.bulan, sum(f.selisih_bobot_kg) as gain
                   from fact_bobot_ternak f join dim_waktu w on w.id_waktu=f.id_waktu
                   where f.adg_kg_hari is not null group by w.tahun, w.bulan) g
             on g.tahun=p.tahun and g.bulan=p.bulan order by p.tahun, p.bulan""")

def pakan_harian(con):
    return _q(con, """select w.tanggal, c.total_pakan_kg, c.populasi_aktif, c.pakan_per_ekor_kg
             from fact_konsumsi_pakan c join dim_waktu w on w.id_waktu=c.id_waktu order by w.tanggal""")

def validasi_k(con):
    return _q(con, "select k, inertia_wcss, silhouette, k_terpilih from hasil_validasi_k order by k")

def titik_klaster(con):
    """Satu baris per kambing per rentang umur pada ruang K-Means (rasio terhadap peer group)."""
    return _q(con, """select h.id_kambing, k.ras, k.jenis_kelamin, k.status, u.rentang_umur, s.nama_segmen as segmen,
             h.rasio_adg, h.rasio_bobot, h.rata_adg, h.rata_bobot, h.n_timbang
             from hasil_klaster h join dim_kambing k on k.id_kambing=h.id_kambing
             join dim_usia u on u.id_usia=h.id_usia join dim_segmen s on s.id_segmen=h.id_segmen""")

# ---------------- Monitoring ----------------
def timbang_terakhir(con):
    """Penimbangan terakhir tiap kambing: bobot, umur, tanggal."""
    return _q(con, """select f.id_kambing, w.tanggal as tgl_timbang_terakhir, f.umur_hari, f.berat_badan_kg as bobot_terakhir
             from fact_bobot_ternak f
             join (select id_kambing, max(id_waktu) as mw from fact_bobot_ternak group by id_kambing) m
               on m.id_kambing=f.id_kambing and m.mw=f.id_waktu
             join dim_waktu w on w.id_waktu=f.id_waktu""")

def adg_bulanan_kategori(con):
    """Rata-rata ADG per bulan per kategori usia (bahan bagan kendali)."""
    return _q(con, """select u.kategori_usia, w.tahun, w.bulan, avg(f.adg_kg_hari) as nilai,
             count(distinct f.id_kambing) as n_ekor
             from fact_bobot_ternak f join dim_waktu w on w.id_waktu=f.id_waktu
             join dim_usia u on u.id_usia=f.id_usia where f.adg_kg_hari is not null
             group by u.kategori_usia, w.tahun, w.bulan order by u.kategori_usia, w.tahun, w.bulan""")

def pakan_per_ekor_bulanan(con):
    """Rata-rata pakan per ekor per hari, dirata-ratakan per bulan (bahan bagan kendali)."""
    return _q(con, """select w.tahun, w.bulan, avg(c.pakan_per_ekor_kg) as nilai, avg(c.populasi_aktif) as n_ekor
             from fact_konsumsi_pakan c join dim_waktu w on w.id_waktu=c.id_waktu
             group by w.tahun, w.bulan order by w.tahun, w.bulan""")
