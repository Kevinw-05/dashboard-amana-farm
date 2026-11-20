"""
Dashboard Monitoring Bobot Ternak & Segmentasi K-Means - PT. Amana Albaroqh Farm
Jalankan:  python -m streamlit run app.py
Demo tanpa MySQL: set DB_URL=sqlite:///dw_uji.sqlite (file dibuat oleh etl_dw.py --sqlite dw_uji.sqlite)
Sumber data: MySQL dw_amana_farm (ubah DB_URL di bawah / variabel lingkungan DB_URL).
"""
import io
import os
import threading

import altair as alt
import pandas as pd
import streamlit as st
import impor
import queries as q

DB_URL = os.environ.get("DB_URL", "mysql+pymysql://root:@localhost/dw_amana_farm")   # di hosting: diisi lewat Secrets

st.set_page_config(page_title="Monitoring Bobot Ternak", layout="wide")

from auth import wajib_login, kotak_pengguna, tab_untuk

# ---------------- Warna dan teks penjelasan ----------------
WARNA = {"Performa Tinggi": "#2E7D32", "Rata-rata": "#8A9099", "Perlu Perhatian": "#C62828",
         "Tumbuh Cepat, Bobot Rendah": "#E69F00", "Bobot Tinggi, Tumbuh Lambat": "#1565C0",
         "Tidak Diklaster": "#BDBDBD"}
WARNA_RAS = {"Boer": "#1B6E5A", "Etawa": "#C77B0A", "PE": "#5B4B9A"}
ARTI_SEGMEN = {
    "Performa Tinggi": "Tumbuh lebih cepat dan lebih berat daripada kambing sebayanya.",
    "Rata-rata": "Pertumbuhan dan bobotnya setara dengan kambing sebayanya.",
    "Tumbuh Cepat, Bobot Rendah": "Sedang tumbuh cepat, tetapi bobotnya masih di bawah sebayanya.",
    "Bobot Tinggi, Tumbuh Lambat": "Bobotnya di atas sebayanya, tetapi pertumbuhannya melambat.",
    "Perlu Perhatian": "Tumbuh lebih lambat dan lebih ringan daripada kambing sebayanya.",
    "Tidak Diklaster": "Data penimbangan pada rentang umur itu belum cukup untuk dinilai.",
}

# ---- Monitoring: status dari segmen K-Means + bagan kendali Shewhart ----
STATUS_SEGMEN = {          # segmen (rentang umur terbaru) -> status monitoring
    "Performa Tinggi": "Normal",
    "Rata-rata": "Normal",
    "Tumbuh Cepat, Bobot Rendah": "Waspada",
    "Bobot Tinggi, Tumbuh Lambat": "Waspada",
    "Perlu Perhatian": "Perlu Tindakan",
    "Tidak Diklaster": "Belum Dinilai",
}
TINDAK_LANJUT = {
    "Normal": "Pertahankan; performa tinggi dapat dipertimbangkan sebagai calon bibit",
    "Waspada": "Pantau pada penimbangan berikutnya",
    "Perlu Tindakan": "Periksa kesehatan dan pakan oleh supervisor",
    "Belum Dinilai": "Data penimbangan pada rentang umur ini belum cukup (< 3 nilai ADG)",
}
WARNA_STATUS = {"Normal": "#2E7D32", "Waspada": "#E69F00", "Perlu Tindakan": "#C62828", "Belum Dinilai": "#8A9099"}
LATAR_STATUS = {"Normal": "#E3F1E4", "Waspada": "#FCEFCF", "Perlu Tindakan": "#F9DEDC", "Belum Dinilai": "#ECEEF0"}
ARTI_STATUS = {"Normal": "Sesuai atau di atas sebayanya", "Waspada": "Perlu dipantau",
               "Perlu Tindakan": "Tertinggal dari sebayanya", "Belum Dinilai": "Data belum cukup"}

# Nama kolom yang mudah dibaca
KOLOM = {"id_kambing": "ID Kambing", "ras": "Ras", "jenis_kelamin": "Jenis kelamin", "status": "Keberadaan",
         "status_monitoring": "Status", "segmen": "Segmen", "rentang_umur": "Rentang umur",
         "umur_hari": "Umur (hari)", "bobot_terakhir": "Bobot terakhir (kg)", "tgl_timbang_terakhir": "Timbang terakhir",
         "n_timbang": "Jumlah timbang", "rata_adg": "ADG rata-rata (kg/hari)", "rata_bobot": "Bobot rata-rata (kg)",
         "rasio_adg": "Rasio ADG", "rasio_bobot": "Rasio bobot", "skor": "Skor",
         "tindak_lanjut": "Saran tindak lanjut", "segmen_dinilai_terakhir": "Segmen terakhir dinilai"}
BANTUAN_KOLOM = {
    "Rasio ADG": "Kecepatan tumbuh dibanding rata-rata kambing sebaya. 1,0 = sama; 0,8 = 20% lebih lambat.",
    "Rasio bobot": "Bobot dibanding rata-rata kambing sebaya. 1,0 = sama; 1,2 = 20% lebih berat.",
    "Skor": "Rata-rata Rasio ADG dan Rasio bobot. Makin kecil, makin tertinggal dari sebayanya.",
    "Segmen": "Kelompok performa hasil K-Means pada rentang umur tersebut.",
    "Status": "Diturunkan dari segmen pada rentang umur terbaru.",
}

def status_dari_segmen(nama):
    dasar = str(nama).split(" (klaster")[0]       # nama kembar diberi akhiran "(klaster i)"
    return STATUS_SEGMEN.get(dasar, "Belum Dinilai")

def warna_segmen(nama):
    return WARNA.get(str(nama).split(" (klaster")[0], "#8A9099")

def batas_kendali(nilai):
    """Shewhart: CL = rata-rata, UCL/LCL = CL +- 3 simpangan baku (Mertens dkk., 2011)."""
    cl, sd = float(nilai.mean()), float(nilai.std(ddof=1))
    return cl, cl + 3 * sd, cl - 3 * sd

# ---------------- Komponen tampilan ----------------
st.markdown("""<style>
.block-container {padding-top: 2.2rem; max-width: 1280px;}
div[data-testid="stMetric"] {background: #FFFFFF; border: 1px solid #DDE5DB; border-radius: 10px; padding: 12px 14px; min-height: 118px;}
div[data-testid="stMetricLabel"] p {font-size: 0.85rem; color: #4C5A52; white-space: normal; overflow: visible; text-overflow: clip;}
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] * {white-space: normal !important; overflow: visible !important; text-overflow: clip !important;}
.strip {height: 6px; border-radius: 6px 6px 0 0; margin-bottom: -4px;}
.kartu-seg {background: #FFFFFF; border: 1px solid #DDE5DB; border-left-width: 6px; border-radius: 10px;
            padding: 10px 14px; height: 100%; margin-bottom: 8px;}
.kartu-seg .nama {font-weight: 600; font-size: 0.95rem;}
.kartu-seg .angka {font-size: 1.5rem; font-weight: 700; line-height: 1.3;}
.kartu-seg .arti {font-size: 0.82rem; color: #4C5A52;}
.petunjuk {background: #EEF3EC; border-radius: 10px; padding: 10px 14px; font-size: 0.92rem; margin-bottom: 10px;}
</style>""", unsafe_allow_html=True)

def petunjuk(teks):
    st.markdown(f'<div class="petunjuk">{teks}</div>', unsafe_allow_html=True)

def gambar(chart):
    try:
        st.altair_chart(chart, width="stretch")                  # Streamlit baru
    except TypeError:
        st.altair_chart(chart, use_container_width=True)         # Streamlit lama

def tabel(df, tinggi=None):
    """Tabel dengan nama kolom yang mudah dibaca, keterangan kolom, dan warna pada kolom Status/Segmen."""
    d = df.rename(columns=KOLOM)
    cfg = {k: st.column_config.Column(help=v) for k, v in BANTUAN_KOLOM.items() if k in d.columns}
    tiga = ["Rasio ADG", "Rasio bobot", "Skor", "ADG rata-rata (kg/hari)"]
    fmt = {k: ("{:.3f}" if k in tiga else "{:.2f}") for k in d.columns if pd.api.types.is_float_dtype(d[k])}
    gaya = d.style.format(fmt, na_rep="-")
    pewarna = getattr(gaya, "map", None) or gaya.applymap          # pandas lama memakai applymap
    if "Status" in d.columns:
        gaya = pewarna(lambda v: f"background-color: {LATAR_STATUS.get(v, '')}; font-weight: 600", subset=["Status"])
    kw = dict(hide_index=True, column_config=cfg)
    if tinggi:
        kw["height"] = tinggi
    try:
        st.dataframe(gaya, width="stretch", **kw)                # Streamlit baru
    except TypeError:
        st.dataframe(gaya, use_container_width=True, **kw)       # Streamlit lama

def grafik_garis(d, x, y, judul_y, warna="#1B6E5A", fmt=".2f"):
    dasar = alt.Chart(d).encode(
        x=alt.X(f"{x}:T", title=None, axis=alt.Axis(format="%b %Y", labelAngle=0, tickCount=8)),
        y=alt.Y(f"{y}:Q", title=judul_y, scale=alt.Scale(zero=False)),
        tooltip=[alt.Tooltip(f"{x}:T", title="Periode", format="%B %Y"), alt.Tooltip(f"{y}:Q", title=judul_y, format=fmt)])
    return (dasar.mark_line(color=warna, strokeWidth=2) + dasar.mark_circle(color=warna, size=28)).properties(height=280)

def grafik_kendali(d, judul_y):
    """Bagan kendali Shewhart. d: kolom periode, nilai, n_ekor. Mengembalikan (grafik, titik di luar batas)."""
    cl, ucl, lcl = batas_kendali(d.nilai)
    d = d.assign(di_luar=(d.nilai > ucl) | (d.nilai < lcl))
    luar = d[d.di_luar]
    x = alt.X("periode:T", title=None, axis=alt.Axis(format="%b %Y", labelAngle=0, tickCount=8))
    tip = [alt.Tooltip("periode:T", title="Bulan", format="%B %Y"), alt.Tooltip("nilai:Q", title=judul_y, format=".3f"),
           alt.Tooltip("n_ekor:Q", title="Jumlah ekor", format=".0f")]
    garis = alt.Chart(d).mark_line(color="#1B6E5A", strokeWidth=1.6).encode(x=x, y=alt.Y("nilai:Q", title=judul_y, scale=alt.Scale(zero=False)))
    titik = alt.Chart(d).mark_circle(color="#1B6E5A", size=26).encode(x=x, y="nilai:Q", tooltip=tip)
    batas = pd.DataFrame({"y": [cl, ucl, lcl], "nama": [f"Garis tengah (CL) {cl:.3f}", f"Batas atas (UCL) {ucl:.3f}", f"Batas bawah (LCL) {lcl:.3f}"],
                          "jenis": ["CL", "Batas", "Batas"]})
    aturan = alt.Chart(batas).mark_rule(strokeWidth=1.4).encode(
        y="y:Q", strokeDash=alt.StrokeDash("jenis:N", scale=alt.Scale(domain=["CL", "Batas"], range=[[1, 0], [6, 4]]), legend=None),
        color=alt.Color("jenis:N", scale=alt.Scale(domain=["CL", "Batas"], range=["#2E7D32", "#C62828"]), legend=None))
    label = alt.Chart(batas.assign(x=d.periode.max())).mark_text(align="right", dy=-7, fontSize=11, color="#3B463F").encode(
        x="x:T", y="y:Q", text="nama:N")
    lapis = aturan + garis + titik + label
    if len(luar):
        lapis += alt.Chart(luar).mark_point(color="#C62828", size=260, strokeWidth=2.2, filled=False).encode(x=x, y="nilai:Q", tooltip=tip)
        lapis += alt.Chart(luar).mark_text(dy=-18, color="#C62828", fontWeight="bold", fontSize=11).encode(
            x=x, y="nilai:Q", text=alt.Text("periode:T", format="%b %Y"))
    return lapis.properties(height=300), luar

def peta_klaster(tk, kom, sorot=None):
    """Scatter rasio ADG vs rasio bobot terhadap kelompok sebaya; tanda silang = pusat (centroid) segmen."""
    urut = [s for s in kom.segmen if s in set(tk.segmen)]
    skala = alt.Scale(domain=urut, range=[warna_segmen(s) for s in urut])
    pudar = alt.value(0.75) if not sorot else alt.condition(alt.datum.segmen == sorot, alt.value(0.9), alt.value(0.12))
    titik = alt.Chart(tk).mark_circle(size=55).encode(
        x=alt.X("rasio_adg:Q", title="Rasio ADG (kanan = tumbuh lebih cepat dari sebayanya)", scale=alt.Scale(zero=False)),
        y=alt.Y("rasio_bobot:Q", title="Rasio bobot (atas = lebih berat dari sebayanya)", scale=alt.Scale(zero=False)),
        color=alt.Color("segmen:N", scale=skala, legend=alt.Legend(title="Segmen", orient="bottom", columns=2, labelLimit=260)),
        opacity=pudar,
        tooltip=[alt.Tooltip("id_kambing:N", title="ID Kambing"), alt.Tooltip("ras:N", title="Ras"),
                 alt.Tooltip("jenis_kelamin:N", title="Jenis kelamin"), alt.Tooltip("rentang_umur:N", title="Rentang umur"),
                 alt.Tooltip("segmen:N", title="Segmen"), alt.Tooltip("rasio_adg:Q", title="Rasio ADG", format=".2f"),
                 alt.Tooltip("rasio_bobot:Q", title="Rasio bobot", format=".2f")])
    satu = pd.DataFrame({"v": [1.0]})
    acuan = (alt.Chart(satu).mark_rule(color="#7A857E", strokeDash=[5, 4]).encode(x="v:Q")
             + alt.Chart(satu).mark_rule(color="#7A857E", strokeDash=[5, 4]).encode(y="v:Q"))
    c = kom[kom.rasio_adg_centroid.notna() & kom.segmen.isin(urut)].copy()
    c["rasio_adg_centroid"] = c.rasio_adg_centroid.astype(float); c["rasio_bobot_centroid"] = c.rasio_bobot_centroid.astype(float)
    pusat = alt.Chart(c).mark_point(shape="cross", size=260, color="black", filled=True, angle=45, opacity=1).encode(
        x="rasio_adg_centroid:Q", y="rasio_bobot_centroid:Q",
        tooltip=[alt.Tooltip("segmen:N", title="Pusat segmen"), alt.Tooltip("rasio_adg_centroid:Q", title="Rasio ADG", format=".2f"),
                 alt.Tooltip("rasio_bobot_centroid:Q", title="Rasio bobot", format=".2f")])
    return (acuan + titik + pusat).properties(height=460)

@st.cache_resource
def koneksi():
    # lokal (XAMPP), cloud dengan TLS (?ssl=true), atau SQLite untuk demo; lihat db.py
    from db import buat_koneksi
    return buat_koneksi(DB_URL, thread_aman=True)

@st.cache_data(ttl=300)
def muat(nama, ras=None):
    con = koneksi()
    return getattr(q, nama)(con, ras) if ras is not None else getattr(q, nama)(con)

@st.cache_data(ttl=300)
def muat_tren(ras, kategori):
    return q.tren_bobot(koneksi(), ras, kategori)

def kondisi_terkini():
    """Satu baris per kambing: segmen pada rentang umur TERBARU, status monitoring, skor, dan penimbangan terakhir."""
    seg = muat("segmentasi").merge(
        muat("titik_klaster")[["id_kambing", "rentang_umur", "rasio_adg", "rasio_bobot"]],
        on=["id_kambing", "rentang_umur"], how="left")
    seg["tgl_terakhir"] = pd.to_datetime(seg.tgl_terakhir)
    seg = seg.sort_values(["id_kambing", "tgl_terakhir"])
    # segmen terakhir yang pernah dinilai (keterangan bila rentang terbaru Belum Dinilai)
    dinilai = seg[seg.segmen != "Tidak Diklaster"].groupby("id_kambing").tail(1)
    m = seg.groupby("id_kambing").tail(1).copy()
    m = m.merge(dinilai[["id_kambing", "segmen"]].rename(columns={"segmen": "segmen_dinilai_terakhir"}), on="id_kambing", how="left")
    m = m.merge(muat("timbang_terakhir"), on="id_kambing", how="left")
    m["status_monitoring"] = m.segmen.map(status_dari_segmen)
    m["skor"] = (m.rasio_adg + m.rasio_bobot) / 2
    m["tindak_lanjut"] = m.status_monitoring.map(TINDAK_LANJUT)
    m["tgl_timbang_terakhir"] = pd.to_datetime(m.tgl_timbang_terakhir).dt.strftime("%Y-%m-%d")
    return m

# ---- Login (akun di tabel pengguna, MySQL): tanpa login, sisa halaman tidak dijalankan ----
try:
    _con = koneksi()
except Exception as e:                       # mis. berkas SQLite tidak ditemukan
    st.error(f"Tabel pengguna belum siap atau database tidak terjangkau. Periksa alamat database (DB_URL). Detail: {e}")
    st.stop()
pengguna = wajib_login(_con)
kotak_pengguna(pengguna)

with st.sidebar:
    st.divider()
    st.markdown("**Istilah singkat**")
    st.caption("**ADG** (Average Daily Gain): pertambahan bobot per hari, dalam kg/hari.")
    st.caption("**Kambing sebaya** (peer group): kambing dengan ras, jenis kelamin, dan rentang umur yang sama.")
    st.caption("**Rasio**: perbandingan dengan rata-rata kambing sebaya. 1,0 berarti sama dengan rata-rata.")
    st.caption("**Segmen**: kelompok performa hasil K-Means.")
    st.caption("**FCR** (Feed Conversion Ratio): kg pakan untuk menghasilkan 1 kg pertambahan bobot. Makin kecil makin hemat.")

st.title("Monitoring Bobot Ternak dan Segmentasi K-Means")
_isi = impor.ringkasan_dw(koneksi())
st.caption("PT. Amana Albaroqh Farm | Data Warehouse MySQL | Klasterisasi dihitung pada tahap pra-ETL (Python)"
           + (f" | Data sampai {_isi['akhir']:%d-%m-%Y}" if _isi.get("akhir") is not None else ""))

try:
    k = muat("kpi")
except Exception as e:
    st.error(f"Tidak dapat terhubung ke database: {e}")
    st.stop()

c = st.columns(5)
c[0].metric("Total kambing tercatat", int(k.total_kambing), help=f"{int(k.terjual)} terjual, {int(k.mati)} mati, {int(k.hidup)} masih hidup")
c[1].metric("Masih hidup", int(k.hidup), help="Kambing yang saat ini masih ada di peternakan")
c[2].metric("Rata-rata ADG (kg/hari)", f"{k.rata_adg:.3f}", help="Rata-rata pertambahan bobot per hari dari seluruh penimbangan")
c[3].metric("Bobot rata-rata kambing hidup (kg)", f"{k.rata_bobot_terakhir:.1f}", help="Penimbangan terakhir tiap kambing yang masih hidup")
c[4].metric("Pakan per ekor (kg/hari, terakhir)", f"{k.pakan_per_ekor_terakhir:.2f}", help="Total pakan hari terakhir dibagi jumlah kambing aktif")
tot = int(k.total_kambing)
st.caption("Persentase status ternak: " + " | ".join(
    f"**{nama}** {int(n)} ekor ({int(n) / tot * 100:.1f}%)" for nama, n in [("Hidup", k.hidup), ("Terjual", k.terjual), ("Mati", k.mati)]))

# Hanya tab yang diizinkan untuk peran ini yang dibuat dan dijalankan
nama_tab = tab_untuk(pengguna["kode_peran"])
tabs = dict(zip(nama_tab, st.tabs(nama_tab)))

if "Bobot dan ADG" in tabs:
    with tabs["Bobot dan ADG"]:
        petunjuk("<b>Halaman ini menjawab:</b> bagaimana perkembangan bobot dan kecepatan tumbuh kambing dari bulan ke bulan? "
                 "Pilih ras dan kategori usia untuk melihat kelompok tertentu.")
        f1, f2 = st.columns(2)
        ras = f1.selectbox("Ras", ["Semua", "Boer", "Etawa", "PE"])
        kat = f2.selectbox("Kategori usia", ["Semua", "Cempe", "Muda", "Dewasa"],
                           help="Cempe: sampai 120 hari. Muda: 121 sampai 365 hari. Dewasa: lebih dari 365 hari.")
        d = muat_tren(None if ras == "Semua" else ras, None if kat == "Semua" else kat)
        d["periode"] = pd.to_datetime(dict(year=d.tahun, month=d.bulan, day=1))
        if kat == "Semua":
            st.caption("Catatan: rata-rata seluruh populasi dipengaruhi komposisi umur (cempe yang baru lahir menurunkan rata-rata). "
                       "Pilih satu kategori usia untuk perbandingan yang adil.")
        a, b = st.columns(2)
        with a:
            st.subheader("Rata-rata bobot per bulan (kg)")
            gambar(grafik_garis(d, "periode", "rata_bobot", "Bobot (kg)", fmt=".1f"))
        with b:
            st.subheader("Rata-rata ADG per bulan (kg/hari)")
            gambar(grafik_garis(d, "periode", "rata_adg", "ADG (kg/hari)", warna="#C77B0A", fmt=".3f"))
        st.subheader("ADG per ras dan kategori usia")
        e = muat("adg_per_ras_usia")
        top = e.loc[e.rata_adg.idxmax()]
        st.caption(f"ADG tertinggi: ras {top.ras} pada kategori {top.kategori_usia} ({top.rata_adg:.3f} kg/hari). "
                   "Kambing dewasa wajar memiliki ADG kecil karena pertumbuhannya sudah melambat.")
        urut_kat = ["Cempe", "Muda", "Dewasa"]
        dasar = alt.Chart(e).encode(
            x=alt.X("kategori_usia:N", title=None, sort=urut_kat, axis=alt.Axis(labelAngle=0, labelFontSize=13)),
            xOffset=alt.XOffset("ras:N", sort=list(WARNA_RAS)),
            y=alt.Y("rata_adg:Q", title="ADG (kg/hari)"))
        batang = dasar.mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
            color=alt.Color("ras:N", scale=alt.Scale(domain=list(WARNA_RAS), range=list(WARNA_RAS.values())),
                            legend=alt.Legend(title="Ras", orient="top")),
            tooltip=[alt.Tooltip("ras:N", title="Ras"), alt.Tooltip("kategori_usia:N", title="Kategori usia"),
                     alt.Tooltip("rata_adg:Q", title="ADG (kg/hari)", format=".3f"), alt.Tooltip("n:Q", title="Jumlah penimbangan")])
        angka = dasar.mark_text(dy=-7, fontSize=11, color="#1F2A24").encode(text=alt.Text("rata_adg:Q", format=".3f"))
        gambar((batang + angka).properties(height=320))

if "Segmentasi" in tabs:
    with tabs["Segmentasi"]:
        petunjuk("<b>Halaman ini menjawab:</b> kambing terbagi ke dalam kelompok performa apa saja, dan siapa anggotanya? "
                 "Setiap kambing dibandingkan dengan <b>kambing sebayanya</b> (ras, jenis kelamin, dan rentang umur yang sama), "
                 "lalu dikelompokkan oleh K-Means menjadi segmen.")
        seg = muat("segmentasi")
        kom = muat("komposisi_segmen")
        tk = muat("titik_klaster")

        st.subheader("Komposisi segmen")
        st.caption("Satu kambing dinilai sekali pada setiap rentang umur yang dilaluinya, sehingga jumlah data lebih banyak "
                   "daripada jumlah kambing dan satu kambing dapat berpindah segmen saat umurnya bertambah.")
        kartu = st.columns(len(kom))
        total_data = int(kom.jumlah_anggota.sum())
        urut_kartu = pd.concat([kom[kom.segmen != "Tidak Diklaster"], kom[kom.segmen == "Tidak Diklaster"]])
        for i, r in enumerate(urut_kartu.itertuples()):
            dasar_nama = str(r.segmen).split(" (klaster")[0]
            kartu[i].markdown(
                f'<div class="kartu-seg" style="border-left-color:{warna_segmen(r.segmen)}"><div class="nama">{r.segmen}</div>'
                f'<div class="angka">{int(r.jumlah_anggota)} <span style="font-size:0.8rem;font-weight:400">data '
                f'({int(r.jumlah_anggota) / total_data * 100:.0f}%)</span></div>'
                f'<div class="arti">{ARTI_SEGMEN.get(dasar_nama, r.keterangan)}</div></div>', unsafe_allow_html=True)
        with st.expander("Lihat tabel pusat (centroid) tiap segmen"):
            st.dataframe(kom.rename(columns={"segmen": "Segmen", "jumlah_anggota": "Jumlah data", "rasio_adg_centroid": "Rasio ADG pusat",
                                             "rasio_bobot_centroid": "Rasio bobot pusat", "keterangan": "Keterangan"}), hide_index=True)

        st.subheader("Daftar kambing per segmen")
        f1, f2, f3 = st.columns([1.2, 1, 1.6])
        pilih_seg = f1.selectbox("Segmen", ["Semua segmen"] + list(urut_kartu.segmen),
                                 help="Pilih segmen untuk melihat anggotanya. Segmen yang dipilih juga disorot pada peta klaster.")
        rg = f2.multiselect("Ras", sorted(seg.ras.unique()), default=sorted(seg.ras.unique()), key="ras_segmen")
        semua_rentang = list(dict.fromkeys(seg.rentang_umur))
        ur = f3.multiselect("Rentang umur", semua_rentang, default=semua_rentang)
        cakupan = st.radio("Data yang ditampilkan",
                           ["Kondisi terkini (kambing hidup, rentang umur terbaru)", "Seluruh riwayat (semua rentang umur)"],
                           horizontal=True, help="Kondisi terkini: satu baris per kambing. Seluruh riwayat: satu baris per kambing per rentang umur.")
        if cakupan.startswith("Kondisi terkini"):
            dsr = kondisi_terkini()
            dsr = dsr[dsr.status == "Hidup"]
            kol = ["id_kambing", "ras", "jenis_kelamin", "segmen", "rentang_umur", "umur_hari", "bobot_terakhir",
                   "tgl_timbang_terakhir", "rasio_adg", "rasio_bobot", "skor"]
        else:
            dsr = seg.merge(tk[["id_kambing", "rentang_umur", "rasio_adg", "rasio_bobot"]], on=["id_kambing", "rentang_umur"], how="left")
            dsr["skor"] = (dsr.rasio_adg + dsr.rasio_bobot) / 2
            kol = ["id_kambing", "ras", "jenis_kelamin", "status", "segmen", "rentang_umur", "n_timbang", "rata_adg", "rata_bobot",
                   "rasio_adg", "rasio_bobot", "skor"]
        s = dsr[dsr.ras.isin(rg) & dsr.rentang_umur.isin(ur)]
        hitung = s.segmen.value_counts().reindex([n for n in kom.segmen if n in set(s.segmen)]).rename_axis("segmen").reset_index(name="jumlah")
        if pilih_seg != "Semua segmen":
            s = s[s.segmen == pilih_seg]
        kiri, kanan = st.columns([1, 1.9])
        with kiri:
            st.markdown("**Jumlah per segmen** (sesuai filter)")
            if len(hitung):
                dasar = alt.Chart(hitung).encode(
                    y=alt.Y("segmen:N", sort=list(urut_kartu.segmen), title=None, axis=alt.Axis(labelLimit=220)),
                    x=alt.X("jumlah:Q", title="Jumlah"))
                gambar((dasar.mark_bar(cornerRadiusTopRight=3, cornerRadiusBottomRight=3).encode(
                    color=alt.Color("segmen:N", scale=alt.Scale(domain=list(hitung.segmen), range=[warna_segmen(x) for x in hitung.segmen]), legend=None),
                    opacity=alt.value(0.9) if pilih_seg == "Semua segmen" else alt.condition(alt.datum.segmen == pilih_seg, alt.value(1), alt.value(0.25)),
                    tooltip=[alt.Tooltip("segmen:N", title="Segmen"), alt.Tooltip("jumlah:Q", title="Jumlah")])
                    + dasar.mark_text(align="left", dx=4, fontSize=12).encode(text="jumlah:Q")).properties(height=44 * len(hitung) + 40))
        with kanan:
            st.markdown(f"**{len(s)} baris** pada: {pilih_seg}. Urutan: skor terendah di atas.")
            if len(s):
                tabel(s.sort_values(["skor", "id_kambing"], na_position="last")[kol], tinggi=330)
                st.download_button("Unduh daftar ini (CSV)", s[kol].to_csv(index=False).encode("utf-8"),
                                   file_name="daftar_kambing_per_segmen.csv", mime="text/csv", key="unduh_segmen")
            else:
                st.info("Tidak ada kambing yang sesuai dengan filter ini.")

        st.subheader("Peta klaster K-Means")
        with st.expander("Cara membaca peta ini", expanded=True):
            st.markdown("- **Satu titik** = satu kambing pada satu rentang umur. Arahkan kursor ke titik untuk melihat ID kambing.\n"
                        "- **Garis putus-putus (1,0)** = rata-rata kambing sebaya. Kanan garis berarti tumbuh lebih cepat; atas garis berarti lebih berat.\n"
                        "- **Tanda silang hitam** = pusat (centroid) tiap segmen.\n"
                        "- Titik yang menumpuk di tepi adalah nilai ekstrem yang dibatasi pada persentil 1 dan 99.")
        gambar(peta_klaster(tk[tk.ras.isin(rg) & tk.rentang_umur.isin(ur)], kom, None if pilih_seg == "Semua segmen" else pilih_seg))

if "Monitoring" in tabs:
    with tabs["Monitoring"]:
        petunjuk("<b>Halaman ini menjawab:</b> kambing mana yang perlu ditangani <b>sekarang</b>, dan apakah ada bulan yang tidak wajar? "
                 "Status diturunkan dari segmen K-Means pada rentang umur terbaru tiap kambing.")
        st.subheader("Status ternak")
        with st.expander("Arti setiap status"):
            st.dataframe(pd.DataFrame([
                {"Status": s, "Segmen asal": ", ".join(g for g, t in STATUS_SEGMEN.items() if t == s), "Saran tindak lanjut": TINDAK_LANJUT[s]}
                for s in ["Normal", "Waspada", "Perlu Tindakan", "Belum Dinilai"]]), hide_index=True)
            st.caption("Skor = rata-rata rasio ADG dan rasio bobot terhadap kambing sebaya (1,0 = setara rata-rata). Skor terendah berada paling atas.")
        m = kondisi_terkini()
        f1, f2 = st.columns(2)
        hanya_hidup = f1.checkbox("Hanya kambing yang masih hidup", value=True)
        rg = f2.multiselect("Ras", sorted(m.ras.unique()), default=sorted(m.ras.unique()), key="ras_monitor")
        v = m[m.ras.isin(rg)]
        if hanya_hidup:
            v = v[v.status == "Hidup"]
        kartu = st.columns(4)
        for i, nama in enumerate(["Normal", "Waspada", "Perlu Tindakan", "Belum Dinilai"]):
            kartu[i].markdown(f'<div class="strip" style="background:{WARNA_STATUS[nama]}"></div>', unsafe_allow_html=True)
            kartu[i].metric(nama, int((v.status_monitoring == nama).sum()), help=TINDAK_LANJUT[nama])
            kartu[i].caption(ARTI_STATUS[nama])

        pilih = st.radio("Tampilkan status", ["Perlu Tindakan", "Waspada", "Normal", "Belum Dinilai", "Semua"], horizontal=True)
        daftar = v if pilih == "Semua" else v[v.status_monitoring == pilih]
        kolom = ["id_kambing", "ras", "jenis_kelamin", "status_monitoring", "segmen", "rentang_umur", "umur_hari",
                 "bobot_terakhir", "tgl_timbang_terakhir", "rasio_adg", "rasio_bobot", "skor", "tindak_lanjut"]
        if pilih in ("Belum Dinilai", "Semua"):
            kolom.insert(6, "segmen_dinilai_terakhir")
        if pilih != "Semua":
            st.markdown(f"**{len(daftar)} ekor** berstatus {pilih}. Saran: {TINDAK_LANJUT[pilih]}.")
        tabel(daftar.sort_values(["skor", "id_kambing"], na_position="last")[kolom], tinggi=360)
        st.download_button("Unduh daftar (CSV)", daftar[kolom].to_csv(index=False).encode("utf-8"),
                           file_name=f"status_ternak_{pilih.lower().replace(' ', '_')}.csv", mime="text/csv")

        st.subheader("Bagan kendali indikator populasi")
        with st.expander("Cara membaca bagan kendali", expanded=True):
            st.markdown("- **Garis hijau (CL)** = rata-rata seluruh bulan. **Garis merah putus-putus (UCL dan LCL)** = CL ± 3 simpangan baku.\n"
                        "- Titik di dalam batas dianggap wajar. Titik **di luar batas** diberi lingkaran merah dan perlu dicek penyebabnya.\n"
                        "- Data ternak tidak selalu memenuhi asumsi bagan kendali (Mertens dkk., 2011), "
                        "jadi tanda ini adalah indikasi awal yang perlu dicek langsung di kandang.")
        kat = st.selectbox("Kategori usia (ADG)", ["Cempe", "Muda", "Dewasa"], index=2)
        ad = muat("adg_bulanan_kategori")
        ad = ad[ad.kategori_usia == kat].copy()
        ad["periode"] = pd.to_datetime(dict(year=ad.tahun, month=ad.bulan, day=1))
        st.markdown(f"**Rata-rata ADG bulanan, kategori {kat} (kg/hari)**")
        fig, luar_adg = grafik_kendali(ad, "ADG (kg/hari)")
        gambar(fig)

        pk = muat("pakan_per_ekor_bulanan")
        pk["periode"] = pd.to_datetime(dict(year=pk.tahun, month=pk.bulan, day=1))
        st.markdown("**Rata-rata pakan per ekor per hari, per bulan (kg, berat segar)**")
        fig, luar_pk = grafik_kendali(pk, "Pakan per ekor (kg/hari)")
        gambar(fig)

        luar = pd.concat([luar_adg.assign(indikator=f"ADG {kat}"), luar_pk.assign(indikator="Pakan per ekor")])
        if len(luar):
            st.warning(f"{len(luar)} bulan berada di luar batas kendali:")
            st.dataframe(luar.assign(bulan=luar.periode.dt.strftime("%Y-%m"))[["indikator", "bulan", "nilai", "n_ekor"]]
                         .round(3), hide_index=True)
        else:
            st.success("Semua bulan berada di dalam batas kendali.")

if "Pakan dan FCR" in tabs:
    with tabs["Pakan dan FCR"]:
        petunjuk("<b>Halaman ini menjawab:</b> berapa banyak pakan yang dipakai, berapa jatah per ekor, dan seberapa efisien pakan "
                 "diubah menjadi pertambahan bobot (FCR)?")
        p = muat("pakan_harian"); p["tanggal"] = pd.to_datetime(p.tanggal)
        fc = muat("pakan_fcr_bulanan")
        fc["periode"] = pd.to_datetime(dict(year=fc.tahun, month=fc.bulan, day=1))
        fcv = fc.dropna(subset=["fcr"])
        r = st.columns(4)
        r[0].metric("Total konsumsi pakan (ton)", f"{p.total_pakan_kg.sum() / 1000:.1f}",
                    help=f"Jumlah seluruh pakan yang tercatat selama {len(p)} hari")
        r[1].metric("Rata-rata pakan per hari (kg)", f"{p.total_pakan_kg.mean():.1f}", help="Total pakan seluruh kandang per hari")
        r[2].metric("Rata-rata pakan per ekor (kg/hari)", f"{p.pakan_per_ekor_kg.mean():.2f}", help="Total pakan harian dibagi jumlah kambing aktif")
        r[3].metric("FCR bulan terakhir", f"{fcv.fcr.iloc[-1]:.1f}" if len(fcv) else "-",
                    help="Kg pakan untuk 1 kg pertambahan bobot populasi. Makin kecil makin efisien.")
        st.subheader("Konsumsi pakan harian (seluruh kandang)")
        gambar(alt.Chart(p).mark_area(color="#1B6E5A", opacity=0.25, line={"color": "#1B6E5A", "strokeWidth": 1.4}).encode(
            x=alt.X("tanggal:T", title=None, axis=alt.Axis(format="%b %Y", labelAngle=0, tickCount=8)),
            y=alt.Y("total_pakan_kg:Q", title="Total pakan (kg/hari)"),
            tooltip=[alt.Tooltip("tanggal:T", title="Tanggal", format="%d %B %Y"), alt.Tooltip("total_pakan_kg:Q", title="Total pakan (kg)", format=".1f"),
                     alt.Tooltip("populasi_aktif:Q", title="Kambing aktif")]).properties(height=260))
        a, b = st.columns(2)
        with a:
            st.subheader("Pakan per ekor per hari (kg, berat segar)")
            gambar(alt.Chart(p).mark_line(color="#C77B0A", strokeWidth=1.4).encode(
                x=alt.X("tanggal:T", title=None, axis=alt.Axis(format="%b %Y", labelAngle=0, tickCount=6)),
                y=alt.Y("pakan_per_ekor_kg:Q", title="Pakan per ekor (kg/hari)", scale=alt.Scale(zero=False)),
                tooltip=[alt.Tooltip("tanggal:T", title="Tanggal", format="%d %B %Y"),
                         alt.Tooltip("pakan_per_ekor_kg:Q", title="Pakan per ekor (kg)", format=".2f")]).properties(height=280))
        with b:
            st.subheader("FCR populasi per bulan")
            gambar(grafik_garis(fcv, "periode", "fcr", "FCR", warna="#5B4B9A", fmt=".1f"))
        st.info("Catatan: pakan dicatat sebagai total seluruh kandang (berat segar, termasuk kambing dewasa), "
                "sehingga FCR hanya valid di tingkat populasi, tidak dapat dipecah per ras atau per segmen, "
                "dan nilainya tidak sebanding langsung dengan FCR literatur berbasis bahan kering.")

if "Validasi K" in tabs:
    with tabs["Validasi K"]:
        petunjuk("<b>Halaman ini menjawab:</b> mengapa kambing dibagi menjadi 4 segmen, bukan 3 atau 5? "
                 "K adalah <b>jumlah</b> klaster. Setiap nilai K dari 2 sampai 8 dicoba, lalu dipilih dengan dua ukuran di bawah.")
        st.subheader("Penentuan dan validasi jumlah klaster (K)")
        v = muat("validasi_k")
        v["k_terpilih"] = v.k_terpilih.astype(int)
        kp = int(v.loc[v.k_terpilih == 1, "k"].iloc[0])
        sil_k, sil_max = float(v.loc[v.k == kp, "silhouette"].iloc[0]), float(v.silhouette.max())
        k_max = int(v.loc[v.silhouette.idxmax(), "k"])
        r = st.columns(3)
        r[0].metric("K terpilih", kp, help="Jumlah klaster yang dipakai untuk segmentasi")
        r[1].metric(f"Silhouette pada K = {kp}", f"{sil_k:.4f}", help="Makin mendekati 1, makin jelas pemisahan antarklaster")
        r[2].metric("Dibanding Silhouette tertinggi", f"{sil_k / sil_max * 100:.1f}%", help=f"Silhouette tertinggi {sil_max:.4f} pada K = {k_max}")

        def kurva(kolom, judul, fmt, dx=16, dy=-14, rata="left"):
            dasar = alt.Chart(v).encode(x=alt.X("k:O", title="Jumlah klaster (K)", axis=alt.Axis(labelAngle=0)),
                                        y=alt.Y(f"{kolom}:Q", title=judul, scale=alt.Scale(zero=False)),
                                        tooltip=[alt.Tooltip("k:O", title="K"), alt.Tooltip(f"{kolom}:Q", title=judul, format=fmt)])
            pilih_ = alt.Chart(v[v.k == kp]).encode(x="k:O", y=f"{kolom}:Q")
            return (dasar.mark_line(color="#1B6E5A", strokeWidth=2) + dasar.mark_circle(color="#1B6E5A", size=45)
                    + pilih_.mark_point(color="#C62828", size=320, strokeWidth=2.4, filled=False)
                    + pilih_.mark_text(dy=dy, dx=dx, align=rata, color="#C62828", fontWeight="bold").encode(text=alt.value(f"K = {kp} dipilih"))).properties(height=300)
        x, y = st.columns(2)
        with x:
            st.markdown("**Elbow: WCSS (inertia)**")
            st.caption("WCSS selalu turun saat K bertambah. Dicari titik siku, yaitu saat penurunannya mulai landai.")
            gambar(kurva("inertia_wcss", "WCSS", ".1f"))
        with y:
            st.markdown("**Silhouette score**")
            st.caption("Mengukur seberapa jelas klaster terpisah. Makin mendekati 1 makin baik.")
            gambar(kurva("silhouette", "Silhouette", ".4f", dx=0, dy=24, rata="center"))
        st.caption(f"Aturan: K kandidat = titik siku kurva WCSS, dipakai bila Silhouette-nya minimal 97% dari Silhouette "
                   f"tertinggi. Silhouette K={kp} = {sil_k:.4f} ({sil_k / sil_max * 100:.1f}% dari tertinggi {sil_max:.4f} "
                   f"pada K={k_max}).")
        with st.expander("Lihat tabel angka"):
            st.dataframe(v.rename(columns={"k": "K", "inertia_wcss": "WCSS (inertia)", "silhouette": "Silhouette",
                                           "k_terpilih": "Terpilih (1 = ya)"}).round(4), hide_index=True)


# ---------------- Import Data (hanya Manajer Operasional) ----------------
@st.cache_resource
def kunci_impor():
    return threading.Lock()          # hanya satu proses import dalam satu waktu


if "Import Data" in tabs:
    with tabs["Import Data"]:
        petunjuk("<b>Halaman ini menjawab:</b> bagaimana memperbarui dashboard dengan data terbaru? "
                 "Unggah berkas Excel terbaru, lalu sistem menghitung ulang K-Means, memuat Data Warehouse, "
                 "dan memeriksa kecocokannya secara otomatis, tanpa perintah PowerShell.")
        hasil_lalu = st.session_state.pop("hasil_impor", None)
        if hasil_lalu:
            st.success(f"Import berhasil. Seluruh halaman kini memakai data baru (K = {hasil_lalu['k']['k']}, "
                       f"rekonsiliasi {sum(c[1] == 'LULUS' for c in hasil_lalu['rekonsiliasi'])}/{len(hasil_lalu['rekonsiliasi'])} lulus). "
                       f"Salinan berkas disimpan di {hasil_lalu['arsip']}.")
            if hasil_lalu.get("k_lama") and hasil_lalu["k_lama"] != hasil_lalu["k"]["k"]:
                st.warning(f"Jumlah klaster berubah dari K = {hasil_lalu['k_lama']} menjadi K = {hasil_lalu['k']['k']} "
                           "menurut aturan Elbow + Silhouette. Periksa halaman Validasi K dan Segmentasi.")
            with st.expander("Lihat hasil rekonsiliasi"):
                st.dataframe(pd.DataFrame(hasil_lalu["rekonsiliasi"], columns=["Pemeriksaan", "Hasil", "Detail"]), hide_index=True)

        sekarang = impor.ringkasan_dw(koneksi())
        st.subheader("Data saat ini")
        r = st.columns(4)
        r[0].metric("Kambing tercatat", sekarang.get("kambing", "-"))
        r[1].metric("Data penimbangan", f"{sekarang.get('penimbangan', 0):,}".replace(",", "."))
        r[2].metric("Hari data pakan", f"{sekarang.get('hari_pakan', 0):,}".replace(",", "."))
        r[3].metric("Data sampai", f"{sekarang['akhir']:%d-%m-%Y}" if sekarang.get("akhir") is not None else "-")

        st.subheader("Unggah berkas Excel terbaru")
        with st.expander("Format berkas yang diterima", expanded=False):
            st.markdown("Unggah **berkas lengkap** (seluruh data sejak awal pencatatan, ditambah data terbaru), bukan hanya "
                        "baris baru, karena seluruh isi Data Warehouse dibangun ulang dari berkas ini. Nama sheet dan kolom "
                        "harus sama dengan berkas `Data_Ternak_2022-2026.xlsx`:")
            st.dataframe(pd.DataFrame([{"Sheet": impor.SHEET[k], "Kolom wajib": ", ".join(v)} for k, v in impor.KOLOM.items()]),
                         hide_index=True)
            st.caption("Nilai yang diterima: ras Boer, Etawa, atau PE; jenis kelamin Jantan atau Betina; status Hidup, Terjual, "
                       "atau Mati. Kambing berstatus Terjual atau Mati wajib memiliki tanggal_keluar.")
        # Server Streamlit Community Cloud menaruh program di /mount/src; di sana berkas SQLite tidak tersimpan permanen
        if str(DB_URL).startswith("sqlite:///") and os.path.abspath(__file__).startswith("/mount/src"):
            st.info("Database saat ini berupa berkas SQLite. Bila dashboard dijalankan di Streamlit Community Cloud, hasil import "
                    "tidak tersimpan permanen (kembali ke data lama saat aplikasi dimulai ulang). Gunakan database MySQL atau "
                    "TiDB Cloud untuk versi daring (lihat PANDUAN_DEPLOY.md).")

        kunci_unggah = st.session_state.setdefault("kunci_unggah", 0)
        berkas = st.file_uploader("Pilih berkas Excel (.xlsx)", type=["xlsx"], key=f"unggah_{kunci_unggah}")
        if berkas is not None:
            data_berkas = berkas.getvalue()
            tanda = (berkas.name, len(data_berkas))
            if st.session_state.get("periksa_tanda") != tanda:      # periksa sekali per berkas
                with st.spinner("Memeriksa berkas..."):
                    st.session_state["periksa_hasil"] = impor.periksa_excel(io.BytesIO(data_berkas))[:3]
                st.session_state["periksa_tanda"] = tanda
            salah, awas, baru = st.session_state["periksa_hasil"]

            if salah:
                st.error("Berkas belum dapat diproses. Perbaiki hal berikut di Excel, lalu unggah ulang. Data saat ini tidak berubah.")
                for m in salah:
                    st.markdown(f"- {m}")
            else:
                st.success("Berkas lolos pemeriksaan format.")
                for m in awas:
                    st.warning(m)
                banding = []
                for label, kunci in [("Kambing tercatat", "kambing"), ("Kambing hidup", "hidup"),
                                     ("Data penimbangan", "penimbangan"), ("Hari data pakan", "hari_pakan")]:
                    lama = sekarang.get(kunci)
                    banding.append({"Data": label, "Saat ini": lama if lama is not None else "-", "Berkas baru": baru[kunci],
                                    "Perubahan": (f"{baru[kunci] - lama:+d}" if lama is not None else "-")})
                banding.append({"Data": "Data sampai", "Saat ini": f"{sekarang['akhir']:%d-%m-%Y}" if sekarang.get("akhir") is not None else "-",
                                "Berkas baru": f"{baru['akhir']:%d-%m-%Y}", "Perubahan": ""})
                st.markdown("**Perbandingan sebelum diproses**")
                st.dataframe(pd.DataFrame(banding).astype(str), hide_index=True)

                berkurang = [b["Data"] for b in banding[:4] if sekarang.get("kambing") is not None and b["Perubahan"].startswith("-")]
                yakin = True
                if berkurang:
                    st.warning("Jumlah data pada berkas baru lebih sedikit daripada data saat ini (" + ", ".join(berkurang).lower()
                               + "). Pastikan berkas yang diunggah adalah berkas lengkap, bukan hanya data terbaru.")
                    yakin = st.checkbox("Saya yakin berkas ini lengkap dan benar")

                with st.expander("Pengaturan lanjutan: jumlah klaster (K)"):
                    pilih_k = st.radio("Jumlah klaster", ["Otomatis (aturan Elbow + Silhouette, disarankan)", "Tetapkan sendiri"],
                                       help="Otomatis: K dipilih ulang dengan aturan yang sama seperti pada penelitian.")
                    k_tetap = None
                    if pilih_k == "Tetapkan sendiri":
                        k_tetap = int(st.number_input("K", min_value=2, max_value=8, value=4, step=1))

                if st.button("Proses import", type="primary", disabled=not yakin):
                    kunci = kunci_impor()
                    if not kunci.acquire(blocking=False):
                        st.warning("Import lain sedang berjalan. Tunggu sampai selesai, lalu coba lagi.")
                    else:
                        try:
                            k_lama = None
                            try:
                                v_lama = q.validasi_k(koneksi())
                                k_lama = int(v_lama.loc[v_lama.k_terpilih.astype(int) == 1, "k"].iloc[0])
                            except Exception:
                                pass
                            batang = st.progress(0.0, text="Memulai...")
                            hasil = impor.proses_impor(data_berkas, koneksi(), folder_program=os.path.dirname(os.path.abspath(__file__)),
                                                       nama_asli=berkas.name, k=k_tetap,
                                                       lapor=lambda teks, nilai: batang.progress(nilai, text=teks))
                        finally:
                            kunci.release()
                        st.cache_data.clear()
                        if hasil["berhasil"]:
                            hasil["k_lama"] = k_lama
                            st.session_state["hasil_impor"] = hasil
                            st.session_state["kunci_unggah"] = kunci_unggah + 1      # kosongkan kotak unggah
                            st.session_state.pop("periksa_tanda", None)
                            st.rerun()
                        else:
                            st.error(hasil["pesan"])
                            if hasil["rekonsiliasi"]:
                                st.dataframe(pd.DataFrame(hasil["rekonsiliasi"], columns=["Pemeriksaan", "Hasil", "Detail"]),
                                             hide_index=True)
