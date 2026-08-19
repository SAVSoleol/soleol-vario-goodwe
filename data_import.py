from __future__ import annotations

import io
from zoneinfo import ZoneInfo

import pandas as pd

SWISS_TZ = ZoneInfo("Europe/Zurich")


def read_csv_flexible(raw: bytes) -> pd.DataFrame:
    errors: list[str] = []
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError as exc:
            errors.append(str(exc))
            continue
        for decimal in (".", ","):
            try:
                df = pd.read_csv(io.StringIO(text), sep=None, engine="python", decimal=decimal)
                if len(df.columns) >= 2:
                    return df
            except Exception as exc:
                errors.append(str(exc))
    raise ValueError("Impossible de lire le CSV. Vérifie le séparateur et l'encodage.")


def prepare_consumption(
    df: pd.DataFrame,
    *,
    timestamp_col: str,
    value_col: str,
    unit: str,
) -> pd.DataFrame:
    data = df[[timestamp_col, value_col]].copy()
    data.columns = ["timestamp", "value"]

    data["timestamp"] = pd.to_datetime(data["timestamp"], errors="coerce", dayfirst=True)
    data["value"] = pd.to_numeric(data["value"], errors="coerce")
    data = data.dropna(subset=["timestamp", "value"]).sort_values("timestamp")
    if data.empty:
        raise ValueError("Aucune ligne valide après lecture du timestamp et de la consommation.")

    # Localize naive timestamps to Switzerland; convert aware timestamps to Switzerland.
    if data["timestamp"].dt.tz is None:
        data["timestamp"] = data["timestamp"].dt.tz_localize(
            SWISS_TZ, ambiguous="infer", nonexistent="shift_forward"
        )
    else:
        data["timestamp"] = data["timestamp"].dt.tz_convert(SWISS_TZ)

    data = data.drop_duplicates(subset=["timestamp"], keep="last")

    # Determine representative time step for power-to-energy conversions.
    diffs_h = data["timestamp"].diff().dt.total_seconds().dropna() / 3600.0
    step_h = float(diffs_h.median()) if not diffs_h.empty else 0.25
    if step_h <= 0 or step_h > 24:
        step_h = 0.25

    if unit == "kWh par intervalle":
        data["consumption_kwh"] = data["value"]
    elif unit == "Wh par intervalle":
        data["consumption_kwh"] = data["value"] / 1000.0
    elif unit == "kW (puissance moyenne)":
        data["consumption_kwh"] = data["value"] * step_h
    elif unit == "W (puissance moyenne)":
        data["consumption_kwh"] = data["value"] / 1000.0 * step_h
    else:
        raise ValueError(f"Unité inconnue : {unit}")

    data = data[data["consumption_kwh"] >= 0].copy()
    # The tariff API is quarter-hourly. Aggregate onto the same 15-min grid.
    data = (
        data.set_index("timestamp")[["consumption_kwh"]]
        .resample("15min")
        .sum()
        .reset_index()
    )
    return data
