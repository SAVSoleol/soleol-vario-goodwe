from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from groupe_e import PriceSlot

Action = Literal["charge", "discharge"]


@dataclass(frozen=True)
class DispatchWindow:
    action: Action
    start: datetime
    end: datetime
    power_w: int
    target_soc: int
    avg_price_chf_kwh: float
    slots_count: int


def _price(slot: PriceSlot, price_field: str) -> float:
    value = getattr(slot, price_field)
    if value is None:
        raise ValueError(f"Prix manquant pour {price_field} à {slot.start}")
    return float(value)


def _merge_consecutive(action: Action, selected: list[PriceSlot], power_w: int, target_soc: int, price_field: str) -> list[DispatchWindow]:
    if not selected:
        return []

    selected = sorted(selected, key=lambda s: s.start)
    windows: list[DispatchWindow] = []
    group: list[PriceSlot] = [selected[0]]

    for slot in selected[1:]:
        if slot.start == group[-1].end:
            group.append(slot)
        else:
            prices = [_price(s, price_field) for s in group]
            windows.append(
                DispatchWindow(action, group[0].start, group[-1].end, power_w, target_soc, sum(prices) / len(prices), len(group))
            )
            group = [slot]

    prices = [_price(s, price_field) for s in group]
    windows.append(DispatchWindow(action, group[0].start, group[-1].end, power_w, target_soc, sum(prices) / len(prices), len(group)))
    return windows


def build_simple_strategy(
    slots: list[PriceSlot],
    battery_capacity_kwh: float,
    charge_power_kw: float,
    discharge_power_kw: float,
    charge_target_soc: int = 95,
    discharge_target_soc: int = 20,
    soc_min: int = 20,
    soc_start: int = 50,
    price_field: str = "integrated_chf_kwh",
    roundtrip_efficiency: float = 0.92,
) -> list[DispatchWindow]:
    """Stratégie simple : charge sur les prix les plus bas, décharge sur les prix les plus hauts.

    Hypothèse de premier prototype : pas encore de prévision PV/conso.
    """
    if not slots:
        return []
    if charge_power_kw <= 0 or discharge_power_kw <= 0 or battery_capacity_kwh <= 0:
        raise ValueError("Capacité et puissances doivent être positives.")

    usable_charge_kwh = max(0.0, battery_capacity_kwh * (charge_target_soc - soc_start) / 100)
    usable_discharge_kwh = max(0.0, battery_capacity_kwh * (charge_target_soc - soc_min) / 100 * roundtrip_efficiency)

    charge_slots_count = max(1, round(usable_charge_kwh / (charge_power_kw * 0.25)))
    discharge_slots_count = max(1, round(usable_discharge_kwh / (discharge_power_kw * 0.25)))

    sorted_low = sorted(slots, key=lambda s: _price(s, price_field))
    charge_slots = sorted_low[: min(charge_slots_count, len(slots))]

    charge_set = {s.start for s in charge_slots}
    remaining = [s for s in slots if s.start not in charge_set]
    sorted_high = sorted(remaining, key=lambda s: _price(s, price_field), reverse=True)
    discharge_slots = sorted_high[: min(discharge_slots_count, len(sorted_high))]

    windows = []
    windows.extend(_merge_consecutive("charge", charge_slots, int(charge_power_kw * 1000), charge_target_soc, price_field))
    windows.extend(_merge_consecutive("discharge", discharge_slots, int(discharge_power_kw * 1000), discharge_target_soc, price_field))
    return sorted(windows, key=lambda w: w.start)


def window_to_goodwe_data(window: DispatchWindow) -> dict[str, int]:
    mode = 2 if window.action == "charge" else 3
    return {
        "BatteryCDEnable": 1,
        "BatteryCDMode": mode,
        "BatteryCDPW": window.power_w,
        "BatteryCDTargetSOC": window.target_soc,
        "CDStartTime": int(window.start.timestamp()),
        "CDEndTime": int(window.end.timestamp()),
    }
