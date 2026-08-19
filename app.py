
from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from billing import compare_double_vario
from groupe_e_api import fetch_vario
from meter_loader import load_consumption_file

st.set_page_config(page_title="Soleol — Double vs VARIO", layout="wide")

VARIO_HISTORY_START = pd.Timestamp("2025-12-11 00:00:00")

st.markdown("""
<style>
.block-container {max-width: 1450px; padding-top: 2rem;}
.result-card {
    border: 1px solid rgba(148,163,184,.22);
    border-radius: 16px;
    padding: 20px 24px;
    background: rgba(15,23,42,.32);
}
.big-result {
    font-size: 2.4rem;
    font-weight: 800;
    margin-top: .2rem;
}
.muted {color:#94a3b8;}
</style>
""", unsafe_allow_html=True)

st.title("Analyse tarifaire Groupe E")
st.caption("Combien ce client aurait-il économisé avec VARIO plutôt qu'avec le tarif Double ?")

with st.sidebar:
    st.header("1. Client")
    client = st.text_input("Client / site", value="")
    uploaded = st.file_uploader(
        "Courbe de soutirage réseau",
        type=["xlsx", "xls", "csv"],
        help="Le programme détecte automatiquement les colonnes, l'unité et le pas de temps.",
    )

    st.header("2. Tarif Double")
    st.caption("Prix variables à comparer au prix VARIO intégré. Frais fixes identiques exclus.")
    ht_ct = st.number_input("Haut tarif (ct/kWh)", min_value=0.0, value=29.32, step=0.01, format="%.2f")
    bt_ct = st.number_input("Bas tarif (ct/kWh)", min_value=0.0, value=19.27, step=0.01, format="%.2f")
    st.caption("HT : 07h–12h et 17h–23h. BT : le reste.")
    vat = st.toggle("Ajouter TVA 8.1 % aux deux scénarios", value=False)

    with st.expander("Options avancées"):
        unit = st.selectbox("Forcer l'unité", ["auto", "kW", "kWh", "W", "Wh"], index=0)
        st.caption("Laisser « auto » dans la grande majorité des cas.")

if uploaded is None:
    st.info("Importe la courbe de soutirage réseau du client pour lancer l'analyse.")
    st.stop()

@st.cache_data(show_spinner=False)
def load_cached(name: str, raw: bytes, unit: str):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / name
        p.write_bytes(raw)
        return load_consumption_file(p, forced_unit=unit)

try:
    load_df, meta = load_cached(uploaded.name, uploaded.getvalue(), unit)
except Exception as exc:
    st.error(f"Fichier non reconnu : {exc}")
    st.stop()

st.success(
    f"Fichier reconnu automatiquement : {meta.vendor} · "
    f"{meta.n_rows:,} mesures · pas {meta.dt_hours*60:.0f} min · unité {meta.input_unit}"
)

with st.expander("Détails de détection"):
    st.write(f"**Colonne date/heure :** {meta.date_column}")
    st.write(f"**Colonne soutirage :** {meta.import_column}")
    st.write(f"**Convention horodatage :** {meta.timestamp_convention}")
    st.write(
        f"**Période du fichier :** {load_df.timestamp.min():%d.%m.%Y %H:%M} → "
        f"{load_df.timestamp.max():%d.%m.%Y %H:%M}"
    )
    st.write(f"**Soutirage total du fichier :** {load_df.import_kWh.sum():,.0f} kWh".replace(",", " "))

preview = load_df.head(8).copy()
preview["timestamp"] = preview["timestamp"].dt.strftime("%d.%m.%Y %H:%M")
with st.expander("Aperçu des mesures"):
    st.dataframe(preview, use_container_width=True, hide_index=True)

if st.button("Comparer Double vs VARIO", type="primary"):
    # Historical API window: always request from the known beginning of available history
    # up to today, but never beyond the client's own data range.
    today = pd.Timestamp.now(tz="Europe/Zurich").tz_localize(None)
    client_start = load_df["timestamp"].min().floor("15min")
    client_end = load_df["timestamp"].max().ceil("15min") + pd.Timedelta(minutes=15)

    api_start = max(VARIO_HISTORY_START, client_start)
    api_end = min(today.ceil("15min"), client_end)

    if api_end <= api_start:
        st.error(
            "Le fichier client ne chevauche pas encore l'historique VARIO disponible "
            "depuis le 11.12.2025."
        )
        st.stop()

    with st.spinner("Récupération de tout l'historique VARIO disponible..."):
        try:
            vario, publication = fetch_vario(api_start, api_end)
        except Exception as exc:
            st.error(f"API Groupe E : {exc}")
            st.stop()

    if vario.empty:
        st.error("Aucun prix VARIO n'est disponible pour la période commune.")
        st.stop()

    data = load_df.copy()
    data["timestamp"] = data["timestamp"].dt.floor("15min")
    merged = data.merge(vario, on="timestamp", how="inner")

    if merged.empty:
        st.error("Aucun quart d'heure commun entre le profil client et les prix VARIO disponibles.")
        st.stop()

    calc, r = compare_double_vario(
        merged,
        ht_chf_kwh=ht_ct / 100.0,
        bt_chf_kwh=bt_ct / 100.0,
        periods=((7.0, 12.0), (17.0, 23.0)),
        weekend_low=False,
        vat_factor=1.081 if vat else 1.0,
    )

    # Coverage is assessed only on the period that could theoretically be compared,
    # not on the entire customer file if it starts before 11 Dec 2025.
    theoretical = data[
        (data["timestamp"] >= api_start) &
        (data["timestamp"] < api_end)
    ]
    comparable_points = len(calc)
    theoretical_points = len(theoretical)
    coverage = comparable_points / theoretical_points * 100.0 if theoretical_points else 0.0
    compared_days = comparable_points * meta.dt_hours / 24.0

    st.subheader("Résultat cumulé")
    c1, c2, c3 = st.columns(3)
    c1.metric("Tarif Double", f"{r['double_chf']:,.2f} CHF".replace(",", " "))
    c2.metric("Tarif VARIO", f"{r['vario_chf']:,.2f} CHF".replace(",", " "))
    c3.metric(
        "Économie VARIO",
        f"{r['saving_chf']:,.2f} CHF".replace(",", " "),
        f"{r['saving_pct']:+.1f} %",
    )

    if r["saving_chf"] >= 0:
        st.success(
            f"Sur toute la période comparable, "
            f"**{client or 'ce client'} aurait économisé {r['saving_chf']:,.2f} CHF "
            f"({r['saving_pct']:.1f} %) avec VARIO**.".replace(",", " ")
        )
    else:
        st.warning(
            f"Sur toute la période comparable, "
            f"**VARIO aurait coûté {abs(r['saving_chf']):,.2f} CHF de plus "
            f"({abs(r['saving_pct']):.1f} %) à {client or 'ce client'}**.".replace(",", " ")
        )

    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Consommation comparée", f"{r['energy_kwh']:,.0f} kWh".replace(",", " "))
    q2.metric("Prix moyen Double", f"{r['avg_double_chf_kwh']*100:.2f} ct/kWh")
    q3.metric("Prix moyen VARIO", f"{r['avg_vario_chf_kwh']*100:.2f} ct/kWh")
    q4.metric("Couverture période comparable", f"{coverage:.1f} %")

    st.info(
        f"Historique VARIO utilisé : **{calc.timestamp.min():%d.%m.%Y} → "
        f"{calc.timestamp.max():%d.%m.%Y}** · environ **{compared_days:.0f} jours**. "
        "Cette période s'allonge automatiquement à mesure que de nouveaux prix VARIO sont publiés."
    )

    if coverage < 99:
        st.warning(
            "Il manque certains quarts d'heure dans la période théoriquement comparable. "
            "Le résultat est calculé uniquement sur les intervalles réellement disponibles."
        )

    # Monthly detail
    monthly = (
        calc.set_index("timestamp")
        .assign(
            energy_kwh=calc.set_index("timestamp")["import_kWh"],
            expected_slot=1,
        )
        .resample("MS")
        .agg(
            consommation_kWh=("energy_kwh", "sum"),
            double_CHF=("double_cost_chf", "sum"),
            vario_CHF=("vario_cost_chf", "sum"),
            points=("expected_slot", "sum"),
        )
    )

    monthly["economie_CHF"] = monthly["double_CHF"] - monthly["vario_CHF"]
    monthly["economie_pct"] = (
        monthly["economie_CHF"] / monthly["double_CHF"].replace(0, pd.NA) * 100
    )

    # Expected interval count for each calendar month, clipped to the actual comparison window.
    comp_start = calc["timestamp"].min()
    comp_end_exclusive = calc["timestamp"].max() + pd.Timedelta(minutes=15)

    expected_counts = []
    statuses = []
    for month_start in monthly.index:
        month_end = month_start + pd.offsets.MonthBegin(1)
        start_clip = max(month_start, comp_start)
        end_clip = min(month_end, comp_end_exclusive)
        expected = max(0, int(round((end_clip - start_clip).total_seconds() / (meta.dt_hours * 3600))))
        expected_counts.append(expected)

        full_calendar_month = (start_clip == month_start) and (end_clip == month_end)
        actual = int(monthly.loc[month_start, "points"])
        cov = actual / expected * 100.0 if expected else 0.0

        if full_calendar_month and cov >= 99.5:
            statuses.append("Complet")
        elif cov >= 99.5:
            statuses.append("Partiel (début/fin période)")
        else:
            statuses.append(f"Incomplet ({cov:.1f} %)")

    monthly["points_attendus"] = expected_counts
    monthly["couverture_pct"] = monthly["points"] / monthly["points_attendus"].replace(0, pd.NA) * 100
    monthly["statut"] = statuses

    st.subheader("Comparaison mois par mois")

    chart = monthly[["double_CHF", "vario_CHF"]].rename(
        columns={"double_CHF": "Tarif Double", "vario_CHF": "Tarif VARIO"}
    )
    st.bar_chart(chart)

    st.subheader("Économie VARIO par mois")
    st.bar_chart(monthly[["economie_CHF"]].rename(columns={"economie_CHF": "Économie VARIO (CHF)"}))

    display = monthly[
        [
            "consommation_kWh",
            "double_CHF",
            "vario_CHF",
            "economie_CHF",
            "economie_pct",
            "couverture_pct",
            "statut",
        ]
    ].copy()
    display.index = display.index.strftime("%m.%Y")
    display = display.rename(
        columns={
            "consommation_kWh": "Consommation (kWh)",
            "double_CHF": "Double (CHF)",
            "vario_CHF": "VARIO (CHF)",
            "economie_CHF": "Économie (CHF)",
            "economie_pct": "Économie (%)",
            "couverture_pct": "Couverture (%)",
            "statut": "Statut",
        }
    )
    st.dataframe(display.round(2), use_container_width=True)

    st.caption(
        "« Complet » signifie que tout le mois civil est couvert. "
        "Le premier mois (décembre 2025) et le mois courant sont normalement indiqués comme partiels."
    )

    prices = calc.set_index("timestamp")[["double_tariff_chf_kwh", "vario_chf_kwh"]] * 100
    prices.columns = ["Double (ct/kWh)", "VARIO (ct/kWh)"]
    with st.expander("Voir les prix appliqués"):
        st.line_chart(prices)

    with st.expander("Contrôle quart d'heure"):
        detail = calc[
            [
                "timestamp",
                "import_kWh",
                "double_tariff_chf_kwh",
                "vario_chf_kwh",
                "double_cost_chf",
                "vario_cost_chf",
            ]
        ].copy()
        detail["double_tariff_chf_kwh"] *= 100
        detail["vario_chf_kwh"] *= 100
        detail = detail.rename(
            columns={
                "double_tariff_chf_kwh": "Double ct/kWh",
                "vario_chf_kwh": "VARIO ct/kWh",
            }
        )
        st.dataframe(detail, use_container_width=True, height=420, hide_index=True)
