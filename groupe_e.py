from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import requests

VARIO_URL = "https://api.tariffs.groupe-e.ch/v2/tariffs"
SWISS_TZ = ZoneInfo("Europe/Zurich")


@dataclass(frozen=True)
class TariffSlot:
    start: datetime
    end: datetime
    grid_chf_kwh: float
    integrated_chf_kwh: float


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _first_value(items: list[dict[str, Any]], default: float = 0.0) -> float:
    if not items:
        return default
    return float(items[0].get("value", default))


def _parse_payload(payload: dict[str, Any]) -> list[TariffSlot]:
    slots: list[TariffSlot] = []
    for row in payload.get("prices", []):
        slots.append(
            TariffSlot(
                start=_parse_dt(row["start_timestamp"]),
                end=_parse_dt(row["end_timestamp"]),
                grid_chf_kwh=_first_value(row.get("grid", [])),
                integrated_chf_kwh=_first_value(row.get("integrated", [])),
            )
        )
    slots.sort(key=lambda s: s.start)
    return slots


def fetch_vario_tariffs(
    timeout: int = 20,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> tuple[str, list[TariffSlot], dict[str, Any]]:
    """Fetch Groupe E VARIO tariffs, optionally over a historical interval."""
    params: dict[str, str] = {}
    if start is not None:
        if start.tzinfo is None:
            start = start.replace(tzinfo=SWISS_TZ)
        params["start_timestamp"] = start.isoformat()
    if end is not None:
        if end.tzinfo is None:
            end = end.replace(tzinfo=SWISS_TZ)
        params["end_timestamp"] = end.isoformat()

    response = requests.get(
        VARIO_URL,
        params=params or None,
        timeout=timeout,
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    slots = _parse_payload(payload)
    return str(payload.get("publication_timestamp", "")), slots, payload


def fetch_vario_date_range(
    start_date: date,
    end_date: date,
    *,
    timeout: int = 60,
) -> tuple[str, list[TariffSlot], dict[str, Any]]:
    """Fetch complete local days, inclusive start_date through end_date."""
    if end_date < start_date:
        raise ValueError("La date de fin doit être postérieure ou égale à la date de début.")
    start = datetime.combine(start_date, time.min, tzinfo=SWISS_TZ)
    # end is exclusive: midnight after end_date
    from datetime import timedelta
    end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=SWISS_TZ)
    return fetch_vario_tariffs(timeout=timeout, start=start, end=end)


def slots_to_rows(slots: list[TariffSlot]) -> list[dict[str, Any]]:
    return [
        {
            "start": s.start,
            "end": s.end,
            "grid_chf_kwh": s.grid_chf_kwh,
            "integrated_chf_kwh": s.integrated_chf_kwh,
        }
        for s in slots
    ]
