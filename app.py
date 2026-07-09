from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from goodwe_api import GoodWeClient, GoodWeConfig
from groupe_e import fetch_vario_tariffs, slots_to_rows
from optimizer import StrategyResult, build_strategy, window_to_goodwe_data

load_dotenv()

st.set_page_config(page_title="Soleol EMS VARIO", layout="wide")
st.title("Soleol EMS — Groupe E VARIO → GoodWe EzManager")

with st.sidebar:
    st.header("Installation")
    site_name = st.text_input("Nom du site", value="Site test")
    objective = st.selectbox("Objectif", ["Économies maximales", "Autoconsommation", "Backup prioritaire"], index=0)

    st.header("Batterie")
    battery_capacity_kwh = st.number_input("Capacité batterie (kWh)", min_value=1.0, value=50.0, step=1.0)
    charge_power_kw = st.number_input("Puissance charge max (kW)", min_value=0.1, value=20.0, step=1.0)
    discharge_power_kw = st.number_input("Puissance décharge max (kW)", min_value=0.1, value=20.0, step=1.0)
    soc_start = st.slider("SOC actuel ou estimé (%)", 0, 100, 50)
    soc_min = st.slider("SOC minimum de sécurité (%)", 0, 100, 20)
    charge_target_soc = st.slider("SOC cible après charge (%)", 0, 100, 95)
    discharge_target_soc = st.slider("SOC cible après décharge (%)", 0, 100, 20)
    roundtrip_efficiency = st.slider("Rendement aller-retour (%)", 70, 100, 90) / 100
    price_field = st.selectbox("Prix utilisé", ["integrated_chf_kwh", "grid_chf_kwh"], index=0)

    st.header("GoodWe")
    device_sn = st.text_input("SN batterie/onduleur")
    datalogger_sn = st.text_input("SN EzManager / datalogger")
    dry_run = st.toggle("Mode test : ne rien envoyer", value=True)

col_a, col_b, col_c = st.columns(3)
if col_a.button("Récupérer tarifs VARIO", type="primary"):
    with st.spinner("Récupération des 96 prix Groupe E..."):
        publication_timestamp, slots, payload = fetch_vario_tariffs()
        st.session_state["publication_timestamp"] = publication_timestamp
        st.session_state["slots"] = slots
        st.session_state["raw_payload"] = payload

slots = st.session_state.get("slots", [])
publication_timestamp = st.session_state.get("publication_timestamp", "")

if not slots:
    st.info("Commence par récupérer les tarifs VARIO.")
    st.stop()

result: StrategyResult = build_strategy(
    slots,
    battery_capacity_kwh=battery_capacity_kwh,
    charge_power_kw=charge_power_kw,
    discharge_power_kw=discharge_power_kw,
    soc_start=soc_start,
    soc_min=soc_min,
    charge_target_soc=charge_target_soc,
    discharge_target_soc=discharge_target_soc,
    price_field=price_field,
    roundtrip_efficiency=roundtrip_efficiency,
)

st.success(f"{len(slots)} prix récupérés — publication : {publication_timestamp}")

k1, k2, k3, k4 = st.columns(4)
k1.metric("Prix min", f"{min(getattr(s, price_field) for s in slots):.4f} CHF/kWh")
k2.metric("Prix max", f"{max(getattr(s, price_field) for s in slots):.4f} CHF/kWh")
k3.metric("Énergie chargée", f"{result.charged_energy_kwh:.1f} kWh")
k4.metric("Gain arbitrage estimé", f"{result.estimated_arbitrage_gain_chf:.2f} CHF/j")

st.subheader("1. Courbe tarifaire et stratégie")
price_df = pd.DataFrame(slots_to_rows(slots))
price_df["time"] = pd.to_datetime(price_df["start"])
price_df = price_df.set_index("time")
st.line_chart(price_df[[price_field]], height=280)

strategy_rows = []
for w in result.windows:
    strategy_rows.append(
        {
            "action": w.action,
            "début": w.start.strftime("%d.%m.%Y %H:%M"),
            "fin": w.end.strftime("%d.%m.%Y %H:%M"),
            "puissance_kW": w.power_w / 1000,
            "SOC cible": w.target_soc,
            "prix moyen": round(w.avg_price_chf_kwh, 4),
            "énergie_kWh": w.energy_kwh,
        }
    )

st.subheader("2. Planning proposé")
st.dataframe(pd.DataFrame(strategy_rows), use_container_width=True, hide_index=True)

st.subheader("3. Données détaillées")
with st.expander("Afficher les 96 prix"):
    st.dataframe(pd.DataFrame(slots_to_rows(slots)), use_container_width=True, height=320)

with st.expander("Payload GoodWe prévu"):
    for w in result.windows:
        st.json({"functionName": "BatteryCD", "items": [{"sn": device_sn or "DEVICE_SN", "data": window_to_goodwe_data(w)}]})

st.subheader("4. Envoi GoodWe")
if dry_run:
    st.warning("Mode test actif : aucun ordre ne sera envoyé à GoodWe.")
else:
    st.info("Mode réel actif : le bouton ci-dessous enverra les consignes à GoodWe.")

can_send = bool(device_sn) and not dry_run and bool(result.windows)
if st.button("Envoyer la stratégie à GoodWe", type="primary", disabled=not can_send):
    client = GoodWeClient(
        GoodWeConfig(
            base_url=os.getenv("GOODWE_BASE_URL", "https://openapi.goodwe.com"),
            authorization=os.getenv("GOODWE_AUTHORIZATION", ""),
            app_identifier=os.getenv("GOODWE_APP_IDENTIFIER", ""),
        )
    )
    if datalogger_sn:
        st.write("Activation du mode Third-party dispatch sur l'EzManager...")
        st.json(client.set_ems_third_party_dispatch(datalogger_sn))
    st.write("Envoi des fenêtres BatteryCD...")
    st.json(client.send_battery_windows(device_sn, result.windows))

st.caption(f"Site : {site_name} — Objectif : {objective} — Dernier calcul : {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
