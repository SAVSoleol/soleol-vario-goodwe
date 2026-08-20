
from __future__ import annotations

import tempfile
from pathlib import Path
import pandas as pd
import streamlit as st

from billing import compare_double_vario
from groupe_e_api import fetch_vario
from meter_loader import load_consumption_file
from battery_opt import optimize_battery, double_price_vector

st.set_page_config(page_title="Soleol — Double vs VARIO + batterie", layout="wide")

VARIO_HISTORY_START = pd.Timestamp("2025-12-11 00:00:00")
MONTHS_FR = {
    1:"Janvier",2:"Février",3:"Mars",4:"Avril",5:"Mai",6:"Juin",
    7:"Juillet",8:"Août",9:"Septembre",10:"Octobre",11:"Novembre",12:"Décembre"
}

st.title("Analyse tarifaire Groupe E")
st.caption("Double / VARIO et optimisation économique d'une batterie sur le profil client.")

with st.sidebar:
    st.header("1. Client")
    client = st.text_input("Client / site", value="")
    uploaded = st.file_uploader("Courbe import / export réseau", type=["xlsx","xls","csv"])
    transpose_to_2026 = st.toggle("Utiliser un profil 2025 comme profil 2026", value=True)

    st.header("2. Tarif Double")
    ht_ct = st.number_input("Haut tarif (ct/kWh)", min_value=0.0, value=29.32, step=0.01)
    bt_ct = st.number_input("Bas tarif (ct/kWh)", min_value=0.0, value=19.27, step=0.01)
    st.caption("HT : 07h–12h et 17h–23h. BT : le reste.")

    st.header("3. Batterie")
    capacity = st.number_input("Capacité batterie (kWh)", min_value=1.0, value=10.0, step=1.0)
    power = st.number_input("Puissance batterie (kW)", min_value=0.5, value=5.0, step=0.5)
    efficiency = st.slider("Rendement aller-retour", 0.50, 1.00, 0.92, 0.01)
    soc_min = st.slider("SOC minimum (%)", 0, 50, 5)
    soc_max = st.slider("SOC maximum (%)", 50, 100, 95)
    feed_in_ct = st.number_input("Reprise PV / injection (ct/kWh)", min_value=0.0, value=6.0, step=0.1)
    allow_grid_charge = st.toggle(
        "Autoriser arbitrage réseau avec VARIO",
        value=False,
        help="Permet de charger la batterie depuis le réseau lorsque VARIO est bas et de la décharger lorsque VARIO est élevé.",
    )

    with st.expander("Options avancées"):
        unit = st.selectbox("Forcer l'unité", ["auto","kW","kWh","W","Wh"], index=0)

if uploaded is None:
    st.info("Importe une courbe Groupe E pour commencer.")
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

original_start = df.timestamp.min()
original_end = df.timestamp.max()
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
    st.warning("MODE SIMULATION — Profil 2025 transposé sur 2026 ; prix VARIO réels 2026.")

with st.expander("Détails de détection"):
    st.write(f"Import : **{meta.import_column}**")
    st.write(f"Export : **{meta.export_column}**")
    st.write(f"Import total : **{df.import_kWh.sum():,.0f} kWh**".replace(","," "))
    st.write(f"Export total : **{df.export_kWh.sum():,.0f} kWh**".replace(","," "))

if st.button("Optimiser et comparer", type="primary"):
    if soc_max <= soc_min:
        st.error("SOC maximum doit être supérieur au SOC minimum.")
        st.stop()

    today = pd.Timestamp.now(tz="Europe/Zurich").tz_localize(None)
    start = max(VARIO_HISTORY_START, df.timestamp.min().floor("15min"))
    end = min(today.ceil("15min"), df.timestamp.max().ceil("15min")+pd.Timedelta(minutes=15))

    with st.spinner("Récupération VARIO..."):
        try:
            vario, publication = fetch_vario(start, end)
        except Exception as exc:
            st.error(f"API Groupe E : {exc}")
            st.stop()

    data = df.copy()
    data["timestamp"] = data["timestamp"].dt.floor("15min")
    merged = data.merge(vario, on="timestamp", how="inner")
    if merged.empty:
        st.error("Aucune période commune.")
        st.stop()

    base, r = compare_double_vario(
        merged,
        ht_chf_kwh=ht_ct/100,
        bt_chf_kwh=bt_ct/100,
        periods=((7,12),(17,23)),
        weekend_low=False,
        vat_factor=1.0,
    )

    feed_in = feed_in_ct/100
    export_revenue = float(merged.export_kWh.sum() * feed_in)
    double_cost = r["double_chf"] - export_revenue
    vario_cost = r["vario_chf"] - export_revenue

    double_prices = double_price_vector(merged.timestamp, ht_ct/100, bt_ct/100)

    with st.spinner("Optimisation économique de la batterie..."):
        try:
            double_bat = optimize_battery(
                merged, double_prices, feed_in, capacity, power, meta.dt_hours,
                efficiency, soc_min, soc_max, allow_grid_charge=False
            )
            vario_pv = optimize_battery(
                merged, merged.vario_chf_kwh.values, feed_in, capacity, power, meta.dt_hours,
                efficiency, soc_min, soc_max, allow_grid_charge=False
            )
            vario_grid = None
            if allow_grid_charge:
                vario_grid = optimize_battery(
                    merged, merged.vario_chf_kwh.values, feed_in, capacity, power, meta.dt_hours,
                    efficiency, soc_min, soc_max, allow_grid_charge=True
                )
        except Exception as exc:
            st.error(str(exc))
            st.stop()

    period_days = len(merged) * meta.dt_hours / 24.0
    annual_factor = 365.0 / period_days if period_days > 0 else 0.0

    st.subheader("Coût sur la période analysée")
    cols = st.columns(5 if allow_grid_charge else 4)
    cols[0].metric("1. Double", f"{double_cost:,.2f} CHF".replace(","," "))
    cols[1].metric("2. VARIO", f"{vario_cost:,.2f} CHF".replace(","," "),
                   f"{double_cost-vario_cost:+.2f} CHF")
    cols[2].metric("3. Double + batterie", f"{double_bat.cost_chf:,.2f} CHF".replace(","," "),
                   f"{double_cost-double_bat.cost_chf:+.2f} CHF")
    cols[3].metric("4. VARIO + batterie PV", f"{vario_pv.cost_chf:,.2f} CHF".replace(","," "),
                   f"{double_cost-vario_pv.cost_chf:+.2f} CHF")
    if allow_grid_charge:
        cols[4].metric("5. VARIO + arbitrage", f"{vario_grid.cost_chf:,.2f} CHF".replace(","," "),
                       f"{double_cost-vario_grid.cost_chf:+.2f} CHF")

    best = vario_grid if allow_grid_charge else vario_pv
    gain_period = double_cost - best.cost_chf
    gain_battery_vs_vario = vario_cost - best.cost_chf

    st.success(
        f"**Gain du meilleur scénario VARIO + batterie sur la période : "
        f"{gain_period:,.2f} CHF vs Double**, dont {gain_battery_vs_vario:,.2f} CHF "
        f"apportés par la batterie par rapport à VARIO seul.".replace(","," ")
    )

    st.subheader("Lecture annuelle")
    a,b,c,d = st.columns(4)
    a.metric("Période analysée", f"{period_days:.0f} jours")
    b.metric("Gain période", f"{gain_period:,.0f} CHF".replace(","," "))
    c.metric("Projection annuelle indicative", f"{gain_period*annual_factor:,.0f} CHF/an".replace(","," "))
    d.metric("Cycles annualisés", f"{best.cycles*annual_factor:.0f}/an")
    st.caption(
        "La projection annuelle est une simple annualisation de la période observée. "
        "Elle n'est pas une garantie et devient plus fiable à mesure que l'historique VARIO couvre une année complète."
    )

    k1,k2,k3,k4 = st.columns(4)
    k1.metric("Surplus disponible", f"{merged.export_kWh.sum():,.0f} kWh".replace(","," "))
    k2.metric("Énergie chargée", f"{best.charged_kwh:,.0f} kWh".replace(","," "))
    k3.metric("Énergie restituée", f"{best.discharged_kwh:,.0f} kWh".replace(","," "))
    k4.metric("Cycles sur période", f"{best.cycles:.0f}")

    # Build interval cost series.
    m = merged[["timestamp","import_kWh","export_kWh","vario_chf_kwh"]].copy()
    m["double"] = merged.import_kWh.values*double_prices - merged.export_kWh.values*feed_in
    m["vario"] = merged.import_kWh.values*merged.vario_chf_kwh.values - merged.export_kWh.values*feed_in
    m["double_bat"] = double_bat.import_after*double_prices - double_bat.export_after*feed_in
    m["vario_pv"] = vario_pv.import_after*merged.vario_chf_kwh.values - vario_pv.export_after*feed_in
    if allow_grid_charge:
        m["vario_grid"] = vario_grid.import_after*merged.vario_chf_kwh.values - vario_grid.export_after*feed_in

    cols_month = ["double","vario","double_bat","vario_pv"] + (["vario_grid"] if allow_grid_charge else [])
    monthly = m.set_index("timestamp")[cols_month].resample("MS").sum()
    monthly["Mois"] = [MONTHS_FR[x.month] for x in monthly.index]

    rename = {
        "double":"Double",
        "vario":"VARIO",
        "double_bat":"Double + batterie",
        "vario_pv":"VARIO + batterie PV",
        "vario_grid":"VARIO + arbitrage",
    }

    st.subheader("Coût mois par mois")
    st.bar_chart(monthly.set_index("Mois")[cols_month].rename(columns=rename))

    saving = pd.DataFrame(index=monthly.index)
    saving["VARIO seul"] = monthly["double"] - monthly["vario"]
    saving["Double + batterie"] = monthly["double"] - monthly["double_bat"]
    saving["VARIO + batterie PV"] = monthly["double"] - monthly["vario_pv"]
    if allow_grid_charge:
        saving["VARIO + arbitrage"] = monthly["double"] - monthly["vario_grid"]
    saving["Mois"] = [MONTHS_FR[x.month] for x in saving.index]

    st.subheader("Économie par mois par rapport au Double")
    st.bar_chart(saving.set_index("Mois"))

    with st.expander("Voir le pilotage optimisé VARIO"):
        chosen = best
        detail = pd.DataFrame({
            "timestamp": merged.timestamp,
            "prix_VARIO_ct_kWh": merged.vario_chf_kwh*100,
            "import_avant_kWh": merged.import_kWh,
            "export_avant_kWh": merged.export_kWh,
            "charge_kWh": chosen.charge_kwh,
            "decharge_kWh": chosen.discharge_kwh,
            "SOC_kWh": chosen.soc_kwh,
            "import_apres_kWh": chosen.import_after,
            "export_apres_kWh": chosen.export_after,
        })
        st.dataframe(detail, use_container_width=True, height=430, hide_index=True)

    st.caption(
        "L'optimiseur connaît ici les prix historiques de toute la période : il calcule donc un backtest économique optimal. "
        "Pour un pilotage réel, il faudrait limiter la prévision aux prix publiés à l'avance par Groupe E."
    )
