
from __future__ import annotations

import tempfile
from pathlib import Path
import pandas as pd
import streamlit as st

from billing import compare_double_vario
from groupe_e_api import fetch_vario
from meter_loader import load_consumption_file
from battery_sim import simulate_double_battery, simulate_vario_battery

st.set_page_config(page_title="Soleol — Double vs VARIO + batterie", layout="wide")

VARIO_HISTORY_START = pd.Timestamp("2025-12-11 00:00:00")
MONTHS_FR = {
    1:"Janvier",2:"Février",3:"Mars",4:"Avril",5:"Mai",6:"Juin",
    7:"Juillet",8:"Août",9:"Septembre",10:"Octobre",11:"Novembre",12:"Décembre"
}

st.title("Analyse tarifaire Groupe E")
st.caption("Comparaison Double / VARIO et potentiel supplémentaire d'une batterie.")

with st.sidebar:
    st.header("1. Client")
    client = st.text_input("Client / site", value="")
    uploaded = st.file_uploader("Courbe import / export réseau", type=["xlsx","xls","csv"])
    transpose_to_2026 = st.toggle(
        "Utiliser un profil 2025 comme profil 2026",
        value=True,
        help="Les valeurs sont conservées ; seule l'année est transposée en 2026."
    )

    st.header("2. Tarif Double")
    ht_ct = st.number_input("Haut tarif (ct/kWh)", min_value=0.0, value=29.32, step=0.01)
    bt_ct = st.number_input("Bas tarif (ct/kWh)", min_value=0.0, value=19.27, step=0.01)
    st.caption("HT : 07h–12h et 17h–23h. BT : le reste.")

    st.header("3. Batterie")
    capacity = st.number_input("Capacité batterie (kWh)", min_value=1.0, value=10.0, step=1.0)
    power = st.number_input("Puissance batterie (kW)", min_value=0.5, value=5.0, step=0.5)
    efficiency = st.slider("Rendement aller-retour", 0.50, 1.00, 0.92, 0.01)
    feed_in_ct = st.number_input("Reprise PV / injection (ct/kWh)", min_value=0.0, value=6.0, step=0.1)

    with st.expander("Options avancées"):
        unit = st.selectbox("Forcer l'unité", ["auto","kW","kWh","W","Wh"], index=0)

if uploaded is None:
    st.info("Importe une courbe de charge Groupe E pour commencer.")
    st.stop()

@st.cache_data(show_spinner=False)
def load_cached(name, raw, unit):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)/name
        p.write_bytes(raw)
        return load_consumption_file(p, forced_unit=unit)

try:
    df, meta = load_cached(uploaded.name, uploaded.getvalue(), unit)
except Exception as exc:
    st.error(f"Fichier non reconnu : {exc}")
    st.stop()

original_start = df["timestamp"].min()
original_end = df["timestamp"].max()
profile_transposed = False
if transpose_to_2026 and original_start.year == 2025:
    df = df.copy()
    df["timestamp"] = df["timestamp"].map(lambda x: x.replace(year=2026))
    profile_transposed = True

st.success(
    f"Fichier reconnu : {meta.vendor} · {meta.n_rows:,} mesures · "
    f"pas {meta.dt_hours*60:.0f} min · unité {meta.input_unit}"
)

if profile_transposed:
    st.warning(
        "MODE SIMULATION — Profil 2025 transposé sur 2026. "
        "Les prix VARIO utilisés sont les prix réels 2026 disponibles."
    )

with st.expander("Détails de détection"):
    st.write(f"Date/heure : **{meta.date_column}**")
    st.write(f"Import : **{meta.import_column}**")
    st.write(f"Export : **{meta.export_column}**")
    st.write(f"Import total : **{df.import_kWh.sum():,.0f} kWh**".replace(","," "))
    st.write(f"Export total : **{df.export_kWh.sum():,.0f} kWh**".replace(","," "))
    if profile_transposed:
        st.write(f"Période originale : {original_start:%d.%m.%Y} → {original_end:%d.%m.%Y}")
        st.write(f"Période simulée : {df.timestamp.min():%d.%m.%Y} → {df.timestamp.max():%d.%m.%Y}")

if st.button("Analyser les 4 scénarios", type="primary"):
    today = pd.Timestamp.now(tz="Europe/Zurich").tz_localize(None)
    start = max(VARIO_HISTORY_START, df.timestamp.min().floor("15min"))
    end = min(today.ceil("15min"), df.timestamp.max().ceil("15min")+pd.Timedelta(minutes=15))

    with st.spinner("Récupération des prix VARIO..."):
        try:
            vario, publication = fetch_vario(start, end)
        except Exception as exc:
            st.error(f"API Groupe E : {exc}")
            st.stop()

    data = df.copy()
    data["timestamp"] = data["timestamp"].dt.floor("15min")
    merged = data.merge(vario, on="timestamp", how="inner")
    if merged.empty:
        st.error("Aucune période commune entre le profil et VARIO.")
        st.stop()

    # Baseline Double/VARIO import comparison.
    base, base_r = compare_double_vario(
        merged,
        ht_chf_kwh=ht_ct/100,
        bt_chf_kwh=bt_ct/100,
        periods=((7,12),(17,23)),
        weekend_low=False,
        vat_factor=1.0,
    )

    # Include export revenue for all four energy-bill scenarios.
    feed_in = feed_in_ct/100
    export_revenue_before = float((merged["export_kWh"] * feed_in).sum())
    double_net = base_r["double_chf"] - export_revenue_before
    vario_net = base_r["vario_chf"] - export_revenue_before

    dbl_bat = simulate_double_battery(
        merged, ht_ct/100, bt_ct/100, feed_in,
        capacity, power, meta.dt_hours, efficiency
    )
    var_bat = simulate_vario_battery(
        merged, feed_in, capacity, power, meta.dt_hours, efficiency
    )

    st.subheader("Comparaison des 4 scénarios")
    a,b,c,d = st.columns(4)
    a.metric("1. Double", f"{double_net:,.2f} CHF".replace(","," "))
    b.metric("2. VARIO", f"{vario_net:,.2f} CHF".replace(","," "),
             f"{double_net-vario_net:+.2f} CHF vs Double")
    c.metric("3. Double + batterie", f"{dbl_bat.cost_chf:,.2f} CHF".replace(","," "),
             f"{double_net-dbl_bat.cost_chf:+.2f} CHF")
    d.metric("4. VARIO + batterie", f"{var_bat.cost_chf:,.2f} CHF".replace(","," "),
             f"{double_net-var_bat.cost_chf:+.2f} CHF vs Double")

    best_gain = double_net - var_bat.cost_chf
    st.success(
        f"Avec une batterie de **{capacity:.0f} kWh / {power:.1f} kW**, "
        f"le scénario VARIO piloté selon les prix économise **{best_gain:,.2f} CHF** "
        f"par rapport au tarif Double sans batterie sur la période analysée.".replace(","," ")
    )

    e1,e2,e3,e4 = st.columns(4)
    e1.metric("Surplus disponible", f"{merged.export_kWh.sum():,.0f} kWh".replace(","," "))
    e2.metric("PV stocké — VARIO", f"{var_bat.charge_kwh.sum():,.0f} kWh".replace(","," "))
    e3.metric("Restitué — VARIO", f"{var_bat.discharge_kwh.sum():,.0f} kWh".replace(","," "))
    e4.metric("Cycles équivalents", f"{var_bat.cycles:.0f}")

    st.caption(
        "Stratégie VARIO batterie : le surplus PV est stocké en priorité puis la batterie "
        "est déchargée pendant les quarts d'heure situés dans les 25 % de prix les plus élevés "
        "des prochaines 24 heures. La charge depuis le réseau n'est pas autorisée dans cette version."
    )

    # Build per-interval costs for all four scenarios.
    m = base.copy()
    m["export_before_kWh"] = merged["export_kWh"].values
    m["double_net"] = m["double_cost_chf"] - m["export_before_kWh"]*feed_in
    m["vario_net"] = m["vario_cost_chf"] - m["export_before_kWh"]*feed_in

    # Recompute interval double prices for battery cost display.
    idx = pd.DatetimeIndex(m["timestamp"])
    hh = idx.hour + idx.minute/60
    dbl_price = pd.Series(
        ((hh>=7)&(hh<12) | (hh>=17)&(hh<23)),
        index=m.index
    ).map({True:ht_ct/100, False:bt_ct/100}).astype(float).values

    m["double_battery"] = dbl_bat.import_after*dbl_price - dbl_bat.export_after*feed_in
    m["vario_battery"] = var_bat.import_after*m["vario_chf_kwh"].values - var_bat.export_after*feed_in

    monthly = m.set_index("timestamp")[["double_net","vario_net","double_battery","vario_battery"]].resample("MS").sum()
    monthly["Mois"] = [MONTHS_FR[x.month] for x in monthly.index]
    chart = monthly.set_index("Mois").rename(columns={
        "double_net":"Double",
        "vario_net":"VARIO",
        "double_battery":"Double + batterie",
        "vario_battery":"VARIO + batterie",
    })

    st.subheader("Coût mois par mois")
    st.bar_chart(chart)

    savings = pd.DataFrame(index=monthly.index)
    savings["VARIO seul"] = monthly["double_net"] - monthly["vario_net"]
    savings["Double + batterie"] = monthly["double_net"] - monthly["double_battery"]
    savings["VARIO + batterie"] = monthly["double_net"] - monthly["vario_battery"]
    savings["Mois"] = [MONTHS_FR[x.month] for x in savings.index]
    st.subheader("Économie par mois vs Double")
    st.bar_chart(savings.set_index("Mois"))

    display = chart.copy()
    display["Gain VARIO vs Double"] = display["Double"] - display["VARIO"]
    display["Gain batterie Double"] = display["Double"] - display["Double + batterie"]
    display["Gain VARIO + batterie"] = display["Double"] - display["VARIO + batterie"]
    st.subheader("Détail mensuel")
    st.dataframe(display.round(2), use_container_width=True)

    with st.expander("Contrôle stratégie batterie VARIO"):
        detail = pd.DataFrame({
            "timestamp": merged["timestamp"],
            "import_avant_kWh": merged["import_kWh"],
            "export_avant_kWh": merged["export_kWh"],
            "prix_VARIO_ct_kWh": merged["vario_chf_kwh"]*100,
            "charge_batterie_kWh": var_bat.charge_kwh,
            "decharge_batterie_kWh": var_bat.discharge_kwh,
            "SOC_kWh": var_bat.soc_kwh,
            "import_apres_kWh": var_bat.import_after,
            "export_apres_kWh": var_bat.export_after,
        })
        st.dataframe(detail, use_container_width=True, height=420, hide_index=True)
