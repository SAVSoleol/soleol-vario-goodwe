from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

VARIO_URL = "https://api.tariffs.groupe-e.ch/v2/tariffs"


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


def fetch_vario_tariffs(timeout: int = 20) -> tuple[str, list[TariffSlot], dict[str, Any]]:
    """Fetch the currently published Groupe E VARIO 15-minute tariffs."""
    response = requests.get(VARIO_URL, timeout=timeout, headers={"Accept": "application/json"})
    response.raise_for_status()
    payload: dict[str, Any] = response.json()

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
    return str(payload.get("publication_timestamp", "")), slots, payload


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
