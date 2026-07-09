from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from optimizer import StrategyWindow, window_to_goodwe_data


@dataclass(frozen=True)
class GoodWeConfig:
    base_url: str = "https://openapi.goodwe.com"
    authorization: str = ""
    app_identifier: str = ""
    timeout: int = 30


class GoodWeClient:
    def __init__(self, config: GoodWeConfig):
        self.config = config

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.authorization:
            headers["Authorization"] = self.config.authorization
        if self.config.app_identifier:
            headers["appIdentifier"] = self.config.app_identifier
        return headers

    def create_control_task(self, function_name: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        url = f"{self.config.base_url.rstrip('/')}/goodwe/integration/api/v1/remote/parameter-tasks"
        payload = {"functionName": function_name, "items": items}
        response = requests.post(url, json=payload, headers=self._headers(), timeout=self.config.timeout)
        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}
        return {"status_code": response.status_code, "payload_sent": payload, "response": data}

    def set_ems_third_party_dispatch(self, datalogger_sn: str) -> dict[str, Any]:
        return self.create_control_task(
            "setEmsDispatchMode",
            [{"sn": datalogger_sn, "data": {"dispatchMode": 1}}],
        )

    def send_battery_windows(self, device_sn: str, windows: list[StrategyWindow]) -> list[dict[str, Any]]:
        results = []
        for window in windows:
            results.append(
                self.create_control_task(
                    "BatteryCD",
                    [{"sn": device_sn, "data": window_to_goodwe_data(window)}],
                )
            )
        return results
