
"""Groupe E VARIO API client, standalone."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import requests

VARIO_URL = "https://api.tariffs.groupe-e.ch/v2/tariffs"


def fetch_vario(start: pd.Timestamp, end: pd.Timestamp, timeout: int = 90) -> tuple[pd.DataFrame, str]:
    """Fetch VARIO integrated 15-minute prices for [start, end).

    Returned timestamps are naive Europe/Zurich local times to align with meter files.
    """
    # Swiss local timezone, including DST.
    # `ambiguous="infer"` only works on a sequence around the DST transition.
    # Here start/end are individual timestamps, so localize them explicitly.
    def _zurich_localize(value):
        ts = pd.Timestamp(value)
        if ts.tzinfo is not None:
            return ts.tz_convert("Europe/Zurich")
        try:
            return ts.tz_localize("Europe/Zurich", ambiguous=False, nonexistent="shift_forward")
        except TypeError:
            return ts.tz_localize("Europe/Zurich")

    start_z = _zurich_localize(start)
    end_z = _zurich_localize(end)

    params = {
        "start_timestamp": start_z.isoformat(),
        "end_timestamp": end_z.isoformat(),
    }
    r = requests.get(VARIO_URL, params=params, headers={"Accept": "application/json"}, timeout=timeout)
    r.raise_for_status()
    payload: dict[str, Any] = r.json()

    rows = []
    for item in payload.get("prices", []):
        integrated = item.get("integrated") or []
        if not integrated:
            continue
        ts = pd.to_datetime(item["start_timestamp"], utc=True)
        ts = ts.tz_convert("Europe/Zurich").tz_localize(None)
        rows.append(
            {
                "timestamp": ts,
                "vario_chf_kwh": float(integrated[0].get("value", 0.0)),
            }
        )

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("timestamp").reset_index(drop=True)

    return df, str(payload.get("publication_timestamp", ""))
