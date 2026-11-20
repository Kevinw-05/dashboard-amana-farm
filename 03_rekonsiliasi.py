"""
Rekonsiliasi: mencocokkan isi Data Warehouse dengan Excel sumber (18 pemeriksaan; 15 bila tanpa --pra).
Angka pembanding dihitung ulang langsung dari Excel dengan cara yang terpisah dari ETL,
sehingga kesalahan pada ETL akan terlihat sebagai pemeriksaan yang GAGAL.

    python 03_rekonsiliasi.py --excel Data_Ternak_2022-2026.xlsx --pra hasil_pra_etl --mysql "mysql+pymysql://root:@localhost/dw_amana_farm"
    python 03_rekonsiliasi.py --excel Data_Ternak_2022-2026.xlsx --pra hasil_pra_etl --db dw_uji.sqlite

Hasilnya dicetak di layar dan disimpan di hasil_rekonsiliasi.csv.
"""
import argparse, sqlite3
import numpy as np, pandas as pd

TOL = 1e-4   # selisih yang masih dianggap sama untuk nilai ADG


def periksa(excel, con, pra=None, cetak=True):
    """Menjalankan seluruh pemeriksaan. Mengembalikan daftar (pemeriksaan, LULUS/GAGAL, detail).
    Dipanggil dari baris perintah maupun dari menu Import Data di dashboard (cetak=False)."""
    hasil = []

    def cek(nama, ok, detail=""):
        hasil.append((nama, "LULUS" if ok else "GAGAL", detail))
        if cetak:
            print(f"[{hasil[-1][1]}] {nama} {detail}")
    q = lambda s: pd.read_sql(s, con)

    tern = pd.read_excel(excel, "Data Ternak 2022-2026", parse_dates=["tanggal_lahir", "tanggal_keluar"])
    bb = pd.read_excel(excel, "Data Pencatatan BB", parse_dates=["tanggal_penimbangan"])
    pak = pd.read_excel(excel, "Data Pakan Harian", parse_dates=["Tanggal"])

    # 1. Jumlah baris tabel sama dengan jumlah baris Excel
    for tbl, n in [("dim_kambing", len(tern)), ("fact_bobot_ternak", len(bb)), ("fact_konsumsi_pakan", len(pak))]:
        m = int(q(f"select count(*) c from {tbl}").c[0]); cek(f"Jumlah baris {tbl}", m == n, f"(DW={m}, Excel={n})")
    # 2. Total berat badan dan total pakan sama
    s = q("select sum(berat_badan_kg) s from fact_bobot_ternak").s[0]
    cek("Total berat_badan_kg", abs(s - bb.berat_badan_kg.sum()) < 0.01, f"(DW={s:.2f}, Excel={bb.berat_badan_kg.sum():.2f})")
    s = q("select sum(total_pakan_kg) s from fact_konsumsi_pakan").s[0]
    cek("Total pakan (kg)", abs(s - pak["Total Pakan Harian (kg)"].sum()) < 0.01, f"(DW={s:.2f}, Excel={pak['Total Pakan Harian (kg)'].sum():.2f})")
    # 3. ADG dihitung ulang per kambing dengan perulangan biasa, lalu dibandingkan
    dw = q("select f.id_kambing, w.tanggal, f.berat_badan_kg, f.adg_kg_hari from fact_bobot_ternak f join dim_waktu w using(id_waktu)")
    dw["tanggal"] = pd.to_datetime(dw.tanggal); dw = dw.set_index(["id_kambing", "tanggal"])
    salah = 0; total = 0
    for kid, g in bb.sort_values("tanggal_penimbangan").groupby("id_kambing"):
        r = list(zip(g.tanggal_penimbangan, g.berat_badan_kg))
        for i in range(1, len(r)):
            exp = (r[i][1] - r[i-1][1]) / (r[i][0] - r[i-1][0]).days
            got = dw.loc[(kid, r[i][0]), "adg_kg_hari"]; total += 1
            if not np.isclose(exp, got, atol=TOL): salah += 1
    cek("ADG = (BB_t - BB_t-1) / selisih hari", salah == 0, f"({total} nilai diperiksa, selisih={salah})")
    # 4. Penimbangan pertama tidak punya ADG, dan semua foreign key menunjuk ke baris dimensi yang ada
    n0 = int(q("select count(*) c from fact_bobot_ternak where adg_kg_hari is null").c[0])
    cek("Penimbangan pertama tiap kambing ber-ADG kosong", n0 == bb.id_kambing.nunique(), f"(null={n0}, kambing={bb.id_kambing.nunique()})")
    orphan = int(q("""select count(*) c from fact_bobot_ternak f left join dim_segmen s using(id_segmen)
                     left join dim_usia u using(id_usia) where s.id_segmen is null or u.id_usia is null""").c[0])
    cek("Tidak ada orphan foreign key (segmen/usia)", orphan == 0, f"(orphan={orphan})")
    # 5. Satu kambing hanya punya satu segmen pada setiap rentang umur
    d = int(q("""select count(*) c from (select id_kambing, id_usia from fact_bobot_ternak
                 group by id_kambing, id_usia having count(distinct id_segmen) > 1) x""").c[0])
    cek("Segmen konsisten per kambing per rentang umur", d == 0, f"(pelanggaran={d})")
    # 6. Angka ringkasan (KPI) dashboard dihitung ulang dari Excel
    import queries as Q
    k = Q.kpi(con)
    st_ = tern.status.value_counts()
    cek("KPI jumlah kambing", int(k.total_kambing) == len(tern), f"(DW={int(k.total_kambing)}, Excel={len(tern)})")
    cek("KPI hidup/terjual/mati", (int(k.hidup), int(k.terjual), int(k.mati)) == (st_["Hidup"], st_["Terjual"], st_["Mati"]),
        f"(DW={int(k.hidup)}/{int(k.terjual)}/{int(k.mati)}, Excel={st_['Hidup']}/{st_['Terjual']}/{st_['Mati']})")
    bs = bb.sort_values(["id_kambing", "tanggal_penimbangan"])
    bs["d"] = bs.groupby("id_kambing").berat_badan_kg.diff() / bs.groupby("id_kambing").tanggal_penimbangan.diff().dt.days
    cek("KPI rata-rata ADG", abs(float(k.rata_adg) - bs.d.mean()) < TOL, f"(DW={float(k.rata_adg):.5f}, Excel={bs.d.mean():.5f})")
    last = bs.groupby("id_kambing").berat_badan_kg.last()
    exp = last[tern[tern.status == "Hidup"].id_kambing].mean()
    cek("KPI bobot rata-rata kambing hidup (penimbangan terakhir)", abs(float(k.rata_bobot_terakhir) - exp) < 0.01, f"(DW={float(k.rata_bobot_terakhir):.3f}, Excel={exp:.3f})")
    # 7. FCR populasi bulanan dihitung ulang dari Excel
    bs["gain"] = bs.groupby("id_kambing").berat_badan_kg.diff()
    bs["ym"] = bs.tanggal_penimbangan.dt.to_period("M")
    pak["ym"] = pak.Tanggal.dt.to_period("M")
    g = bs.dropna(subset=["gain"]).groupby("ym").gain.sum()
    pk = pak.groupby("ym")["Total Pakan Harian (kg)"].sum()
    fc = Q.pakan_fcr_bulanan(con)
    salah = 0
    for _, r in fc.iterrows():
        ym = pd.Period(year=int(r.tahun), month=int(r.bulan), freq="M")
        if g[ym] > 0 and not np.isclose(r.fcr, pk[ym] / g[ym], rtol=1e-6): salah += 1
    cek("FCR populasi bulanan = total pakan / total pertambahan bobot", salah == 0, f"({len(fc)} bulan diperiksa, selisih={salah})")
    # 8. Populasi aktif harian sama dengan hitungan ulang dari tanggal lahir dan tanggal keluar
    pa = q("select w.tanggal, c.populasi_aktif p from fact_konsumsi_pakan c join dim_waktu w using(id_waktu)")
    pa["tanggal"] = pd.to_datetime(pa.tanggal)
    # sengaja ditulis ulang di sini, tidak memakai fungsi dari etl_dw.py
    awal_catat = pak.Tanggal.min()
    akhir_catat = max(pak.Tanggal.max(), bb.tanggal_penimbangan.max())
    mulai = tern.tanggal_lahir.where(tern.tanggal_lahir >= awal_catat, awal_catat)
    akhir = tern.tanggal_keluar.where(tern.status != "Hidup", akhir_catat)
    salah = sum(int(((mulai <= d) & (d <= akhir)).sum()) != p_ for d, p_ in zip(pa.tanggal.iloc[::50], pa.p.iloc[::50]))
    cek("Populasi aktif harian (sampel tiap 50 hari)", salah == 0, f"(selisih={salah})")
    # 9. Segmen di Data Warehouse sama dengan hasil K-Means (label_klaster.csv)
    if pra:
        lab = pd.read_csv(f"{pra}/label_klaster.csv")
        sg = Q.segmentasi(con)
        m = lab.merge(sg, left_on=["id_kambing", "kelompok_umur"], right_on=["id_kambing", "rentang_umur"], how="left", suffixes=("", "_dw"))
        beda = int((m.segmen != m.segmen_dw).sum())
        cek("Segmen di DW = label K-Means", beda == 0, f"({len(lab)} data kambing-rentang umur, berbeda={beda})")
        cek("Jumlah baris hasil_klaster = label", int(q("select count(*) c from hasil_klaster").c[0]) == len(lab))
        cek("Jumlah anggota dim_segmen = label", int(q("select sum(jumlah_anggota) s from dim_segmen where id_segmen>0").s[0]) == len(lab))
    return hasil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", required=True); ap.add_argument("--db"); ap.add_argument("--mysql"); ap.add_argument("--pra", help="folder hasil pra-ETL (opsional, untuk cek segmen)")
    a = ap.parse_args()
    if a.mysql:
        from db import buat_koneksi; con = buat_koneksi(a.mysql)
    else:
        con = sqlite3.connect(a.db)
    hasil = periksa(a.excel, con, a.pra)
    gagal = [h for h in hasil if h[1] == "GAGAL"]
    print(f"\nRINGKASAN: {len(hasil)-len(gagal)}/{len(hasil)} lulus")
    pd.DataFrame(hasil, columns=["pengujian", "hasil", "detail"]).to_csv("hasil_rekonsiliasi.csv", index=False)

if __name__ == "__main__":
    main()
