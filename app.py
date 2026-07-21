from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from dispatch import window_payload
from forecast import forecast_from_dataframe, forecast_to_rows, synthetic_forecast
from goodwe_api import GoodWeClient, GoodWeConfig
from groupe_e import fetch_vario_tariffs, slots_to_rows
from optimizer import optimize_day

load_dotenv()
st.set_page_config(page_title="Soleol EMS VARIO", layout="wide")
st.title("Soleol EMS — Groupe E VARIO → GoodWe EzManager")

with st.sidebar:
    st.header("Installation")
    site_name = st.text_input("Nom du site", value="Site test")

    st.header("Batterie")
    capacity = st.number_input("Capacité batterie (kWh)", min_value=1.0, value=50.0)
    p_charge = st.number_input("Puissance charge max (kW)", min_value=0.1, value=20.0)
    p_discharge = st.number_input("Puissance décharge max (kW)", min_value=0.1, value=20.0)
    soc_start = st.slider("SOC initial (%)", 0, 100, 50)
    soc_min = st.slider("SOC minimum (%)", 0, 100, 20)
    soc_max = st.slider("SOC maximum (%)", 0, 100, 95)
    allow_grid_charge = st.toggle("Autoriser charge réseau", value=True)
    min_margin = st.number_input("Marge minimale (CHF/kWh)", min_value=0.0, value=0.02, step=0.005)

    st.header("Prévision du lendemain")
    forecast_mode = st.radio("Source", ["Profil théorique", "Fichier CSV"], horizontal=False)
    pv_day = st.number_input("Production PV prévue (kWh)", min_value=0.0, value=120.0)
    load_day = st.number_input("Consommation prévue (kWh)", min_value=0.0, value=160.0)
    uploaded = st.file_uploader("CSV : timestamp, pv_kwh, load_kwh", type=["csv"])

    st.header("GoodWe")
    device_sn = st.text_input("SN batterie/onduleur")
    datalogger_sn = st.text_input("SN EzManager / datalogger")
    dry_run = st.toggle("Mode test : ne rien envoyer", value=True)

if st.button("Récupérer tarifs VARIO", type="primary"):
    with st.spinner("Récupération Groupe E..."):
        publication_timestamp, slots, payload = fetch_vario_tariffs()
        st.session_state["publication_timestamp"] = publication_timestamp
        st.session_state["slots"] = slots
        st.session_state["raw_payload"] = payload

slots = st.session_state.get("slots", [])
if not slots:
    st.info("Commence par récupérer les tarifs VARIO.")
    st.stop()

try:
    if forecast_mode == "Fichier CSV" and uploaded is not None:
        forecast_df = pd.read_csv(uploaded)
        forecast = forecast_from_dataframe(forecast_df, slots)
    else:
        forecast = synthetic_forecast(slots, pv_energy_kwh=pv_day, load_energy_kwh=load_day)
except Exception as exc:
    st.error(f"Prévision invalide : {exc}")
    st.stop()

result = optimize_day(
    slots,
    forecast,
    battery_capacity_kwh=capacity,
    charge_power_kw=p_charge,
    discharge_power_kw=p_discharge,
    soc_start_pct=soc_start,
    soc_min_pct=soc_min,
    soc_max_pct=soc_max,
    allow_grid_charge=allow_grid_charge,
    min_arbitrage_margin_chf_kwh=min_margin,
)

st.success(f"{len(slots)} prix récupérés — publication : {st.session_state.get('publication_timestamp', '')}")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Coût sans EMS", f"{result.baseline_cost_chf:.2f} CHF")
m2.metric("Coût avec EMS", f"{result.optimized_cost_chf:.2f} CHF")
m3.metric("Gain estimé", f"{result.estimated_gain_chf:.2f} CHF/j")
m4.metric("SOC final", f"{result.final_soc_pct:.1f} %")
m5.metric("Fenêtres GoodWe", str(len(result.windows)))

m6, m7 = st.columns(2)
m6.metric("Énergie chargée", f"{result.charged_energy_kwh:.1f} kWh")
m7.metric("Énergie déchargée", f"{result.discharged_energy_kwh:.1f} kWh")
st.caption(result.strategy_comment)

st.subheader("1. Tarifs et prévision")
prices = pd.DataFrame(slots_to_rows(slots))
fc = pd.DataFrame(forecast_to_rows(forecast))
plot = prices.merge(fc, on=["start", "end"])
plot["time"] = pd.to_datetime(plot["start"])
plot = plot.set_index("time")
st.line_chart(plot[["integrated_chf_kwh", "grid_chf_kwh"]].rename(columns={
    "integrated_chf_kwh": "achat_CHF_kWh",
    "grid_chf_kwh": "revente_CHF_kWh",
}), height=280)
st.line_chart(plot[["pv_kwh", "load_kwh"]], height=280)

st.subheader("2. Simulation énergétique 15 minutes")
steps_df = pd.DataFrame([s.__dict__ for s in result.steps])
st.dataframe(steps_df, use_container_width=True, height=360, hide_index=True)

st.subheader("3. Fenêtres GoodWe proposées")
windows_df = pd.DataFrame([
    {
        "action": w.action,
        "début": w.start.strftime("%d.%m.%Y %H:%M"),
        "fin": w.end.strftime("%d.%m.%Y %H:%M"),
        "puissance_kW": w.power_kw,
        "SOC_cible": w.target_soc,
        "énergie_kWh": w.energy_kwh,
    }
    for w in result.windows
])
st.dataframe(windows_df, use_container_width=True, hide_index=True)

with st.expander("Payloads GoodWe"):
    for w in result.windows:
        st.json(window_payload(device_sn or "DEVICE_SN", w))

st.subheader("4. Envoi GoodWe")
if dry_run:
    st.warning("Mode test actif : aucun ordre ne sera envoyé.")
else:
    st.error("Mode réel actif. Utiliser uniquement sur une installation pilote maîtrisée.")

can_send = bool(device_sn) and bool(result.windows) and not dry_run
if st.button("Envoyer la stratégie à GoodWe", type="primary", disabled=not can_send):
    client = GoodWeClient(
        GoodWeConfig(
            base_url=os.getenv("GOODWE_BASE_URL", "https://openapi.goodwe.com"),
            authorization=os.getenv("GOODWE_AUTHORIZATION", ""),
            app_identifier=os.getenv("GOODWE_APP_IDENTIFIER", ""),
        )
    )
    if datalogger_sn:
        st.write("Activation Third-party dispatch...")
        st.json(client.set_ems_third_party_dispatch(datalogger_sn))
    st.write("Envoi BatteryCD...")
    st.json(client.send_battery_windows(device_sn, result.windows))

st.caption(f"Site : {site_name} — Calcul : {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
