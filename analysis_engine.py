from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd


@dataclass(frozen=True)
class ComparisonResult:
    double_cost_chf: float
    vario_cost_chf: float
    saving_chf: float
    saving_pct: float
    consumption_kwh: float
    avg_double_ct_kwh: float
    avg_vario_ct_kwh: float


def is_double_high_tariff(ts: datetime) -> bool:
    """HT windows used by the app: 07:00-12:00 and 17:00-23:00."""
    minutes = ts.hour * 60 + ts.minute
    return (7 * 60 <= minutes < 12 * 60) or (17 * 60 <= minutes < 23 * 60)


def compare(df: pd.DataFrame, high_ct: float, low_ct: float) -> tuple[ComparisonResult, pd.DataFrame]:
    data = df.copy()
    data["double_ct_kwh"] = data["timestamp"].apply(
        lambda x: high_ct if is_double_high_tariff(x.to_pydatetime()) else low_ct
    )
    data["double_cost_chf"] = data["consumption_kwh"] * data["double_ct_kwh"] / 100.0
    data["vario_cost_chf"] = data["consumption_kwh"] * data["vario_chf_kwh"]

    consumption = float(data["consumption_kwh"].sum())
    double_cost = float(data["double_cost_chf"].sum())
    vario_cost = float(data["vario_cost_chf"].sum())
    saving = double_cost - vario_cost
    saving_pct = (saving / double_cost * 100.0) if double_cost else 0.0

    result = ComparisonResult(
        double_cost_chf=double_cost,
        vario_cost_chf=vario_cost,
        saving_chf=saving,
        saving_pct=saving_pct,
        consumption_kwh=consumption,
        avg_double_ct_kwh=(double_cost / consumption * 100.0) if consumption else 0.0,
        avg_vario_ct_kwh=(vario_cost / consumption * 100.0) if consumption else 0.0,
    )
    return result, data


def monthly_summary(detail: pd.DataFrame) -> pd.DataFrame:
    m = detail.copy()
    m["month"] = m["timestamp"].dt.tz_localize(None).dt.to_period("M").astype(str)
    out = (
        m.groupby("month", as_index=False)
        .agg(
            consommation_kWh=("consumption_kwh", "sum"),
            tarif_Double_CHF=("double_cost_chf", "sum"),
            tarif_VARIO_CHF=("vario_cost_chf", "sum"),
        )
    )
    out["economie_CHF"] = out["tarif_Double_CHF"] - out["tarif_VARIO_CHF"]
    out["economie_pct"] = out.apply(
        lambda r: (r["economie_CHF"] / r["tarif_Double_CHF"] * 100.0) if r["tarif_Double_CHF"] else 0.0,
        axis=1,
    )
    return out
