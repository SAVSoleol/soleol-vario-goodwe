from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from groupe_e import TariffSlot

Action = Literal["charge", "discharge", "idle"]


@dataclass(frozen=True)
class StrategyWindow:
    action: Action
    start: datetime
    end: datetime
    power_w: int
    target_soc: int
    avg_price_chf_kwh: float
    slots_count: int
    energy_kwh: float


@dataclass(frozen=True)
class StrategyResult:
    windows: list[StrategyWindow]
    estimated_arbitrage_gain_chf: float
    charged_energy_kwh: float
    discharged_energy_kwh: float
    avg_charge_price: float
    avg_discharge_price: float


def _price(slot: TariffSlot, field: str) -> float:
    return float(getattr(slot, field))


def _group_contiguous(action: Action, selected: list[TariffSlot], power_kw: float, target_soc: int, price_field: str) -> list[StrategyWindow]:
    if not selected:
        return []
    selected = sorted(selected, key=lambda s: s.start)
    groups: list[list[TariffSlot]] = [[selected[0]]]
    for slot in selected[1:]:
        if slot.start == groups[-1][-1].end:
            groups[-1].append(slot)
        else:
            groups.append([slot])

    out: list[StrategyWindow] = []
    for group in groups:
        avg_price = sum(_price(s, price_field) for s in group) / len(group)
        hours = sum((s.end - s.start).total_seconds() for s in group) / 3600
        out.append(
            StrategyWindow(
                action=action,
                start=group[0].start,
                end=group[-1].end,
                power_w=int(round(power_kw * 1000)),
                target_soc=int(target_soc),
                avg_price_chf_kwh=avg_price,
                slots_count=len(group),
                energy_kwh=round(hours * power_kw, 3),
            )
        )
    return out


def build_strategy(
    slots: list[TariffSlot],
    *,
    battery_capacity_kwh: float,
    charge_power_kw: float,
    discharge_power_kw: float,
    soc_start: int,
    soc_min: int,
    charge_target_soc: int,
    discharge_target_soc: int,
    price_field: str = "integrated_chf_kwh",
    roundtrip_efficiency: float = 0.90,
    max_windows_per_action: int = 2,
) -> StrategyResult:
    """Simple VARIO arbitrage optimizer.

    Chooses the cheapest slots to charge and most expensive slots to discharge.
    It then groups adjacent 15-min slots into GoodWe BatteryCD windows.
    """
    if not slots:
        return StrategyResult([], 0, 0, 0, 0, 0)

    available_charge_kwh = max(0.0, battery_capacity_kwh * (charge_target_soc - soc_start) / 100)
    available_discharge_kwh = max(0.0, battery_capacity_kwh * (soc_start - discharge_target_soc) / 100)

    # If the battery is not expected to have enough energy for the evening, assume the planned charge can be used later.
    planned_charge_kwh = available_charge_kwh
    planned_discharge_kwh = max(available_discharge_kwh, planned_charge_kwh * roundtrip_efficiency)
    planned_discharge_kwh = min(planned_discharge_kwh, battery_capacity_kwh * max(0, charge_target_soc - soc_min) / 100)

    slot_h = 0.25
    charge_slots_needed = int(-(-available_charge_kwh // (charge_power_kw * slot_h))) if charge_power_kw > 0 else 0
    discharge_slots_needed = int(-(-planned_discharge_kwh // (discharge_power_kw * slot_h))) if discharge_power_kw > 0 else 0

    cheapest = sorted(slots, key=lambda s: _price(s, price_field))[:charge_slots_needed]
    most_expensive = sorted(slots, key=lambda s: _price(s, price_field), reverse=True)[:discharge_slots_needed]

    charge_windows = _group_contiguous("charge", cheapest, charge_power_kw, charge_target_soc, price_field)
    discharge_windows = _group_contiguous("discharge", most_expensive, discharge_power_kw, discharge_target_soc, price_field)

    # Keep only the strongest windows if too fragmented.
    charge_windows = sorted(charge_windows, key=lambda w: (w.avg_price_chf_kwh, -w.energy_kwh))[:max_windows_per_action]
    discharge_windows = sorted(discharge_windows, key=lambda w: (-w.avg_price_chf_kwh, -w.energy_kwh))[:max_windows_per_action]

    windows = sorted(charge_windows + discharge_windows, key=lambda w: w.start)

    charged_energy = sum(w.energy_kwh for w in charge_windows)
    discharged_energy = sum(w.energy_kwh for w in discharge_windows)
    avg_charge = sum(w.avg_price_chf_kwh * w.energy_kwh for w in charge_windows) / charged_energy if charged_energy else 0
    avg_discharge = sum(w.avg_price_chf_kwh * w.energy_kwh for w in discharge_windows) / discharged_energy if discharged_energy else 0
    shifted = min(charged_energy * roundtrip_efficiency, discharged_energy)
    gain = max(0.0, shifted * (avg_discharge - avg_charge / max(roundtrip_efficiency, 0.01)))

    return StrategyResult(windows, round(gain, 2), round(charged_energy, 3), round(discharged_energy, 3), avg_charge, avg_discharge)


def _to_utc_seconds(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.astimezone(timezone.utc).timestamp())


def window_to_goodwe_data(window: StrategyWindow) -> dict[str, int]:
    mode = {"idle": 1, "charge": 2, "discharge": 3}[window.action]
    return {
        "BatteryCDEnable": 1,
        "BatteryCDMode": mode,
        "BatteryCDPW": int(window.power_w),
        "BatteryCDTargetSOC": int(window.target_soc),
        "CDStartTime": _to_utc_seconds(window.start),
        "CDEndTime": _to_utc_seconds(window.end),
    }
