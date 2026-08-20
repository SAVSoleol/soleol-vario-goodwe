
from __future__ import annotations
import tempfile
from pathlib import Path
import pandas as pd
import streamlit as st
from billing import compare_double_vario
from groupe_e_api import fetch_vario
from meter_loader import load_consumption_file
from battery_opt import optimize_battery, double_price_vector
from report_vario import generate_vario_report

st.set_page_config(page_title="Soleol — Analyse VARIO", layout="wide")

st.markdown("""
<style>
.kpi-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:10px 0 20px}
.kpi-card{border-radius:12px;padding:18px 22px;border:1px solid;min-height:92px}
.kpi-label{font-size:.86rem;font-weight:750;margin-bottom:8px}
.kpi-value{font-size:1.65rem;font-weight:850;line-height:1.05}
.kpi-sub{font-size:.78rem;margin-top:8px;font-weight:700}
.kpi-red{background:linear-gradient(100deg,rgba(127,29,29,.42),rgba(69,10,10,.20));border-color:rgba(239,68,68,.55)}
.kpi-red .kpi-label,.kpi-red .kpi-sub{color:#fca5a5}
.kpi-blue{background:linear-gradient(100deg,rgba(30,64,175,.35),rgba(7,32,63,.22));border-color:rgba(59,130,246,.55)}
.kpi-blue .kpi-label,.kpi-blue .kpi-sub{color:#93c5fd}
.kpi-green{background:linear-gradient(100deg,rgba(20,83,45,.38),rgba(5,46,22,.20));border-color:rgba(34,197,94,.45)}
.kpi-green .kpi-label,.kpi-green .kpi-sub{color:#86efac}
.kpi-purple{background:linear-gradient(100deg,rgba(88,28,135,.42),rgba(59,7,100,.22));border-color:rgba(168,85,247,.55)}
.kpi-purple .kpi-label,.kpi-purple .kpi-sub{color:#d8b4fe}
.vario-help{color:#a1a1aa;font-size:.86rem;margin:-5px 0 14px}
.vario-box{border:1px solid rgba(234,179,8,.45);background:rgba(113,63,18,.13);border-radius:12px;padding:16px 18px;margin-bottom:16px}
.vario-box b{color:#facc15}
</style>
""", unsafe_allow_html=True)
VARIO_HISTORY_START = pd.Timestamp("2025-12-11 00:00:00")
MONTHS_FR = {1:"Janvier",2:"Février",3:"Mars",4:"Avril",5:"Mai",6:"Juin",7:"Juillet",8:"Août",9:"Septembre",10:"Octobre",11:"Novembre",12:"Décembre"}

st.title("Analyse tarifaire Groupe E")
st.caption("Objectif : savoir si VARIO est intéressant, puis mesurer la valeur ajoutée d'une batterie.")

with st.sidebar:
    st.header("1. Données client")
    client = st.text_input("Client / site", value="")
    uploaded = st.file_uploader("Courbe import / export réseau", type=["xlsx","xls","csv"])
    transpose_to_2026 = st.toggle("Utiliser un profil 2025 comme profil 2026", value=True)

    st.header("2. Tarif Double")
    ht_ct = st.number_input("Haut tarif (ct/kWh)", min_value=0.0, value=29.32, step=0.01)
    bt_ct = st.number_input("Bas tarif (ct/kWh)", min_value=0.0, value=19.27, step=0.01)
    st.caption("HT : 07h–12h et 17h–23h. BT : le reste.")

    st.header("3. Batterie")
    capacity = st.number_input("Capacité (kWh)", min_value=1.0, value=10.0, step=1.0)
    power = st.number_input("Puissance (kW)", min_value=0.5, value=5.0, step=0.5)
    efficiency = st.slider("Rendement aller-retour", 0.50, 1.00, 0.92, 0.01)
    soc_min = st.slider("SOC minimum (%)", 0, 50, 5)
    soc_max = st.slider("SOC maximum (%)", 50, 100, 95)
    feed_in_ct = st.number_input("Reprise PV (ct/kWh)", min_value=0.0, value=6.0, step=0.1)
    allow_grid_charge = st.toggle("Autoriser la charge depuis le réseau", value=False)
    wear_ct = st.number_input(
        "Coût d'usure batterie (ct/kWh déchargé)",
        min_value=0.0, value=4.0, step=0.5,
        help="Intégré dans l'optimisation pour éviter les micro-arbitrages peu rentables."
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

original_df = df.copy()
original_start = df.timestamp.min()
profile_transposed = False
if transpose_to_2026 and original_start.year == 2025:
    df = df.copy()
    df["timestamp"] = df["timestamp"].map(lambda x: x.replace(year=2026))
    profile_transposed = True

st.success(f"Fichier reconnu : {meta.vendor} · {meta.n_rows:,} mesures · pas {meta.dt_hours*60:.0f} min · unité {meta.input_unit}")
if profile_transposed:
    st.warning("MODE SIMULATION — Profil 2025 transposé sur 2026 ; prix VARIO réels 2026.")

if not original_df.empty:
    original_prices = double_price_vector(original_df["timestamp"], ht_ct/100, bt_ct/100)
    ht_mask = abs(original_prices - ht_ct/100) < 1e-12
    bt_mask = ~ht_mask

    ht_kwh = float(original_df.loc[ht_mask, "import_kWh"].sum())
    bt_kwh = float(original_df.loc[bt_mask, "import_kWh"].sum())
    total_double_kwh = ht_kwh + bt_kwh

    ht_cost = ht_kwh * ht_ct / 100.0
    bt_cost = bt_kwh * bt_ct / 100.0
    total_double_cost = ht_cost + bt_cost

    ht_share = ht_kwh / total_double_kwh * 100.0 if total_double_kwh > 0 else 0.0
    bt_share = bt_kwh / total_double_kwh * 100.0 if total_double_kwh > 0 else 0.0

    export_total_kwh = float(original_df["export_kWh"].sum()) if "export_kWh" in original_df.columns else 0.0
    export_revenue_chf = export_total_kwh * feed_in_ct / 100.0

    profile_year = int(original_df["timestamp"].dt.year.mode().iloc[0])

    st.subheader(f"Répartition de la consommation {profile_year} — Tarif Double")
    st.caption(
        f"Calcul sur le soutirage réseau du profil original avec les tarifs saisis "
        f"({ht_ct:.2f} ct/kWh HT et {bt_ct:.2f} ct/kWh BT)."
    )

    st.markdown(
        f"""
        <div class="kpi-grid">
          <div class="kpi-card kpi-red">
            <div class="kpi-label">Consommation haut tarif (HT)</div>
            <div class="kpi-value">{ht_kwh:,.0f} kWh</div>
            <div class="kpi-sub">{ht_share:.1f} % du soutirage</div>
          </div>
          <div class="kpi-card kpi-red">
            <div class="kpi-label">Coût haut tarif (HT)</div>
            <div class="kpi-value">{ht_cost:,.2f} CHF</div>
            <div class="kpi-sub">{ht_ct:.2f} ct/kWh</div>
          </div>
          <div class="kpi-card kpi-blue">
            <div class="kpi-label">Consommation bas tarif (BT)</div>
            <div class="kpi-value">{bt_kwh:,.0f} kWh</div>
            <div class="kpi-sub">{bt_share:.1f} % du soutirage</div>
          </div>
          <div class="kpi-card kpi-blue">
            <div class="kpi-label">Coût bas tarif (BT)</div>
            <div class="kpi-value">{bt_cost:,.2f} CHF</div>
            <div class="kpi-sub">{bt_ct:.2f} ct/kWh</div>
          </div>
          <div class="kpi-card kpi-green">
            <div class="kpi-label">Consommation totale</div>
            <div class="kpi-value">{total_double_kwh:,.0f} kWh</div>
            <div class="kpi-sub">HT + BT</div>
          </div>
          <div class="kpi-card kpi-green">
            <div class="kpi-label">Coût total au tarif Double</div>
            <div class="kpi-value">{total_double_cost:,.2f} CHF</div>
            <div class="kpi-sub">HT + BT, hors frais fixes</div>
          </div>
          <div class="kpi-card kpi-purple">
            <div class="kpi-label">Export total (réseau)</div>
            <div class="kpi-value">{export_total_kwh:,.0f} kWh</div>
            <div class="kpi-sub">Énergie injectée sur la période</div>
          </div>
          <div class="kpi-card kpi-purple">
            <div class="kpi-label">Revenus d’injection (reprise PV)</div>
            <div class="kpi-value">{export_revenue_chf:,.2f} CHF</div>
            <div class="kpi-sub">{feed_in_ct:.2f} ct/kWh</div>
          </div>
        </div>
        """.replace(",", " "),
        unsafe_allow_html=True,
    )

if st.button("Lancer l'analyse", type="primary"):
    today = pd.Timestamp.now(tz="Europe/Zurich").tz_localize(None)
    start = max(VARIO_HISTORY_START, df.timestamp.min().floor("15min"))
    end = min(today.ceil("15min"), df.timestamp.max().ceil("15min") + pd.Timedelta(minutes=15))

    with st.spinner("Récupération des prix VARIO..."):
        vario, _ = fetch_vario(start, end)

    data = df.copy()
    data["timestamp"] = data["timestamp"].dt.floor("15min")
    merged = data.merge(vario, on="timestamp", how="inner")
    if merged.empty:
        st.error("Aucune période commune.")
        st.stop()

    base, r = compare_double_vario(
        merged, ht_chf_kwh=ht_ct/100, bt_chf_kwh=bt_ct/100,
        periods=((7,12),(17,23)), weekend_low=False, vat_factor=1.0
    )

    feed_in = feed_in_ct/100
    wear = wear_ct/100
    export_revenue = float(merged.export_kWh.sum()*feed_in)
    double_cost = r["double_chf"] - export_revenue
    vario_cost = r["vario_chf"] - export_revenue
    double_prices = double_price_vector(merged.timestamp, ht_ct/100, bt_ct/100)

    with st.spinner("Optimisation économique de la batterie..."):
        double_bat = optimize_battery(
            merged, double_prices, feed_in, capacity, power, meta.dt_hours,
            efficiency, soc_min, soc_max, False, wear
        )
        vario_pv = optimize_battery(
            merged, merged.vario_chf_kwh.values, feed_in, capacity, power, meta.dt_hours,
            efficiency, soc_min, soc_max, False, wear
        )
        vario_grid = None
        if allow_grid_charge:
            vario_grid = optimize_battery(
                merged, merged.vario_chf_kwh.values, feed_in, capacity, power, meta.dt_hours,
                efficiency, soc_min, soc_max, True, wear
            )

    period_days = len(merged)*meta.dt_hours/24
    annual_factor = 365/period_days if period_days else 0

    st.subheader("1. VARIO seul est-il intéressant ?")
    st.markdown(
        '<div class="vario-help"><b>Tarif Double</b> = votre tarif de référence avec heures HT/BT. '
        '<b>VARIO</b> = le même soutirage du client, sans batterie, mais facturé avec le prix dynamique '
        'Groupe E de chaque quart d’heure.</div>',
        unsafe_allow_html=True,
    )
    gain_vario = double_cost-vario_cost
    c1,c2,c3 = st.columns(3)
    c1.metric("Tarif Double (HT / BT)", f"{double_cost:,.2f} CHF".replace(","," "))
    c2.metric("Tarif VARIO (sans batterie)", f"{vario_cost:,.2f} CHF".replace(","," "))
    c3.metric("Économie en passant à VARIO", f"{gain_vario:,.2f} CHF".replace(","," "), f"{(gain_vario/double_cost*100 if double_cost else 0):+.1f} %")

    st.subheader("2. Que rapporte une batterie chargée avec le surplus PV ?")
    gross_pv = vario_cost-vario_pv.cost_chf
    net_pv = vario_cost-vario_pv.economic_cost_chf
    b1,b2,b3,b4 = st.columns(4)
    b1.metric("VARIO sans batterie", f"{vario_cost:,.2f} CHF".replace(","," "))
    b2.metric("Facture avec batterie", f"{vario_pv.cost_chf:,.2f} CHF".replace(","," "))
    b3.metric("Gain brut batterie", f"{gross_pv:,.2f} CHF".replace(","," "))
    b4.metric("Gain net après usure", f"{net_pv:,.2f} CHF".replace(","," "))
    st.caption(f"Coût d'usure imputé : {vario_pv.wear_cost_chf:,.2f} CHF sur la période.".replace(","," "))

    st.subheader("3. L'arbitrage réseau VARIO vaut-il la peine ?")
    if allow_grid_charge:
        gross_extra = vario_pv.cost_chf-vario_grid.cost_chf
        net_extra = vario_pv.economic_cost_chf-vario_grid.economic_cost_chf
        extra_cycles = vario_grid.cycles-vario_pv.cycles
        a1,a2,a3,a4 = st.columns(4)
        a1.metric("Batterie PV seule", f"{vario_pv.cost_chf:,.2f} CHF".replace(","," "))
        a2.metric("Batterie + arbitrage", f"{vario_grid.cost_chf:,.2f} CHF".replace(","," "))
        a3.metric("Gain brut arbitrage", f"{gross_extra:,.2f} CHF".replace(","," "))
        a4.metric("Gain net arbitrage", f"{net_extra:,.2f} CHF".replace(","," "))
        if net_extra > 0:
            st.success(f"Arbitrage rentable après usure : +{net_extra:,.2f} CHF sur la période, pour {extra_cycles:.0f} cycles supplémentaires.".replace(","," "))
        else:
            st.warning("Avec ce coût d'usure, l'arbitrage réseau n'apporte pas de gain économique supplémentaire.")
        best = vario_grid
    else:
        st.info("Active « Autoriser la charge depuis le réseau » pour tester l'arbitrage.")
        best = vario_pv

    st.divider()
    st.subheader("Résumé décisionnel")
    total_bill_gain = double_cost-best.cost_chf
    total_net_gain = double_cost-best.economic_cost_chf
    s1,s2,s3,s4 = st.columns(4)
    s1.metric("Gain facture période", f"{total_bill_gain:,.0f} CHF".replace(","," "))
    s2.metric("Gain économique net", f"{total_net_gain:,.0f} CHF".replace(","," "))
    s3.metric("Projection nette indicative", f"{total_net_gain*annual_factor:,.0f} CHF/an".replace(","," "))
    s4.metric("Cycles annualisés", f"{best.cycles*annual_factor:.0f}/an")
    st.caption(f"Période analysée : {period_days:.0f} jours. Projection annuelle = annualisation indicative.")

    tab1, tab2, tab3 = st.tabs(["Comparaison mensuelle", "Économie mensuelle", "Pilotage batterie"])
    m = merged[["timestamp","import_kWh","export_kWh","vario_chf_kwh"]].copy()
    m["double"] = merged.import_kWh.values*double_prices - merged.export_kWh.values*feed_in
    m["vario"] = merged.import_kWh.values*merged.vario_chf_kwh.values - merged.export_kWh.values*feed_in
    m["vario_pv"] = vario_pv.import_after*merged.vario_chf_kwh.values - vario_pv.export_after*feed_in
    if allow_grid_charge:
        m["vario_grid"] = vario_grid.import_after*merged.vario_chf_kwh.values - vario_grid.export_after*feed_in

    cols = ["double","vario","vario_pv"] + (["vario_grid"] if allow_grid_charge else [])
    monthly = m.set_index("timestamp")[cols].resample("MS").sum()
    monthly["Mois"] = [MONTHS_FR[x.month] for x in monthly.index]

    with tab1:
        names={"double":"Double","vario":"VARIO","vario_pv":"VARIO + batterie PV","vario_grid":"VARIO + arbitrage"}
        st.bar_chart(monthly.set_index("Mois")[cols].rename(columns=names))
        st.caption("Plus la barre est basse, plus la facture du mois est faible.")

    with tab2:
        savings=pd.DataFrame(index=monthly.index)
        savings["VARIO seul"]=monthly["double"]-monthly["vario"]
        savings["VARIO + batterie PV"]=monthly["double"]-monthly["vario_pv"]
        if allow_grid_charge:
            savings["VARIO + arbitrage"]=monthly["double"]-monthly["vario_grid"]
        savings["Mois"]=[MONTHS_FR[x.month] for x in savings.index]
        st.bar_chart(savings.set_index("Mois"))
        st.caption("Valeur positive = économie par rapport au Double sans batterie.")

    with tab3:
        chosen=best
        detail=pd.DataFrame({
            "timestamp":merged.timestamp,
            "prix_VARIO_ct_kWh":merged.vario_chf_kwh*100,
            "import_avant_kWh":merged.import_kWh,
            "export_avant_kWh":merged.export_kWh,
            "charge_kWh":chosen.charge_kwh,
            "decharge_kWh":chosen.discharge_kwh,
            "SOC_kWh":chosen.soc_kwh,
            "import_apres_kWh":chosen.import_after,
            "export_apres_kWh":chosen.export_after,
        })
        st.dataframe(detail,use_container_width=True,height=430,hide_index=True)


    st.divider()
    st.subheader("Rapport client PDF")
    st.caption(
        "Le rapport reprend uniquement les informations utiles au client : comparaison des solutions, "
        "origine des économies, projection annuelle et hypothèses principales."
    )

    report_monthly = monthly.copy()
    pdf_bytes = generate_vario_report(
        client_name=client,
        period_start=merged.timestamp.min(),
        period_end=merged.timestamp.max(),
        period_days=period_days,
        profile_transposed=profile_transposed,
        capacity_kwh=capacity,
        power_kw=power,
        efficiency=efficiency,
        soc_min=soc_min,
        soc_max=soc_max,
        feed_in_ct=feed_in_ct,
        wear_ct=wear_ct,
        double_cost=double_cost,
        vario_cost=vario_cost,
        vario_pv_bill=vario_pv.cost_chf,
        vario_pv_economic=vario_pv.economic_cost_chf,
        arbitrage_enabled=allow_grid_charge,
        vario_grid_bill=(vario_grid.cost_chf if vario_grid is not None else None),
        vario_grid_economic=(vario_grid.economic_cost_chf if vario_grid is not None else None),
        cycles_annualized=best.cycles*annual_factor,
        monthly_df=report_monthly,
    )

    st.download_button(
        "Télécharger le rapport client PDF",
        pdf_bytes,
        file_name="analyse_vario_client.pdf",
        mime="application/pdf",
        type="primary",
    )

