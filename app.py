from __future__ import annotations

import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from goodwe_api import GoodWeClient, GoodWeConfig
from groupe_e import fetch_vario_tariffs, slots_to_rows
from optimizer import build_simple_strategy, window_to_goodwe_data

load_dotenv()

st.set_page_config(page_title="Soleol VARIO → GoodWe", layout="wide")
st.title("Soleol VARIO → GoodWe EzManager")

with st.sidebar:
    st.header("Paramètres batterie")
    battery_capacity_kwh = st.number_input("Capacité batterie (kWh)", min_value=1.0, value=50.0, step=1.0)
    charge_power_kw = st.number_input("Puissance charge (kW)", min_value=0.1, value=20.0, step=1.0)
    discharge_power_kw = st.number_input("Puissance décharge (kW)", min_value=0.1, value=20.0, step=1.0)
    soc_start = st.slider("SOC estimé au départ (%)", 0, 100, 50)
    soc_min = st.slider("SOC minimum (%)", 0, 100, 20)
    charge_target_soc = st.slider("SOC cible charge (%)", 0, 100, 95)
    discharge_target_soc = st.slider("SOC cible décharge (%)", 0, 100, 20)
    price_field = st.selectbox("Prix utilisé", ["integrated_chf_kwh", "grid_chf_kwh"], index=0)

    st.header("GoodWe")
    device_sn = st.text_input("SN équipement batterie/onduleur")
    datalogger_sn = st.text_input("SN EzManager / datalogger")
    dry_run = st.toggle("Mode test : ne rien envoyer à GoodWe", value=True)

st.subheader("1. Tarifs Groupe E VARIO")
if st.button("Récupérer les tarifs"):
    with st.spinner("Récupération des tarifs VARIO..."):
        publication_timestamp, slots, _payload = fetch_vario_tariffs()
        st.session_state["publication_timestamp"] = publication_timestamp
        st.session_state["slots"] = slots

slots = st.session_state.get("slots", [])
publication_timestamp = st.session_state.get("publication_timestamp")

if slots:
    st.success(f"{len(slots)} prix récupérés. Publication : {publication_timestamp}")
    df = pd.DataFrame(slots_to_rows(slots))
    st.dataframe(df, use_container_width=True, height=280)

    st.subheader("2. Stratégie proposée")
    windows = build_simple_strategy(
        slots,
        battery_capacity_kwh=battery_capacity_kwh,
        charge_power_kw=charge_power_kw,
        discharge_power_kw=discharge_power_kw,
        charge_target_soc=charge_target_soc,
        discharge_target_soc=discharge_target_soc,
        soc_min=soc_min,
        soc_start=soc_start,
        price_field=price_field,
    )
    st.session_state["windows"] = windows

    strategy_df = pd.DataFrame(
        [
            {
                "action": w.action,
                "start": w.start,
                "end": w.end,
                "power_kW": w.power_w / 1000,
                "target_soc": w.target_soc,
                "avg_price_chf_kwh": round(w.avg_price_chf_kwh, 4),
                "slots_15min": w.slots_count,
            }
            for w in windows
        ]
    )
    st.dataframe(strategy_df, use_container_width=True)

    with st.expander("Payload GoodWe prévu"):
        for w in windows:
            st.json({"functionName": "BatteryCD", "items": [{"sn": device_sn or "DEVICE_SN", "data": window_to_goodwe_data(w)}]})

    st.subheader("3. Envoi GoodWe")
    if dry_run:
        st.info("Mode test actif : aucun ordre ne sera envoyé.")

    if st.button("Envoyer les consignes à GoodWe", type="primary", disabled=dry_run or not device_sn):
        client = GoodWeClient(
            GoodWeConfig(
                base_url=os.getenv("GOODWE_BASE_URL", "https://openapi.goodwe.com"),
                authorization=os.getenv("GOODWE_AUTHORIZATION", ""),
                app_identifier=os.getenv("GOODWE_APP_IDENTIFIER", ""),
            )
        )
        if datalogger_sn:
            st.write("Activation du mode third-party dispatch...")
            st.json(client.set_ems_third_party_dispatch(datalogger_sn))
        st.write("Envoi des fenêtres BatteryCD...")
        st.json(client.send_battery_windows(device_sn, windows))
else:
    st.info("Clique sur “Récupérer les tarifs” pour commencer.")
