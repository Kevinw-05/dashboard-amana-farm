"""
Tahap pra-ETL: menghitung fitur tiap kambing, menentukan jumlah klaster (K), menjalankan K-Means,
dan menyimpan hasilnya ke folder hasil_pra_etl untuk dibaca etl_dw.py.

Alur:
  Excel -> (1) fitur per kambing per rentang umur (rasio ADG dan rasio bobot terhadap kambing sebaya)
        -> (2) WCSS (Elbow) dan Silhouette untuk K = 2 sampai 8
        -> (3) pemilihan K dengan aturan di bawah
        -> (4) K-Means -> label segmen dan tabel pendukung (dim_usia, dim_segmen, validasi_k)

Cara pakai:
  python pra_etl_kmeans.py --excel Data_Ternak_2022-2026.xlsx --out hasil_pra_etl
  python pra_etl_kmeans.py --excel Data_Ternak_2022-2026.xlsx --out hasil_pra_etl --k 3   # menetapkan K sendiri

Aturan pemilihan K (ATURAN_K):
  1. Hitung WCSS (Elbow) dan Silhouette untuk K = 2..8.
  2. Titik siku (elbow) = K dengan jarak terjauh ke garis lurus antara titik awal dan akhir kurva WCSS.
  3. K terpilih = titik siku, JIKA silhouette-nya >= (1 - TOLERANSI_SIL) x silhouette tertinggi.
     Jika tidak, K terkecil yang silhouette-nya memenuhi syarat yang sama.
"""
import argparse
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

# ---------------- Pengaturan ----------------
SHEET_TERNAK = "Data Ternak 2022-2026"
SHEET_BB = "Data Pencatatan BB"
BATAS_CEMPE = 120        # umur sampai 120 hari = Cempe
BATAS_MUDA = 365         # 121 sampai 365 hari = Muda; lebih dari itu = Dewasa
MIN_OBS_ADG = 3          # minimal nilai ADG per kambing per rentang umur agar ikut dikelompokkan
K_MIN, K_MAX = 2, 8      # rentang K yang diuji
TOLERANSI_SIL = 0.03     # Silhouette K terpilih minimal 97% dari Silhouette tertinggi
TOLERANSI = 0.05         # centroid dalam +-5% dari 1,0 pada kedua rasio diberi nama "Rata-rata"
WINSOR = (1, 99)         # nilai rasio di luar persentil 1-99 dipotong agar tidak mendominasi (None = tidak dipotong)
SEED = 42                # angka acak tetap agar hasil K-Means selalu sama
N_INIT = 20              # K-Means diulang 20 kali dengan titik awal berbeda; hasil terbaik dipakai

# Rentang umur untuk kelompok sebaya (peer group). "halus" (bawaan) memecah tiga kategori usia menjadi
# tujuh rentang agar kambing umur 1 tahun tidak dibandingkan dengan kambing umur 4 tahun.
# "proposal" hanya memakai tiga kategori (Cempe, Muda, Dewasa).
RENTANG = {
    "proposal": ([-1, 120, 365, 10 ** 7], ["Cempe", "Muda", "Dewasa"]),
    "halus": ([-1, 120, 240, 365, 545, 730, 1095, 10 ** 7],
              ["Cempe", "Muda 121-240", "Muda 241-365", "Dewasa 366-545",
               "Dewasa 546-730", "Dewasa 731-1095", "Dewasa >1095"]),
}


def kategori_usia(umur_hari):
    """Kategori usia: Cempe / Muda / Dewasa."""
    return pd.cut(umur_hari, [-1, BATAS_CEMPE, BATAS_MUDA, 10 ** 7],
                  labels=["Cempe", "Muda", "Dewasa"])


def kelompok_umur(umur_hari, mode):
    """Rentang umur (kelompok sebaya) dari umur dalam hari."""
    edges, labels = RENTANG[mode]
    return pd.cut(umur_hari, edges, labels=labels)


def tabel_dim_usia(mode):
    """Isi tabel dim_usia: satu baris per rentang umur beserta kategori usianya."""
    edges, labels = RENTANG[mode]
    baris = []
    for i, lab in enumerate(labels):
        bawah, atas = edges[i] + 1, edges[i + 1]
        kat = "Cempe" if atas <= BATAS_CEMPE else ("Muda" if atas <= BATAS_MUDA else "Dewasa")
        baris.append({"id_usia": i + 1, "rentang_umur": str(lab), "kategori_usia": kat,
                      "umur_min_hari": max(bawah, 0), "umur_maks_hari": None if atas >= 10 ** 6 else atas})
    return pd.DataFrame(baris)


# ---------------- 1. Fitur ----------------
def bangun_fitur(excel, mode="halus"):
    """Menghitung ADG tiap penimbangan, lalu rata-rata ADG dan bobot tiap kambing per rentang umur,
    dibandingkan dengan rata-rata kambing sebayanya (ras, jenis kelamin, dan rentang umur yang sama)."""
    ternak = pd.read_excel(excel, SHEET_TERNAK)
    bb = pd.read_excel(excel, SHEET_BB, parse_dates=["tanggal_penimbangan"])
    bb = bb.sort_values(["id_kambing", "tanggal_penimbangan"]).merge(
        ternak[["id_kambing", "tanggal_lahir"]], on="id_kambing", how="left")

    # ADG = selisih bobot / jumlah hari sebenarnya antara dua penimbangan
    bb["selisih_hari"] = bb.groupby("id_kambing")["tanggal_penimbangan"].diff().dt.days
    bb["adg"] = bb.groupby("id_kambing")["berat_badan_kg"].diff() / bb["selisih_hari"]

    # Umur dan rentang umur dihitung pada saat penimbangan, bukan umur sekarang
    bb["umur_hari"] = (bb["tanggal_penimbangan"] - bb["tanggal_lahir"]).dt.days
    bb["kategori_usia"] = kategori_usia(bb["umur_hari"])
    bb["kelompok_umur"] = kelompok_umur(bb["umur_hari"], mode)

    # Kelompok sebaya = ras + jenis kelamin + rentang umur
    kunci = ["ras", "jenis_kelamin", "kelompok_umur"]
    peer = bb.groupby(kunci, observed=True).agg(
        peer_adg=("adg", "mean"), peer_bobot=("berat_badan_kg", "mean"),
        peer_n_ekor=("id_kambing", "nunique")).reset_index()

    fase = bb.groupby(["id_kambing", "kategori_usia"] + kunci, observed=True).agg(
        n_timbang=("berat_badan_kg", "size"), n_adg=("adg", "count"),
        rata_adg=("adg", "mean"), rata_bobot=("berat_badan_kg", "mean"),
        bobot_terakhir=("berat_badan_kg", "last")).reset_index()
    fase = fase[fase["n_timbang"] > 0]
    fase = fase.merge(peer, on=kunci, how="left")
    fase["rasio_adg"] = fase["rata_adg"] / fase["peer_adg"]
    fase["rasio_bobot"] = fase["rata_bobot"] / fase["peer_bobot"]
    fase["ikut_klaster"] = fase["n_adg"] >= MIN_OBS_ADG
    return bb, fase


# ---------------- 2. Penentuan dan validasi K ----------------
def validasi_k(X):
    """WCSS (inertia, untuk metode Elbow) dan Silhouette untuk setiap K dari K_MIN sampai K_MAX."""
    baris = []
    for k in range(K_MIN, K_MAX + 1):
        km = KMeans(n_clusters=k, n_init=N_INIT, random_state=SEED).fit(X)
        baris.append({"K": k, "inertia_wcss": km.inertia_,
                      "silhouette": silhouette_score(X, km.labels_)})
    return pd.DataFrame(baris)


def titik_siku(df):
    """Titik siku = K dengan jarak terjauh ke garis lurus antara titik awal dan akhir kurva WCSS."""
    k = df["K"].to_numpy(float)
    w = df["inertia_wcss"].to_numpy(float)
    p1, p2 = np.array([k[0], w[0]]), np.array([k[-1], w[-1]])
    d = []
    for ki, wi in zip(k, w):
        p = np.array([ki, wi])
        v, u = p2 - p1, p1 - p
        d.append(abs(v[0] * u[1] - v[1] * u[0]) / np.linalg.norm(v))
    return int(k[int(np.argmax(d))])


def pilih_k(val):
    """Aturan pemilihan K. Mengembalikan (K terpilih, K siku, K silhouette tertinggi, alasan)."""
    k_siku = titik_siku(val)
    sil_maks = val["silhouette"].max()
    k_sil = int(val.loc[val["silhouette"].idxmax(), "K"])
    syarat = val[val["silhouette"] >= (1 - TOLERANSI_SIL) * sil_maks]
    sil_siku = float(val.loc[val["K"] == k_siku, "silhouette"].iloc[0])
    if k_siku in set(syarat["K"]):
        alasan = (f"K={k_siku} adalah titik siku dan silhouette-nya {sil_siku:.3f} "
                  f"({sil_siku / sil_maks * 100:.1f}% dari tertinggi {sil_maks:.3f}, batas {100 * (1 - TOLERANSI_SIL):.0f}%).")
        return k_siku, k_siku, k_sil, alasan
    k_pilih = int(syarat["K"].min())
    alasan = (f"Silhouette titik siku (K={k_siku}) di bawah batas {100 * (1 - TOLERANSI_SIL):.0f}% dari tertinggi; "
              f"dipilih K terkecil yang memenuhi batas, yaitu K={k_pilih}.")
    return k_pilih, k_siku, k_sil, alasan


def grafik_validasi(df, k_pilih, path):
    """Menyimpan grafik Elbow dan Silhouette; garis putus-putus menandai K terpilih."""
    fig, ax = plt.subplots(1, 2, figsize=(10, 4))
    seri = [("inertia_wcss", "Elbow (WCSS / inertia)", "tab:blue"),
            ("silhouette", "Silhouette (makin tinggi makin baik)", "tab:green")]
    for a, (kol, judul, warna) in zip(ax, seri):
        a.plot(df["K"], df[kol], "o-", color=warna)
        a.set_title(judul, fontsize=10)
        a.axvline(k_pilih, ls="--", color="gray")
        a.set_xlabel("K")
        a.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ---------------- 3. K-Means dan penamaan segmen ----------------
def beri_nama(centroid):
    """Nama segmen dari posisi centroid terhadap kambing sebaya (rasio 1,0 = setara rata-rata)."""
    nama = []
    for _, r in centroid.iterrows():
        a, b = r["rasio_adg"] >= 1.0, r["rasio_bobot"] >= 1.0
        if abs(r["rasio_adg"] - 1) <= TOLERANSI and abs(r["rasio_bobot"] - 1) <= TOLERANSI:
            nama.append("Rata-rata")
        elif a and b:
            nama.append("Performa Tinggi")
        elif not a and not b:
            nama.append("Perlu Perhatian")
        elif a and not b:
            nama.append("Tumbuh Cepat, Bobot Rendah")
        else:
            nama.append("Bobot Tinggi, Tumbuh Lambat")
    nama = pd.Series(nama, index=centroid.index)
    dup = nama[nama.duplicated(keep=False)]
    for i in dup.index:                       # nama yang kembar diberi nomor klaster
        nama[i] = f"{nama[i]} (klaster {i})"
    return nama


# Penjelasan singkat tiap segmen (disimpan di dim_segmen)
KETERANGAN = {
    "Perlu Perhatian": "ADG dan bobot di bawah rata-rata peer group",
    "Rata-rata": "ADG dan bobot setara rata-rata peer group",
    "Performa Tinggi": "ADG dan bobot di atas rata-rata peer group",
    "Tumbuh Cepat, Bobot Rendah": "ADG di atas, bobot di bawah rata-rata peer group",
    "Bobot Tinggi, Tumbuh Lambat": "Bobot di atas, ADG di bawah rata-rata peer group",
}


def jalankan(excel, out="hasil_pra_etl", rentang="halus", k=None, cetak=True):
    """Menjalankan seluruh tahap pra-ETL. Dipanggil dari baris perintah maupun dari menu Import Data (cetak=False).
    k=None berarti K dipilih dengan aturan; angka berarti K ditetapkan sendiri.
    Mengembalikan ringkasan: K dipakai, K menurut aturan, alasan, dan jumlah data."""
    os.makedirs(out, exist_ok=True)
    bb, fase = bangun_fitur(excel, rentang)
    data = fase[fase["ikut_klaster"]].copy()
    fitur = ["rasio_adg", "rasio_bobot"]

    # Pada kambing tua rata-rata ADG sebaya mendekati 0, sehingga rasio ADG bisa sangat besar: nilai ekstrem dipotong
    for c in fitur:
        data[c + "_asli"] = data[c]
        if WINSOR:
            lo, hi = np.percentile(data[c], WINSOR)
            data[c] = data[c].clip(lo, hi)
    X = StandardScaler().fit_transform(data[fitur])   # standardisasi agar kedua fitur berbobot setara

    val = validasi_k(X)
    k_auto, k_siku, k_sil, alasan = pilih_k(val)
    k_pilih = k if k else k_auto
    val["k_terpilih"] = val["K"] == k_pilih
    val.to_csv(f"{out}/validasi_k.csv", index=False)
    grafik_validasi(val, k_pilih, f"{out}/validasi_k.png")

    km = KMeans(n_clusters=k_pilih, n_init=N_INIT, random_state=SEED).fit(X)
    data["cluster"] = km.labels_
    cent = data.groupby("cluster")[fitur].mean()           # centroid dalam satuan rasio (bukan hasil standardisasi)
    cent["jumlah_anggota"] = data.groupby("cluster").size()
    cent["segmen"] = beri_nama(cent)
    data["segmen"] = data["cluster"].map(cent["segmen"])

    # ---- simpan label segmen tiap kambing per rentang umur ----
    keluar = ["id_kambing", "ras", "jenis_kelamin", "kategori_usia", "kelompok_umur", "n_timbang", "n_adg",
              "rata_adg", "rata_bobot", "rasio_adg_asli", "rasio_bobot_asli", "rasio_adg",
              "rasio_bobot", "cluster", "segmen"]
    data[keluar].to_csv(f"{out}/label_klaster.csv", index=False)
    fase.to_csv(f"{out}/fitur_semua_fase.csv", index=False)

    # ---- tabel pendukung untuk ETL (segmen diurutkan dari skor terendah) ----
    tabel_dim_usia(rentang).to_csv(f"{out}/dim_usia.csv", index=False)
    urut = cent.assign(skor=cent[fitur].mean(axis=1)).sort_values("skor")
    seg = [{"id_segmen": 0, "nama_segmen": "Tidak Diklaster", "rasio_adg_centroid": None,
            "rasio_bobot_centroid": None, "jumlah_anggota": int((~fase["ikut_klaster"]).sum()),
            "keterangan": "Data penimbangan terlalu sedikit untuk diklasterkan"}]
    for i, (idx, r) in enumerate(urut.iterrows(), start=1):
        dasar = r["segmen"].split(" (klaster")[0]
        seg.append({"id_segmen": i, "nama_segmen": r["segmen"], "rasio_adg_centroid": round(r["rasio_adg"], 4),
                    "rasio_bobot_centroid": round(r["rasio_bobot"], 4), "jumlah_anggota": int(r["jumlah_anggota"]),
                    "keterangan": KETERANGAN.get(dasar, "")})
    pd.DataFrame(seg).to_csv(f"{out}/dim_segmen.csv", index=False)
    cent.to_csv(f"{out}/centroid.csv")

    # ---- catatan alasan pemilihan K ----
    with open(f"{out}/keputusan_k.txt", "w", encoding="utf-8") as f:
        f.write("ATURAN PEMILIHAN K\n" + __doc__.split("Aturan pemilihan K (ATURAN_K):")[1].strip() + "\n\n")
        f.write(val.round(4).to_string(index=False) + "\n\n")
        f.write(f"Titik siku (elbow): K={k_siku}\nSilhouette tertinggi: K={k_sil}\n")
        f.write(f"K menurut aturan: K={k_auto}\nK dipakai: K={k_pilih}"
                + (" (dipaksa lewat --k)" if k else "") + "\n")
        f.write("Alasan: " + alasan + "\n")

    # ---- peta klaster (scatter) ----
    fig, ax = plt.subplots(figsize=(7, 5))
    for s, d in data.groupby("segmen"):
        ax.scatter(d["rasio_adg"], d["rasio_bobot"], s=18, label=f"{s} ({len(d)})")
    ax.scatter(cent["rasio_adg"], cent["rasio_bobot"], marker="X", s=140, c="k", label="Centroid")
    ax.set_xlabel("Rasio ADG terhadap peer group")
    ax.set_ylabel("Rasio Bobot terhadap peer group")
    ax.legend(fontsize=8); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(f"{out}/scatter_klaster.png", dpi=150); plt.close(fig)

    ringkas = {"k": int(k_pilih), "k_aturan": int(k_auto), "k_siku": int(k_siku), "k_silhouette": int(k_sil),
               "alasan": alasan, "n_fase": int(len(fase)), "n_klaster": int(len(data)),
               "silhouette": float(val.loc[val["K"] == k_pilih, "silhouette"].iloc[0])}
    if not cetak:
        return ringkas
    print("Kambing-fase total:", len(fase), "| ikut klaster:", len(data),
          "| dikeluarkan (ADG < %d):" % MIN_OBS_ADG, int((~fase["ikut_klaster"]).sum()))
    print("\nValidasi K:\n", val.round(4).to_string(index=False))
    print(f"\nTitik siku: K={k_siku} | Silhouette tertinggi: K={k_sil} | Menurut aturan: K={k_auto} | Dipakai: K={k_pilih}")
    print("Alasan:", alasan)
    print("\nCentroid:\n", cent.round(4).to_string())
    return ringkas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", required=True)
    ap.add_argument("--out", default="hasil_pra_etl")
    ap.add_argument("--rentang", choices=list(RENTANG), default="halus",
                    help="rentang umur kelompok sebaya: halus (bawaan, 7 rentang) atau proposal (3 kategori)")
    ap.add_argument("--k", type=int, default=None, help="tetapkan K sendiri; tanpa opsi ini K dipilih dengan aturan")
    a = ap.parse_args()
    jalankan(a.excel, a.out, a.rentang, a.k)


if __name__ == "__main__":
    main()
