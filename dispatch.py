from __future__ import annotations

from datetime import datetime, timezone

from optimizer import StrategyWindow


def _to_utc_seconds(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.astimezone(timezone.utc).timestamp())


def window_to_goodwe_data(window: StrategyWindow) -> dict[str, int]:
    mode = {"idle": 1, "charge": 2, "discharge": 3}[window.action]
    return {
        "BatteryCDEnable": 1,
        "BatteryCDMode": mode,
        "BatteryCDPW": int(round(window.power_kw * 1000)),
        "BatteryCDTargetSOC": int(window.target_soc),
        "CDStartTime": _to_utc_seconds(window.start),
        "CDEndTime": _to_utc_seconds(window.end),
    }


def window_payload(device_sn: str, window: StrategyWindow) -> dict[str, object]:
    return {
        "functionName": "BatteryCD",
        "items": [{"sn": device_sn, "data": window_to_goodwe_data(window)}],
    }
