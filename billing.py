
"""Double vs VARIO billing engine."""
from __future__ import annotations
import numpy as np
import pandas as pd


def high_tariff_mask(
    timestamps,
    periods=((7.0, 12.0), (17.0, 23.0)),
    weekend_low=False,
):
    idx = pd.DatetimeIndex(pd.to_datetime(timestamps))
    out = np.zeros(len(idx), dtype=bool)
    for i, ts in enumerate(idx):
        if weekend_low and ts.weekday() >= 5:
            continue
        h = ts.hour + ts.minute / 60.0
        for start, end in periods:
            if start <= end:
                if start <= h < end:
                    out[i] = True
                    break
            elif h >= start or h < end:
                out[i] = True
                break
    return out


def compare_double_vario(
    merged: pd.DataFrame,
    ht_chf_kwh: float,
    bt_chf_kwh: float,
    periods=((7.0, 12.0), (17.0, 23.0)),
    weekend_low=False,
    vat_factor=1.0,
) -> tuple[pd.DataFrame, dict]:
    x = merged.copy()
    mask = high_tariff_mask(x["timestamp"], periods=periods, weekend_low=weekend_low)
    x["double_tariff_chf_kwh"] = np.where(mask, float(ht_chf_kwh), float(bt_chf_kwh))
    x["double_cost_chf"] = x["import_kWh"] * x["double_tariff_chf_kwh"] * vat_factor
    x["vario_cost_chf"] = x["import_kWh"] * x["vario_chf_kwh"] * vat_factor

    double = float(x["double_cost_chf"].sum())
    vario = float(x["vario_cost_chf"].sum())
    saving = double - vario
    pct = saving / double * 100.0 if double > 0 else 0.0

    energy = float(x["import_kWh"].sum())
    avg_double = double / energy if energy > 0 else 0.0
    avg_vario = vario / energy if energy > 0 else 0.0

    return x, {
        "double_chf": double,
        "vario_chf": vario,
        "saving_chf": saving,
        "saving_pct": pct,
        "energy_kwh": energy,
        "avg_double_chf_kwh": avg_double,
        "avg_vario_chf_kwh": avg_vario,
    }
