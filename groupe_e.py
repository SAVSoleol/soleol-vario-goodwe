from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

VARIO_URL = "https://api.tariffs.groupe-e.ch/v2/tariffs"
SWISS_TZ = ZoneInfo("Europe/Zurich")


@dataclass(frozen=True)
class TariffSlot:
    start: datetime
    end: datetime
    integrated_chf_kwh: float


def _first_value(items: list[dict[str, Any]], default: float = 0.0) -> float:
    if not items:
        return default
    return float(items[0].get("value", default))


def _parse_payload(payload: dict[str, Any]) -> list[TariffSlot]:
    slots: list[TariffSlot] = []
    for row in payload.get("prices", []):
        slots.append(
            TariffSlot(
                start=datetime.fromisoformat(row["start_timestamp"]),
                end=datetime.fromisoformat(row["end_timestamp"]),
                integrated_chf_kwh=_first_value(row.get("integrated", [])),
            )
        )
    slots.sort(key=lambda s: s.start)
    return slots


def fetch_vario_date_range(
    start_date: date,
    end_date: date,
    *,
    timeout: int = 90,
) -> tuple[str, list[TariffSlot]]:
    """Fetch complete Swiss-local days, inclusive start_date through end_date."""
    if end_date < start_date:
        raise ValueError("La date de fin doit être postérieure ou égale à la date de début.")

    start = datetime.combine(start_date, time.min, tzinfo=SWISS_TZ)
    end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=SWISS_TZ)
    params = {
        "start_timestamp": start.isoformat(),
        "end_timestamp": end.isoformat(),
    }
    response = requests.get(
        VARIO_URL,
        params=params,
        timeout=timeout,
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    return str(payload.get("publication_timestamp", "")), _parse_payload(payload)
