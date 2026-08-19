from __future__ import annotations

from collections import defaultdict
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


def _shapes(slots: list) -> tuple[list[float], list[float]]:
    pv_shape: list[float] = []
    load_shape: list[float] = []
    for slot in slots:
        midpoint = slot.start + (slot.end - slot.start) / 2
        h = midpoint.hour + midpoint.minute / 60
        daylight = 6.0 <= h <= 21.0
        pv_shape.append(exp(-0.5 * ((h - 13.0) / 3.0) ** 2) if daylight else 0.0)
        base = 0.35
        morning = 0.25 * exp(-0.5 * ((h - 7.5) / 1.5) ** 2)
        evening = 0.45 * exp(-0.5 * ((h - 19.0) / 2.2) ** 2)
        daytime = 0.30 * exp(-0.5 * ((h - 13.0) / 4.0) ** 2)
        load_shape.append(base + morning + evening + daytime)
    return pv_shape, load_shape


def synthetic_forecast(
    tariff_slots: Iterable,
    *,
    pv_energy_kwh: float,
    load_energy_kwh: float,
    per_day: bool = False,
) -> list[ForecastSlot]:
    """Create a deterministic PV/load profile aligned with tariff slots.

    If per_day=True, pv_energy_kwh and load_energy_kwh are interpreted as daily
    energies and are independently distributed over each local calendar day.
    """
    slots = list(tariff_slots)
    if not slots:
        return []

    if not per_day:
        pv_shape, load_shape = _shapes(slots)
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

    by_day: dict[object, list] = defaultdict(list)
    for s in slots:
        by_day[s.start.date()].append(s)

    result: list[ForecastSlot] = []
    for day in sorted(by_day):
        day_slots = by_day[day]
        pv_shape, load_shape = _shapes(day_slots)
        pv_weights = _normalise(pv_shape)
        load_weights = _normalise(load_shape)
        for i, s in enumerate(day_slots):
            result.append(
                ForecastSlot(
                    start=s.start,
                    end=s.end,
                    pv_kwh=round(max(0.0, pv_energy_kwh) * pv_weights[i], 6),
                    load_kwh=round(max(0.0, load_energy_kwh) * load_weights[i], 6),
                )
            )
    return result


def forecast_from_dataframe(df: pd.DataFrame, tariff_slots: Iterable) -> list[ForecastSlot]:
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
    return [{"start": x.start, "end": x.end, "pv_kwh": x.pv_kwh, "load_kwh": x.load_kwh} for x in forecast]
