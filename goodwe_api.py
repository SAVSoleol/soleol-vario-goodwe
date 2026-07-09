from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from optimizer import DispatchWindow, window_to_goodwe_data


@dataclass
class GoodWeConfig:
    base_url: str = "https://openapi.goodwe.com"
    authorization: str = ""  # Exemple: Bearer xxx ou la valeur exacte demandée par GoodWe
    app_identifier: str = ""  # Optionnel selon votre accès GoodWe
    timeout: int = 30


class GoodWeClient:
    def __init__(self, config: GoodWeConfig):
        self.config = config

    @property
    def headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.authorization:
            headers["Authorization"] = self.config.authorization
        if self.config.app_identifier:
            headers["appIdentifier"] = self.config.app_identifier
        return headers

    def create_control_task(self, function_name: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        url = f"{self.config.base_url.rstrip('/')}/goodwe/integration/api/v1/remote/parameter-tasks"
        payload = {"functionName": function_name, "items": items}
        response = requests.post(url, headers=self.headers, json=payload, timeout=self.config.timeout)
        response.raise_for_status()
        return response.json()

    def set_ems_third_party_dispatch(self, datalogger_sn: str) -> dict[str, Any]:
        return self.create_control_task(
            "setEmsDispatchMode",
            [{"sn": datalogger_sn, "data": {"dispatchMode": 1}}],
        )

    def send_battery_window(self, device_sn: str, window: DispatchWindow) -> dict[str, Any]:
        return self.create_control_task(
            "BatteryCD",
            [{"sn": device_sn, "data": window_to_goodwe_data(window)}],
        )

    def send_battery_windows(self, device_sn: str, windows: list[DispatchWindow]) -> list[dict[str, Any]]:
        results = []
        for window in windows:
            results.append(self.send_battery_window(device_sn, window))
        return results
