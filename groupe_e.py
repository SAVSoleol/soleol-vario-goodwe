from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests


GROUPE_E_TARIFF_URL = "https://api.tariffs.groupe-e.ch/v2/tariffs"


@dataclass(frozen=True)
class PriceSlot:
    start: datetime
    end: datetime
    grid_chf_kwh: float | None
    integrated_chf_kwh: float | None


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _first_value(items: list[dict[str, Any]] | None) -> float | None:
    if not items:
        return None
    value = items[0].get("value")
    return float(value) if value is not None else None


def fetch_vario_tariffs(timeout: int = 20) -> tuple[datetime | None, list[PriceSlot], dict[str, Any]]:
    """Récupère les tarifs VARIO Groupe E.

    L'API retourne en principe les 96 quarts d'heure publiés pour le lendemain.
    """
    response = requests.get(GROUPE_E_TARIFF_URL, timeout=timeout)
    response.raise_for_status()
    payload: dict[str, Any] = response.json()

    publication_raw = payload.get("publication_timestamp")
    publication_timestamp = _parse_iso(publication_raw) if publication_raw else None

    slots: list[PriceSlot] = []
    for row in payload.get("prices", []):
        slots.append(
            PriceSlot(
                start=_parse_iso(row["start_timestamp"]),
                end=_parse_iso(row["end_timestamp"]),
                grid_chf_kwh=_first_value(row.get("grid")),
                integrated_chf_kwh=_first_value(row.get("integrated")),
            )
        )

    return publication_timestamp, slots, payload


def slots_to_rows(slots: list[PriceSlot]) -> list[dict[str, Any]]:
    return [
        {
            "start": slot.start,
            "end": slot.end,
            "grid_chf_kwh": slot.grid_chf_kwh,
            "integrated_chf_kwh": slot.integrated_chf_kwh,
        }
        for slot in slots
    ]
