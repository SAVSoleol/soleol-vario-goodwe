from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from forecast import ForecastSlot
from groupe_e import TariffSlot

Action = Literal["charge", "discharge", "idle"]
Source = Literal["pv_surplus", "grid", "battery", "none"]


@dataclass(frozen=True)
class DispatchStep:
    start: datetime
    end: datetime
    action: Action
    power_kw: float
    energy_kwh: float
    soc_start_pct: float
    soc_end_pct: float
    pv_kwh: float
    load_kwh: float
    grid_import_kwh: float
    grid_export_kwh: float
    buy_price_chf_kwh: float
    sell_price_chf_kwh: float
    source: Source
    cost_chf: float


@dataclass(frozen=True)
class StrategyWindow:
    action: Action
    start: datetime
    end: datetime
    power_kw: float
    target_soc: int
    energy_kwh: float


@dataclass(frozen=True)
class StrategyResult:
    steps: list[DispatchStep]
    windows: list[StrategyWindow]
    baseline_cost_chf: float
    optimized_cost_chf: float
    estimated_gain_chf: float
    charged_energy_kwh: float
    discharged_energy_kwh: float
    final_soc_pct: float
    strategy_comment: str


def _validate(slots: list[TariffSlot], forecast: list[ForecastSlot]) -> None:
    if len(slots) != len(forecast):
        raise ValueError("Les tarifs et la prévision n'ont pas le même nombre de pas.")
    for s, f in zip(slots, forecast):
        if s.start != f.start or s.end != f.end:
            raise ValueError("Les pas tarifaires et énergétiques ne sont pas alignés.")


def _baseline_cost(slots: list[TariffSlot], forecast: list[ForecastSlot]) -> float:
    total = 0.0
    for s, f in zip(slots, forecast):
        net = f.load_kwh - f.pv_kwh
        if net >= 0:
            total += net * s.integrated_chf_kwh
        else:
            total -= (-net) * s.grid_chf_kwh
    return total


def _future_buy_threshold(slots: list[TariffSlot], idx: int, lookahead_slots: int = 24) -> float:
    future = [x.integrated_chf_kwh for x in slots[idx + 1 : idx + 1 + lookahead_slots]]
    return max(future) if future else slots[idx].integrated_chf_kwh


def optimize_day(
    slots: list[TariffSlot],
    forecast: list[ForecastSlot],
    *,
    battery_capacity_kwh: float,
    charge_power_kw: float,
    discharge_power_kw: float,
    soc_start_pct: float,
    soc_min_pct: float,
    soc_max_pct: float,
    charge_efficiency: float = 0.95,
    discharge_efficiency: float = 0.95,
    allow_grid_charge: bool = True,
    min_arbitrage_margin_chf_kwh: float = 0.02,
    strategy_mode: str = "automatic",
    buy_min_chf_kwh: float = 0.12,
    buy_max_chf_kwh: float = 0.30,
    sell_min_chf_kwh: float = 0.03,
    sell_max_chf_kwh: float = 0.15,
    feed_in_chf_kwh: float = 0.08,
) -> StrategyResult:
    """Transparent greedy EMS simulation over quarter-hour slots.

    Priority:
    1. Serve load with PV.
    2. Store PV surplus when its injection value is below a future avoided-buy value.
    3. Discharge during high buy-price slots.
    4. Optionally charge from grid when future spread covers losses and margin.
    """
    _validate(slots, forecast)
    if battery_capacity_kwh <= 0:
        raise ValueError("La capacité batterie doit être positive.")

    soc_min_kwh = battery_capacity_kwh * soc_min_pct / 100
    soc_max_kwh = battery_capacity_kwh * soc_max_pct / 100
    stored_kwh = min(max(battery_capacity_kwh * soc_start_pct / 100, soc_min_kwh), soc_max_kwh)
    baseline = _baseline_cost(slots, forecast)
    optimized_cost = 0.0
    steps: list[DispatchStep] = []

    for i, (slot, fc) in enumerate(zip(slots, forecast)):
        duration_h = (slot.end - slot.start).total_seconds() / 3600
        max_charge_input = charge_power_kw * duration_h
        max_discharge_output = discharge_power_kw * duration_h
        soc_before = stored_kwh / battery_capacity_kwh * 100

        pv_to_load = min(fc.pv_kwh, fc.load_kwh)
        residual_load = fc.load_kwh - pv_to_load
        surplus_pv = fc.pv_kwh - pv_to_load

        charge_input = 0.0
        discharge_output = 0.0
        grid_import = 0.0
        grid_export = 0.0
        source: Source = "none"

        future_high = _future_buy_threshold(slots, i)
        pv_storage_value = future_high * discharge_efficiency - feed_in_chf_kwh

        # PV surplus first. In manual mode, store only while the injection price
        # is at or below the configured low selling threshold.
        if strategy_mode == "manual":
            # Injection remuneration is independent from the VARIO grid component.
            # In manual mode, the buy thresholds control grid arbitrage; PV storage
            # remains based on avoided future purchase versus fixed feed-in value.
            should_store_pv = pv_storage_value >= min_arbitrage_margin_chf_kwh
        else:
            should_store_pv = pv_storage_value >= min_arbitrage_margin_chf_kwh

        if surplus_pv > 0 and should_store_pv:
            room_input = max(0.0, (soc_max_kwh - stored_kwh) / charge_efficiency)
            charge_input = min(surplus_pv, max_charge_input, room_input)
            stored_kwh += charge_input * charge_efficiency
            surplus_pv -= charge_input
            source = "pv_surplus" if charge_input > 0 else "none"

        # Battery serves load when current price is sufficiently valuable.
        if residual_load > 0:
            available_output = max(0.0, (stored_kwh - soc_min_kwh) * discharge_efficiency)
            # Rolling 24 h threshold, suitable for both one-day and historical simulations.
            window = slots[max(0, i - 48): min(len(slots), i + 48)]
            sorted_prices = sorted(s.integrated_chf_kwh for s in window)
            high_price_threshold = sorted_prices[int(0.65 * (len(sorted_prices) - 1))]
            should_discharge = (
                slot.integrated_chf_kwh >= buy_max_chf_kwh
                if strategy_mode == "manual"
                else slot.integrated_chf_kwh >= high_price_threshold
            )
            if should_discharge:
                discharge_output = min(residual_load, max_discharge_output, available_output)
                stored_kwh -= discharge_output / discharge_efficiency
                residual_load -= discharge_output
                if discharge_output > 0:
                    source = "battery"

        # Optional grid charging if future arbitrage spread is sufficient.
        if allow_grid_charge and charge_input == 0 and residual_load >= 0:
            effective_charge_cost = slot.integrated_chf_kwh / max(charge_efficiency * discharge_efficiency, 0.01)
            spread = future_high - effective_charge_cost
            should_grid_charge = (
                slot.integrated_chf_kwh <= buy_min_chf_kwh
                if strategy_mode == "manual"
                else spread >= min_arbitrage_margin_chf_kwh
            )
            if should_grid_charge:
                room_input = max(0.0, (soc_max_kwh - stored_kwh) / charge_efficiency)
                grid_charge = min(max_charge_input, room_input)
                if grid_charge > 0:
                    charge_input += grid_charge
                    stored_kwh += grid_charge * charge_efficiency
                    grid_import += grid_charge
                    source = "grid"

        grid_import += max(0.0, residual_load)
        grid_export += max(0.0, surplus_pv)

        slot_cost = grid_import * slot.integrated_chf_kwh - grid_export * feed_in_chf_kwh
        optimized_cost += slot_cost
        soc_after = stored_kwh / battery_capacity_kwh * 100

        if charge_input > 1e-6:
            action: Action = "charge"
            energy = charge_input
            power = charge_input / duration_h
        elif discharge_output > 1e-6:
            action = "discharge"
            energy = discharge_output
            power = discharge_output / duration_h
        else:
            action = "idle"
            energy = 0.0
            power = 0.0

        steps.append(
            DispatchStep(
                start=slot.start,
                end=slot.end,
                action=action,
                power_kw=round(power, 3),
                energy_kwh=round(energy, 4),
                soc_start_pct=round(soc_before, 2),
                soc_end_pct=round(soc_after, 2),
                pv_kwh=round(fc.pv_kwh, 4),
                load_kwh=round(fc.load_kwh, 4),
                grid_import_kwh=round(grid_import, 4),
                grid_export_kwh=round(grid_export, 4),
                buy_price_chf_kwh=slot.integrated_chf_kwh,
                sell_price_chf_kwh=feed_in_chf_kwh,
                source=source,
                cost_chf=round(slot_cost, 5),
            )
        )

    windows = steps_to_windows(steps)
    gain = baseline - optimized_cost
    return StrategyResult(
        steps=steps,
        windows=windows,
        baseline_cost_chf=round(baseline, 2),
        optimized_cost_chf=round(optimized_cost, 2),
        estimated_gain_chf=round(gain, 2),
        charged_energy_kwh=round(sum(s.energy_kwh for s in steps if s.action == "charge"), 2),
        discharged_energy_kwh=round(sum(s.energy_kwh for s in steps if s.action == "discharge"), 2),
        final_soc_pct=round(stored_kwh / battery_capacity_kwh * 100, 1),
        strategy_comment=f"Simulation énergétique sur {len(slots)} pas de 15 minutes avec PV, consommation, achat, revente et SOC.",
    )


def steps_to_windows(steps: list[DispatchStep]) -> list[StrategyWindow]:
    active = [s for s in steps if s.action != "idle"]
    if not active:
        return []
    groups: list[list[DispatchStep]] = [[active[0]]]
    for step in active[1:]:
        prev = groups[-1][-1]
        same_action = step.action == prev.action
        contiguous = step.start == prev.end
        similar_power = abs(step.power_kw - prev.power_kw) <= max(0.5, prev.power_kw * 0.10)
        if same_action and contiguous and similar_power:
            groups[-1].append(step)
        else:
            groups.append([step])

    out: list[StrategyWindow] = []
    for g in groups:
        avg_power = sum(s.power_kw for s in g) / len(g)
        target = round(g[-1].soc_end_pct)
        out.append(
            StrategyWindow(
                action=g[0].action,
                start=g[0].start,
                end=g[-1].end,
                power_kw=round(avg_power, 2),
                target_soc=int(target),
                energy_kwh=round(sum(s.energy_kwh for s in g), 3),
            )
        )
    return out
