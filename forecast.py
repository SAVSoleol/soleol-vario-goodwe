from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import exp
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class ForecastSlot:
    start: datetime
    end: datetime
    pv_kwh: float
    load_kwh: float


def _normalise(values: list[float]) -> list[float]:
    total = sum(max(0.0, v) for v in values)
    if total <= 0:
        return [0.0 for _ in values]
    return [max(0.0, v) / total for v in values]


def synthetic_forecast(
    tariff_slots: Iterable,
    *,
    pv_energy_kwh: float,
    load_energy_kwh: float,
    pv_peak_hour: float = 13.0,
    pv_spread_hours: float = 3.0,
    morning_share: float = 0.25,
    evening_share: float = 0.45,
) -> list[ForecastSlot]:
    """Create a simple 15-minute PV/load forecast aligned with tariff slots.

    This is deliberately transparent and deterministic. It is suitable for a
    first pilot before connecting a real weather or consumption forecast API.
    """
    slots = list(tariff_slots)
    if not slots:
        return []

    pv_shape: list[float] = []
    load_shape: list[float] = []
    for slot in slots:
        midpoint = slot.start + (slot.end - slot.start) / 2
        h = midpoint.hour + midpoint.minute / 60

        # Bell curve around solar noon, clipped at night.
        daylight = 6.0 <= h <= 21.0
        pv_shape.append(exp(-0.5 * ((h - pv_peak_hour) / max(pv_spread_hours, 0.5)) ** 2) if daylight else 0.0)

        # Residential-like profile: base + morning + evening peaks.
        base = 0.35
        morning = morning_share * exp(-0.5 * ((h - 7.5) / 1.5) ** 2)
        evening = evening_share * exp(-0.5 * ((h - 19.0) / 2.2) ** 2)
        daytime = max(0.0, 1.0 - morning_share - evening_share) * exp(-0.5 * ((h - 13.0) / 4.0) ** 2)
        load_shape.append(base + morning + evening + daytime)

    pv_weights = _normalise(pv_shape)
    load_weights = _normalise(load_shape)

    return [
        ForecastSlot(
            start=s.start,
            end=s.end,
            pv_kwh=round(max(0.0, pv_energy_kwh) * pv_weights[i], 6),
            load_kwh=round(max(0.0, load_energy_kwh) * load_weights[i], 6),
        )
        for i, s in enumerate(slots)
    ]


def forecast_from_dataframe(df: pd.DataFrame, tariff_slots: Iterable) -> list[ForecastSlot]:
    """Read a user-provided forecast dataframe.

    Required columns: timestamp, pv_kwh, load_kwh. Timestamps are matched to the
    beginning of each tariff slot.
    """
    required = {"timestamp", "pv_kwh", "load_kwh"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Colonnes manquantes: {', '.join(sorted(missing))}")

    data = df.copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"], errors="raise")
    mapping = {
        ts.to_pydatetime(): (float(pv), float(load))
        for ts, pv, load in zip(data["timestamp"], data["pv_kwh"], data["load_kwh"])
    }

    out: list[ForecastSlot] = []
    for s in tariff_slots:
        key = s.start
        if key not in mapping:
            raise ValueError(f"Prévision absente pour {key.isoformat()}")
        pv, load = mapping[key]
        out.append(ForecastSlot(s.start, s.end, max(0.0, pv), max(0.0, load)))
    return out


def forecast_to_rows(forecast: list[ForecastSlot]) -> list[dict[str, object]]:
    return [
        {"start": x.start, "end": x.end, "pv_kwh": x.pv_kwh, "load_kwh": x.load_kwh}
        for x in forecast
    ]
