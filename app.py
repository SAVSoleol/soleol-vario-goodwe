from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from billing import compare_double_vario
from dispatch import window_payload
from forecast import forecast_from_dataframe, forecast_to_rows, synthetic_forecast
from goodwe_api import GoodWeClient, GoodWeConfig
from groupe_e import fetch_vario_date_range, fetch_vario_tariffs, slots_to_rows
from optimizer import optimize_day

load_dotenv()
st.set_page_config(page_title="Soleol — Comparateur Groupe E VARIO", layout="wide")
st.title("Soleol — Comparateur Groupe E : Double vs VARIO + batterie")
st.caption("Objectif : quantifier le gain du tarif dynamique sur le profil réel du client, puis le gain supplémentaire possible avec une batterie.")

with st.sidebar:
    st.header("Installation")
    site_name = st.text_input("Nom du site", value="Site test")

    st.header("Période VARIO")
    tariff_mode = st.radio("Source", ["Tarifs publiés", "Historique"], horizontal=False)
    today = date.today()
    hist_start = st.date_input("Début historique", value=max(date(2025, 12, 11), today - timedelta(days=30)), disabled=tariff_mode != "Historique")
    hist_end = st.date_input("Fin historique", value=today, disabled=tariff_mode != "Historique")

    st.header("Tarif Double — référence")
    st.caption("Valeurs modifiables. Les plages 2026 sont HT 07-12 / 17-23 et BT le reste.")
    double_high_ct = st.number_input("Haut tarif (ct/kWh)", min_value=0.0, value=31.0, step=0.1)
    double_low_ct = st.number_input("Bas tarif (ct/kWh)", min_value=0.0, value=21.0, step=0.1)
    feed_in_ct = st.number_input("Reprise PV / injection (ct/kWh)", min_value=-50.0, value=8.0, step=0.1,
                                 help="Rémunération de l'énergie injectée. Ce n'est pas la valeur 'grid' de l'API VARIO.")

    st.header("Profil client")
    forecast_mode = st.radio("Source énergétique", ["Profil théorique", "Fichier CSV"], horizontal=False)
    pv_day = st.number_input("Production PV (kWh/jour)", min_value=0.0, value=120.0)
    load_day = st.number_input("Consommation (kWh/jour)", min_value=0.0, value=160.0)
    uploaded = st.file_uploader("CSV : timestamp, pv_kwh, load_kwh", type=["csv"])

    st.header("Batterie — scénario 3")
    battery_enabled = st.toggle("Simuler une batterie", value=True)
    capacity = st.number_input("Capacité batterie (kWh)", min_value=1.0, value=50.0, disabled=not battery_enabled)
    p_charge = st.number_input("Puissance charge max (kW)", min_value=0.1, value=20.0, disabled=not battery_enabled)
    p_discharge = st.number_input("Puissance décharge max (kW)", min_value=0.1, value=20.0, disabled=not battery_enabled)
    soc_start = st.slider("SOC initial (%)", 0, 100, 50, disabled=not battery_enabled)
    soc_min = st.slider("SOC minimum (%)", 0, 100, 20, disabled=not battery_enabled)
    soc_max = st.slider("SOC maximum (%)", 0, 100, 95, disabled=not battery_enabled)
    allow_grid_charge = st.toggle("Autoriser charge réseau", value=True, disabled=not battery_enabled)

    st.header("Pilotage batterie")
    strategy_label = st.radio("Stratégie", ["Automatique VARIO", "Seuils manuels"], horizontal=False, disabled=not battery_enabled)
    strategy_mode = "manual" if strategy_label == "Seuils manuels" else "automatic"
    min_margin_ct = st.number_input("Marge minimale arbitrage (ct/kWh)", min_value=0.0, value=2.0, step=0.5, disabled=not battery_enabled)
    buy_min_ct = st.number_input("Charger réseau sous (ct/kWh)", min_value=0.0, value=12.0, step=0.5,
                                 disabled=(not battery_enabled or strategy_mode != "manual"))
    buy_max_ct = st.number_input("Décharger au-dessus de (ct/kWh)", min_value=0.0, value=30.0, step=0.5,
                                 disabled=(not battery_enabled or strategy_mode != "manual"))

    st.header("GoodWe")
    device_sn = st.text_input("SN batterie/onduleur")
    datalogger_sn = st.text_input("SN EzManager / datalogger")
    dry_run = st.toggle("Mode test : ne rien envoyer", value=True)

if st.button("Récupérer tarifs VARIO", type="primary"):
    try:
        with st.spinner("Récupération Groupe E..."):
            if tariff_mode == "Historique":
                publication_timestamp, slots, payload = fetch_vario_date_range(hist_start, hist_end)
                st.session_state["is_historical"] = True
            else:
                publication_timestamp, slots, payload = fetch_vario_tariffs()
                st.session_state["is_historical"] = False
            st.session_state["publication_timestamp"] = publication_timestamp
            st.session_state["slots"] = slots
            st.session_state["raw_payload"] = payload
    except Exception as exc:
        st.error(f"Erreur Groupe E : {exc}")

slots = st.session_state.get("slots", [])
is_historical = bool(st.session_state.get("is_historical", False))
if not slots:
    st.info("Commence par récupérer les tarifs VARIO.")
    st.stop()

try:
    if forecast_mode == "Fichier CSV" and uploaded is not None:
        forecast_df = pd.read_csv(uploaded)
        forecast = forecast_from_dataframe(forecast_df, slots)
    else:
        forecast = synthetic_forecast(slots, pv_energy_kwh=pv_day, load_energy_kwh=load_day, per_day=is_historical)
except Exception as exc:
    st.error(f"Profil énergétique invalide : {exc}")
    st.stop()

# Exact covered duration: 96 slots = 1 day, not 2 calendar dates.
period_days = max(1.0, sum((s.end - s.start).total_seconds() for s in slots) / 86400.0)

comparison = compare_double_vario(
    slots,
    forecast,
    double_high_ct_kwh=double_high_ct,
    double_low_ct_kwh=double_low_ct,
    feed_in_ct_kwh=feed_in_ct,
)

result = None
if battery_enabled:
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
        min_arbitrage_margin_chf_kwh=min_margin_ct / 100.0,
        strategy_mode=strategy_mode,
        buy_min_chf_kwh=buy_min_ct / 100.0,
        buy_max_chf_kwh=buy_max_ct / 100.0,
        feed_in_chf_kwh=feed_in_ct / 100.0,
    )

st.success(f"{len(slots)} prix VARIO — {slots[0].start:%d.%m.%Y %H:%M} → {slots[-1].end:%d.%m.%Y %H:%M} — {period_days:.2f} jour(s)")

st.subheader("Comparaison demandée — même profil de consommation")
c1, c2, c3, c4 = st.columns(4)
c1.metric("1. Tarif Double", f"{comparison.double_cost_chf:.2f} CHF")
c2.metric("2. Tarif VARIO", f"{comparison.vario_cost_chf:.2f} CHF")
c3.metric("Économie VARIO", f"{comparison.saving_chf:.2f} CHF", delta=f"{comparison.saving_pct:.1f} %")
c4.metric("Économie moyenne", f"{comparison.saving_chf / period_days:.2f} CHF/j")

if comparison.saving_chf >= 0:
    st.info(f"Sur cette période et ce profil, VARIO économise {comparison.saving_chf:.2f} CHF ({comparison.saving_pct:.1f} %) par rapport au tarif Double.")
else:
    st.warning(f"Sur cette période et ce profil, VARIO coûte {-comparison.saving_chf:.2f} CHF de plus ({-comparison.saving_pct:.1f} %) que le tarif Double.")

if result is not None:
    st.subheader("3. VARIO + batterie optimisée")
    b1, b2, b3, b4, b5 = st.columns(5)
    b1.metric("VARIO sans batterie", f"{comparison.vario_cost_chf:.2f} CHF")
    b2.metric("VARIO + batterie", f"{result.optimized_cost_chf:.2f} CHF")
    battery_extra = comparison.vario_cost_chf - result.optimized_cost_chf
    total_vs_double = comparison.double_cost_chf - result.optimized_cost_chf
    b3.metric("Gain batterie en plus", f"{battery_extra:.2f} CHF")
    b4.metric("Gain total vs Double", f"{total_vs_double:.2f} CHF")
    b5.metric("SOC final", f"{result.final_soc_pct:.1f} %")

    e1, e2, e3 = st.columns(3)
    e1.metric("Énergie chargée", f"{result.charged_energy_kwh:.1f} kWh")
    e2.metric("Énergie déchargée", f"{result.discharged_energy_kwh:.1f} kWh")
    e3.metric("Gain batterie moyen", f"{battery_extra / period_days:.2f} CHF/j")

st.subheader("Prix VARIO observés")
buy_values_ct = [s.integrated_chf_kwh * 100 for s in slots]
grid_values_ct = [s.grid_chf_kwh * 100 for s in slots]
t1, t2, t3, t4 = st.columns(4)
t1.metric("VARIO intégré min.", f"{min(buy_values_ct):.2f} ct/kWh")
t2.metric("VARIO intégré max.", f"{max(buy_values_ct):.2f} ct/kWh")
t3.metric("Réseau VARIO min.", f"{min(grid_values_ct):.2f} ct/kWh")
t4.metric("Réseau VARIO max.", f"{max(grid_values_ct):.2f} ct/kWh")
st.caption("Le prix 'Réseau VARIO' est une composante du prix d'achat, pas un tarif de reprise de l'électricité injectée.")

st.subheader("Tarifs et profil énergétique")
prices = pd.DataFrame(slots_to_rows(slots))
fc = pd.DataFrame(forecast_to_rows(forecast))
plot = prices.merge(fc, on=["start", "end"])
plot["time"] = pd.to_datetime(plot["start"])
plot["double_chf_kwh"] = plot["time"].apply(
    lambda x: (double_high_ct if ((7 <= x.hour < 12) or (17 <= x.hour < 23)) else double_low_ct) / 100.0
)
plot = plot.set_index("time")
st.line_chart(plot[["integrated_chf_kwh", "double_chf_kwh"]].rename(columns={
    "integrated_chf_kwh": "VARIO_achat_CHF_kWh",
    "double_chf_kwh": "DOUBLE_achat_CHF_kWh",
}), height=280)
st.line_chart(plot[["pv_kwh", "load_kwh"]], height=260)

if is_historical:
    st.subheader("Résumé journalier Double vs VARIO")
    rows = []
    for slot, fc_slot in zip(slots, forecast):
        net = fc_slot.load_kwh - fc_slot.pv_kwh
        imp = max(0.0, net)
        exp = max(0.0, -net)
        double_price = (double_high_ct if ((7 <= slot.start.hour < 12) or (17 <= slot.start.hour < 23)) else double_low_ct) / 100.0
        rows.append({
            "jour": slot.start.date(),
            "import_kwh": imp,
            "export_kwh": exp,
            "cout_double_chf": imp * double_price - exp * feed_in_ct / 100.0,
            "cout_vario_chf": imp * slot.integrated_chf_kwh - exp * feed_in_ct / 100.0,
        })
    daily = pd.DataFrame(rows).groupby("jour", as_index=False).sum()
    daily["gain_vario_chf"] = daily["cout_double_chf"] - daily["cout_vario_chf"]
    st.dataframe(daily.round(3), use_container_width=True, hide_index=True)

st.subheader("GoodWe")
if result is None:
    st.info("Simulation batterie désactivée.")
elif is_historical:
    st.info("Mode historique : aucune commande GoodWe ne peut être envoyée.")
else:
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

can_send = result is not None and (not is_historical) and bool(device_sn) and bool(result.windows) and not dry_run
if st.button("Envoyer la stratégie à GoodWe", type="primary", disabled=not can_send):
    client = GoodWeClient(GoodWeConfig(
        base_url=os.getenv("GOODWE_BASE_URL", "https://openapi.goodwe.com"),
        authorization=os.getenv("GOODWE_AUTHORIZATION", ""),
        app_identifier=os.getenv("GOODWE_APP_IDENTIFIER", ""),
    ))
    if datalogger_sn:
        st.json(client.set_ems_third_party_dispatch(datalogger_sn))
    st.json(client.send_battery_windows(device_sn, result.windows))

st.caption(f"Site : {site_name} — Calcul : {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
