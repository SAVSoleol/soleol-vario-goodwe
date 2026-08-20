
from __future__ import annotations

import tempfile
from pathlib import Path
import pandas as pd
import numpy as np
import streamlit as st

from billing import compare_double_vario
from groupe_e_api import fetch_vario
from meter_loader import load_consumption_file
from battery_opt import optimize_battery, double_price_vector
from reprise_groupe_e import repurchase_vector, quarterly_summary

try:
    from report_vario import generate_vario_report
    HAS_REPORT = True
except Exception:
    HAS_REPORT = False

st.set_page_config(page_title="Soleol — Analyse VARIO", layout="wide")
VARIO_HISTORY_START = pd.Timestamp("2025-12-11 00:00:00")
MONTHS_FR = {
    1:"Janvier",2:"Février",3:"Mars",4:"Avril",5:"Mai",6:"Juin",
    7:"Juillet",8:"Août",9:"Septembre",10:"Octobre",11:"Novembre",12:"Décembre"
}

st.markdown("""
<style>
.block-container{max-width:1500px;padding-top:1.6rem}
.kpi-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:8px 0 12px}
.kpi-card{border-radius:12px;padding:16px 18px;border:1px solid;min-height:88px}
.kpi-label{font-size:.84rem;font-weight:750;margin-bottom:7px}
.kpi-value{font-size:1.55rem;font-weight:850;line-height:1.05}
.kpi-sub{font-size:.76rem;margin-top:7px;font-weight:650}
.kpi-red{background:linear-gradient(100deg,rgba(127,29,29,.42),rgba(69,10,10,.18));border-color:rgba(239,68,68,.5)}
.kpi-red .kpi-label,.kpi-red .kpi-sub{color:#fca5a5}
.kpi-blue{background:linear-gradient(100deg,rgba(30,64,175,.35),rgba(7,32,63,.20));border-color:rgba(59,130,246,.5)}
.kpi-blue .kpi-label,.kpi-blue .kpi-sub{color:#93c5fd}
.kpi-green{background:linear-gradient(100deg,rgba(20,83,45,.38),rgba(5,46,22,.18));border-color:rgba(34,197,94,.45)}
.kpi-green .kpi-label,.kpi-green .kpi-sub{color:#86efac}
.kpi-purple{background:linear-gradient(100deg,rgba(88,28,135,.42),rgba(59,7,100,.20));border-color:rgba(168,85,247,.52)}
.kpi-purple .kpi-label,.kpi-purple .kpi-sub{color:#d8b4fe}
.kpi-orange{background:linear-gradient(100deg,rgba(124,45,18,.38),rgba(67,20,7,.18));border-color:rgba(249,115,22,.48)}
.kpi-orange .kpi-label,.kpi-orange .kpi-sub{color:#fdba74}
.section-shell{border:1px solid rgba(148,163,184,.18);border-radius:16px;padding:15px 17px;margin-bottom:16px;background:rgba(15,23,42,.18)}
.compare-title{font-size:1.1rem;font-weight:850;margin-bottom:3px}
.compare-sub{font-size:.78rem;color:#94a3b8;margin-bottom:8px}
</style>
""", unsafe_allow_html=True)

st.title("Analyse tarifaire Groupe E")
st.caption("Comparaison du tarif Double, du tarif dynamique VARIO et du potentiel d'une batterie.")

# ---------------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("1. Données client")
    client = st.text_input("Client / site", value="")
    uploaded = st.file_uploader("Courbe import / export réseau", type=["xlsx","xls","csv"])
    transpose_to_2026 = st.toggle("Utiliser un profil 2025 comme profil 2026", value=True)

    st.header("2. Période d'analyse")

    st.header("3. Tarif Double")
    ht_ct = st.number_input("Haut tarif (ct/kWh)", min_value=0.0, value=29.32, step=0.01)
    bt_ct = st.number_input("Bas tarif (ct/kWh)", min_value=0.0, value=19.27, step=0.01)
    st.caption("HT : 07h–12h et 17h–23h. BT : le reste.")

    st.header("4. Reprise PV Groupe E")
    installation_kw = st.number_input(
        "Puissance PV (kW)", min_value=0.1, value=10.0, step=0.5,
        help="Le minimum Groupe E de 6 ct/kWh est directement applicable aux installations <30 kW."
    )
    sell_go = st.toggle("Céder la GO à Groupe E", value=False)
    provisional_ct = st.number_input(
        "Reprise provisoire trimestre non publié (ct/kWh)",
        min_value=0.0, value=6.0, step=0.1,
        help="Utilisée uniquement pour un trimestre dont le prix OFEN/Groupe E n'est pas encore publié."
    )

    st.header("5. Batterie")
    capacity = st.number_input("Capacité (kWh)", min_value=1.0, value=10.0, step=1.0)
    power = st.number_input("Puissance (kW)", min_value=0.5, value=5.0, step=0.5)
    efficiency = st.slider("Rendement aller-retour", 0.50, 1.00, 0.92, 0.01)
    soc_min = st.slider("SOC minimum (%)", 0, 50, 5)
    soc_max = st.slider("SOC maximum (%)", 50, 100, 95)
    allow_grid_charge = st.toggle("Autoriser la charge depuis le réseau", value=False)
    wear_ct = st.number_input("Coût d'usure (ct/kWh déchargé)", min_value=0.0, value=4.0, step=0.5)

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
    original_df, meta = load_cached(uploaded.name, uploaded.getvalue(), unit)
except Exception as exc:
    st.error(f"Fichier non reconnu : {exc}")
    st.stop()

# Transpose 2025 -> 2026 if requested
analysis_df = original_df.copy()
profile_transposed = False
if transpose_to_2026 and analysis_df.timestamp.min().year == 2025:
    analysis_df["timestamp"] = analysis_df["timestamp"].map(lambda x: x.replace(year=2026))
    profile_transposed = True

st.success(
    f"Fichier reconnu : {meta.vendor} · {meta.n_rows:,} mesures · "
    f"pas {meta.dt_hours*60:.0f} min · unité {meta.input_unit}"
)
if profile_transposed:
    st.warning("MODE SIMULATION — Profil 2025 transposé sur 2026 ; prix VARIO réels 2026.")

# ---------------------------------------------------------------------- month selector
available_periods = sorted(analysis_df["timestamp"].dt.to_period("M").unique().tolist())
labels = [f"{MONTHS_FR[p.month]} {p.year}" for p in available_periods]
with st.sidebar:
    if available_periods:
        start_label = st.selectbox("Mois de début", labels, index=0)
        end_default = min(len(labels)-1, max(0, pd.Timestamp.now().month-1 if analysis_df.timestamp.min().year == pd.Timestamp.now().year else len(labels)-1))
        end_label = st.selectbox("Mois de fin", labels, index=end_default)
        start_period = available_periods[labels.index(start_label)]
        end_period = available_periods[labels.index(end_label)]
    else:
        st.error("Aucun mois détecté.")
        st.stop()

if start_period > end_period:
    st.error("Le mois de début doit être antérieur au mois de fin.")
    st.stop()

period_start = start_period.start_time
period_end = end_period.end_time
period_df = analysis_df[
    (analysis_df.timestamp >= period_start) &
    (analysis_df.timestamp <= period_end)
].copy()

if period_df.empty:
    st.error("Aucune donnée sur la période sélectionnée.")
    st.stop()

# Original-period counterpart for Double display if transposed
if profile_transposed:
    orig_start = period_start.replace(year=2025)
    orig_end = period_end.replace(year=2025)
    display_double_df = original_df[
        (original_df.timestamp >= orig_start) &
        (original_df.timestamp <= orig_end)
    ].copy()
    period_label = f"{MONTHS_FR[start_period.month]} à {MONTHS_FR[end_period.month]} 2026 (profil 2025 transposé)"
else:
    display_double_df = period_df.copy()
    period_label = f"{start_label} à {end_label}"

st.subheader(f"Période sélectionnée : {period_label}")

# ---------------------------------------------------------------------- Double side
# The visible Double vs VARIO comparison is intentionally calculated only after
# the API merge, so both scenarios use EXACTLY the same quarter-hours.
# This avoids comparing a full selected month on Double with only a partial
# month available on VARIO.

# ---------------------------------------------------------------------- Fetch VARIO early so right panel can be displayed
today = pd.Timestamp.now(tz="Europe/Zurich").tz_localize(None)
api_start = max(VARIO_HISTORY_START, period_df.timestamp.min().floor("15min"))
api_end = min(today.ceil("15min"), period_df.timestamp.max().ceil("15min") + pd.Timedelta(minutes=15))

if api_end <= api_start:
    vario = pd.DataFrame()
    merged = pd.DataFrame()
else:
    with st.spinner("Récupération des prix VARIO pour la période sélectionnée..."):
        try:
            vario, _ = fetch_vario(api_start, api_end)
        except Exception as exc:
            st.error(f"API Groupe E : {exc}")
            vario = pd.DataFrame()

data_q = period_df.copy()
data_q["timestamp"] = data_q["timestamp"].dt.floor("15min")
merged = data_q.merge(vario, on="timestamp", how="inner") if not vario.empty else pd.DataFrame()

if not merged.empty:
    # Reprise vector must match the exact common VARIO timestamps.
    feed_vec, feed_labels = repurchase_vector(
        merged.timestamp,
        installation_kw=installation_kw,
        sell_go=sell_go,
        provisional_ct=provisional_ct,
    )

    # -------------------- VARIO on common intervals
    comparable_import_kwh = float(merged.import_kWh.sum())
    comparable_export_kwh = float(merged.export_kWh.sum())
    vario_import_cost = float(np.dot(merged.import_kWh.values, merged.vario_chf_kwh.values))
    vario_export_revenue = float(np.dot(merged.export_kWh.values, feed_vec))
    vario_net = vario_import_cost - vario_export_revenue
    vario_avg_ct = (
        vario_import_cost / comparable_import_kwh * 100
        if comparable_import_kwh > 0 else 0.0
    )

    # -------------------- DOUBLE on the exact same intervals
    dprices_common = double_price_vector(merged.timestamp, ht_ct/100, bt_ct/100)
    ht_mask_common = np.isclose(dprices_common, ht_ct/100)
    bt_mask_common = ~ht_mask_common

    ht_kwh = float(merged.loc[ht_mask_common, "import_kWh"].sum())
    bt_kwh = float(merged.loc[bt_mask_common, "import_kWh"].sum())
    total_import = ht_kwh + bt_kwh

    ht_cost = ht_kwh * ht_ct/100
    bt_cost = bt_kwh * bt_ct/100
    double_common_import_cost = ht_cost + bt_cost

    double_common_export_revenue = float(np.dot(merged.export_kWh.values, feed_vec))
    double_common_net = double_common_import_cost - double_common_export_revenue

    # Shared export quantities for both scenarios.
    export_total = comparable_export_kwh
    export_revenue = double_common_export_revenue

    saving_vario = double_common_net - vario_net
    saving_vario_pct = saving_vario / double_common_net * 100 if double_common_net else 0.0

    ht_share = ht_kwh / total_import * 100 if total_import else 0.0
    bt_share = bt_kwh / total_import * 100 if total_import else 0.0
else:
    feed_vec = np.array([])
    comparable_import_kwh = comparable_export_kwh = 0.0
    ht_kwh = bt_kwh = total_import = 0.0
    ht_cost = bt_cost = double_common_import_cost = 0.0
    export_total = export_revenue = 0.0
    vario_import_cost = vario_export_revenue = vario_net = vario_avg_ct = 0.0
    double_common_export_revenue = double_common_net = 0.0
    saving_vario = saving_vario_pct = 0.0
    ht_share = bt_share = 0.0

# ---------------------------------------------------------------------- visual side-by-side tables
if not merged.empty:
    actual_start = merged.timestamp.min()
    actual_end = merged.timestamp.max()
    st.caption(
        f"Comparaison réelle sur les mêmes quarts d'heure : "
        f"{actual_start:%d.%m.%Y %H:%M} → {actual_end:%d.%m.%Y %H:%M} "
        f"({len(merged):,} pas de 15 min).".replace(",", " ")
    )

left, right = st.columns(2)

with left:
    st.markdown('<div class="section-shell">', unsafe_allow_html=True)
    st.markdown('<div class="compare-title">Tarif Double — HT / BT</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="compare-sub">Même période et mêmes quarts d’heure que VARIO. '
        'Répartition du soutirage selon les plages haut et bas tarif.</div>',
        unsafe_allow_html=True
    )

    st.markdown(f"""
    <div class="kpi-grid">
      <div class="kpi-card kpi-red">
        <div class="kpi-label">Consommation HT</div>
        <div class="kpi-value">{ht_kwh:,.0f} kWh</div>
        <div class="kpi-sub">{ht_share:.1f} % du soutirage</div>
      </div>
      <div class="kpi-card kpi-red">
        <div class="kpi-label">Coût soutirage HT</div>
        <div class="kpi-value">{ht_cost:,.2f} CHF</div>
        <div class="kpi-sub">{ht_ct:.2f} ct/kWh</div>
      </div>

      <div class="kpi-card kpi-blue">
        <div class="kpi-label">Consommation BT</div>
        <div class="kpi-value">{bt_kwh:,.0f} kWh</div>
        <div class="kpi-sub">{bt_share:.1f} % du soutirage</div>
      </div>
      <div class="kpi-card kpi-blue">
        <div class="kpi-label">Coût soutirage BT</div>
        <div class="kpi-value">{bt_cost:,.2f} CHF</div>
        <div class="kpi-sub">{bt_ct:.2f} ct/kWh</div>
      </div>

      <div class="kpi-card kpi-green">
        <div class="kpi-label">Soutirage total Double</div>
        <div class="kpi-value">{total_import:,.0f} kWh</div>
        <div class="kpi-sub">HT + BT</div>
      </div>
      <div class="kpi-card kpi-green">
        <div class="kpi-label">Coût soutirage Double</div>
        <div class="kpi-value">{double_common_import_cost:,.2f} CHF</div>
        <div class="kpi-sub">avant revenus d'injection</div>
      </div>

      <div class="kpi-card kpi-purple">
        <div class="kpi-label">Export total</div>
        <div class="kpi-value">{export_total:,.0f} kWh</div>
        <div class="kpi-sub">mêmes quarts d'heure</div>
      </div>
      <div class="kpi-card kpi-purple">
        <div class="kpi-label">Revenus d'injection</div>
        <div class="kpi-value">{double_common_export_revenue:,.2f} CHF</div>
        <div class="kpi-sub">reprise Groupe E trimestrielle</div>
      </div>

      <div class="kpi-card kpi-orange">
        <div class="kpi-label">Coût net Double</div>
        <div class="kpi-value">{double_common_net:,.2f} CHF</div>
        <div class="kpi-sub">soutirage - revenus d'injection</div>
      </div>
      <div class="kpi-card kpi-orange">
        <div class="kpi-label">Référence de comparaison</div>
        <div class="kpi-value">100 %</div>
        <div class="kpi-sub">base pour calculer le gain VARIO</div>
      </div>
    </div>
    """.replace(",", " "), unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

with right:
    st.markdown('<div class="section-shell">', unsafe_allow_html=True)
    st.markdown('<div class="compare-title">Tarif VARIO — prix dynamique</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="compare-sub">Exactement le même soutirage et le même export, '
        'mais chaque quart d’heure est valorisé au prix VARIO réel.</div>',
        unsafe_allow_html=True
    )

    if merged.empty:
        st.warning("Pas de prix VARIO disponible sur cette période.")
    else:
        st.markdown(f"""
        <div class="kpi-grid">
          <div class="kpi-card kpi-blue">
            <div class="kpi-label">Soutirage total VARIO</div>
            <div class="kpi-value">{comparable_import_kwh:,.0f} kWh</div>
            <div class="kpi-sub">identique au Double</div>
          </div>
          <div class="kpi-card kpi-blue">
            <div class="kpi-label">Coût soutirage VARIO</div>
            <div class="kpi-value">{vario_import_cost:,.2f} CHF</div>
            <div class="kpi-sub">prix moyen {vario_avg_ct:.2f} ct/kWh</div>
          </div>

          <div class="kpi-card kpi-purple">
            <div class="kpi-label">Export total</div>
            <div class="kpi-value">{comparable_export_kwh:,.0f} kWh</div>
            <div class="kpi-sub">identique au Double</div>
          </div>
          <div class="kpi-card kpi-purple">
            <div class="kpi-label">Revenus d'injection</div>
            <div class="kpi-value">{vario_export_revenue:,.2f} CHF</div>
            <div class="kpi-sub">même reprise Groupe E</div>
          </div>

          <div class="kpi-card kpi-green">
            <div class="kpi-label">Coût net VARIO</div>
            <div class="kpi-value">{vario_net:,.2f} CHF</div>
            <div class="kpi-sub">soutirage - revenus d'injection</div>
          </div>
          <div class="kpi-card kpi-green">
            <div class="kpi-label">Économie VARIO vs Double</div>
            <div class="kpi-value">{saving_vario:,.2f} CHF</div>
            <div class="kpi-sub">{saving_vario_pct:+.1f} %</div>
          </div>
        </div>
        """.replace(",", " "), unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------------- quarterly repurchase summary
st.subheader("Reprise photovoltaïque Groupe E appliquée")
qsum = quarterly_summary(
    merged.timestamp if not merged.empty else period_df.timestamp,
    installation_kw=installation_kw,
    sell_go=sell_go,
    provisional_ct=provisional_ct,
)
st.dataframe(qsum, use_container_width=True, hide_index=True)
if any("provisoire" in x for x in qsum["Statut"].astype(str)):
    st.warning(
        "Au moins un trimestre n'a pas encore de prix définitif publié. "
        "Le calcul utilise la valeur provisoire saisie dans la barre latérale."
    )
if installation_kw >= 30:
    st.warning(
        "Installation ≥30 kW : le minimum Groupe E est dégressif selon la puissance. "
        "Le prix exact doit être confirmé selon le cas du client."
    )

# ---------------------------------------------------------------------- battery analysis
if merged.empty:
    st.stop()

st.divider()
st.subheader("Simulation batterie sur la période sélectionnée")

if st.button("Optimiser la batterie", type="primary"):
    if soc_max <= soc_min:
        st.error("SOC maximum doit être supérieur au SOC minimum.")
        st.stop()

    wear = wear_ct/100
    with st.spinner("Optimisation économique de la batterie..."):
        try:
            vario_pv = optimize_battery(
                merged, merged.vario_chf_kwh.values, feed_vec,
                capacity, power, meta.dt_hours, efficiency,
                soc_min, soc_max, False, wear
            )
            vario_grid = None
            if allow_grid_charge:
                vario_grid = optimize_battery(
                    merged, merged.vario_chf_kwh.values, feed_vec,
                    capacity, power, meta.dt_hours, efficiency,
                    soc_min, soc_max, True, wear
                )
        except Exception as exc:
            st.error(str(exc))
            st.stop()

    best = vario_grid if vario_grid is not None else vario_pv
    period_days = len(merged)*meta.dt_hours/24
    annual_factor = 365/period_days if period_days else 0

    gain_pv = vario_net - vario_pv.cost_chf
    net_gain_pv = vario_net - vario_pv.economic_cost_chf

    if vario_grid is not None:
        gain_arbitrage_extra = vario_pv.cost_chf - vario_grid.cost_chf
        net_arbitrage_extra = vario_pv.economic_cost_chf - vario_grid.economic_cost_chf
    else:
        gain_arbitrage_extra = net_arbitrage_extra = 0.0

    total_bill_gain = double_common_net - best.cost_chf
    total_net_gain = double_common_net - best.economic_cost_chf

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("VARIO sans batterie", f"{vario_net:,.2f} CHF".replace(","," "))
    c2.metric("VARIO + batterie PV", f"{vario_pv.cost_chf:,.2f} CHF".replace(","," "), f"{gain_pv:+.2f} CHF")
    if vario_grid is not None:
        c3.metric("VARIO + arbitrage", f"{vario_grid.cost_chf:,.2f} CHF".replace(","," "), f"{gain_arbitrage_extra:+.2f} CHF")
    else:
        c3.metric("Arbitrage réseau", "désactivé")
    c4.metric("Gain net après usure", f"{total_net_gain:,.2f} CHF".replace(","," "))

    st.info(
        f"Projection nette indicative : **{total_net_gain*annual_factor:,.0f} CHF/an** · "
        f"Cycles annualisés : **{best.cycles*annual_factor:.0f}/an**".replace(",", " ")
    )

    # Monthly chart
    detail = merged[["timestamp","import_kWh","export_kWh","vario_chf_kwh"]].copy()
    detail["double"] = merged.import_kWh.values*dprices_common - merged.export_kWh.values*feed_vec
    detail["vario"] = merged.import_kWh.values*merged.vario_chf_kwh.values - merged.export_kWh.values*feed_vec
    detail["vario_pv"] = vario_pv.import_after*merged.vario_chf_kwh.values - vario_pv.export_after*feed_vec
    if vario_grid is not None:
        detail["vario_grid"] = vario_grid.import_after*merged.vario_chf_kwh.values - vario_grid.export_after*feed_vec

    mcols = ["double","vario","vario_pv"] + (["vario_grid"] if vario_grid is not None else [])
    monthly = detail.set_index("timestamp")[mcols].resample("MS").sum()
    monthly["Mois"] = [MONTHS_FR[x.month] for x in monthly.index]

    tab1,tab2 = st.tabs(["Comparaison mensuelle","Pilotage batterie"])
    with tab1:
        ren={"double":"Double","vario":"VARIO","vario_pv":"VARIO + batterie PV","vario_grid":"VARIO + arbitrage"}
        st.bar_chart(monthly.set_index("Mois")[mcols].rename(columns=ren))
    with tab2:
        chosen = best
        control = pd.DataFrame({
            "timestamp": merged.timestamp,
            "prix_VARIO_ct_kWh": merged.vario_chf_kwh*100,
            "reprise_PV_ct_kWh": feed_vec*100,
            "import_avant_kWh": merged.import_kWh,
            "export_avant_kWh": merged.export_kWh,
            "charge_kWh": chosen.charge_kwh,
            "decharge_kWh": chosen.discharge_kwh,
            "SOC_kWh": chosen.soc_kwh,
            "import_apres_kWh": chosen.import_after,
            "export_apres_kWh": chosen.export_after,
        })
        st.dataframe(control, use_container_width=True, height=430, hide_index=True)
