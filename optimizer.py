from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from groupe_e import TariffSlot

Action = Literal["charge", "discharge", "idle"]
ChargeSource = Literal["reseau", "pv_surplus", "mixte"]


@dataclass(frozen=True)
class StrategyWindow:
    action: Action
    start: datetime
    end: datetime
    power_w: int
    target_soc: int
    avg_buy_price_chf_kwh: float
    avg_sell_price_chf_kwh: float
    avg_cost_price_chf_kwh: float
    slots_count: int
    energy_kwh: float
    source: ChargeSource = "mixte"


@dataclass(frozen=True)
class StrategyResult:
    windows: list[StrategyWindow]
    estimated_gain_chf: float
    charged_energy_kwh: float
    usable_charged_energy_kwh: float
    discharged_energy_kwh: float
    avg_charge_cost: float
    avg_discharge_value: float
    strategy_comment: str


@dataclass(frozen=True)
class _Candidate:
    slot: TariffSlot
    source: ChargeSource
    cost_chf_kwh: float


def _ceil_div_energy(energy_kwh: float, power_kw: float, slot_h: float = 0.25) -> int:
    if energy_kwh <= 0 or power_kw <= 0:
        return 0
    slot_energy = power_kw * slot_h
    return int(-(-energy_kwh // slot_energy))


def _group_charge_windows(selected: list[_Candidate], power_kw: float, target_soc: int) -> list[StrategyWindow]:
    if not selected:
        return []
    selected = sorted(selected, key=lambda c: (c.source, c.slot.start))
    groups: list[list[_Candidate]] = [[selected[0]]]
    for cand in selected[1:]:
        last = groups[-1][-1]
        if cand.source == last.source and cand.slot.start == last.slot.end:
            groups[-1].append(cand)
        else:
            groups.append([cand])

    out: list[StrategyWindow] = []
    for group in groups:
        slots = [c.slot for c in group]
        hours = sum((s.end - s.start).total_seconds() for s in slots) / 3600
        energy = round(hours * power_kw, 3)
        out.append(
            StrategyWindow(
                action="charge",
                start=slots[0].start,
                end=slots[-1].end,
                power_w=int(round(power_kw * 1000)),
                target_soc=int(target_soc),
                avg_buy_price_chf_kwh=sum(s.integrated_chf_kwh for s in slots) / len(slots),
                avg_sell_price_chf_kwh=sum(s.grid_chf_kwh for s in slots) / len(slots),
                avg_cost_price_chf_kwh=sum(c.cost_chf_kwh for c in group) / len(group),
                slots_count=len(group),
                energy_kwh=energy,
                source=group[0].source,
            )
        )
    return out


def _group_discharge_windows(selected: list[TariffSlot], power_kw: float, target_soc: int) -> list[StrategyWindow]:
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
        hours = sum((s.end - s.start).total_seconds() for s in group) / 3600
        energy = round(hours * power_kw, 3)
        avg_buy = sum(s.integrated_chf_kwh for s in group) / len(group)
        avg_sell = sum(s.grid_chf_kwh for s in group) / len(group)
        out.append(
            StrategyWindow(
                action="discharge",
                start=group[0].start,
                end=group[-1].end,
                power_w=int(round(power_kw * 1000)),
                target_soc=int(target_soc),
                avg_buy_price_chf_kwh=avg_buy,
                avg_sell_price_chf_kwh=avg_sell,
                avg_cost_price_chf_kwh=avg_buy,
                slots_count=len(group),
                energy_kwh=energy,
                source="mixte",
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
    roundtrip_efficiency: float = 0.90,
    charge_policy: Literal["reseau", "pv_surplus", "auto"] = "auto",
    max_windows_per_action: int = 4,
    min_margin_chf_kwh: float = 0.01,
) -> StrategyResult:
    """Optimiseur économique VARIO.

    Hypothèses :
    - integrated_chf_kwh = prix d'achat réseau VARIO PLUS.
    - grid_chf_kwh = valeur d'injection / coût d'opportunité du surplus PV.

    Si charge_policy="reseau", la batterie est chargée sur les heures d'achat les moins chères.
    Si charge_policy="pv_surplus", la charge est planifiée lorsque la valeur d'injection est la plus basse.
    Si charge_policy="auto", l'algorithme retient le meilleur coût entre réseau et surplus PV.
    """
    if not slots:
        return StrategyResult([], 0, 0, 0, 0, 0, 0, "Aucune donnée tarifaire.")

    eta = max(0.01, min(roundtrip_efficiency, 1.0))
    slot_h = 0.25

    energy_to_full_kwh = max(0.0, battery_capacity_kwh * (charge_target_soc - soc_start) / 100)
    max_discharge_from_target_kwh = max(0.0, battery_capacity_kwh * (charge_target_soc - discharge_target_soc) / 100)
    current_discharge_available_kwh = max(0.0, battery_capacity_kwh * (soc_start - discharge_target_soc) / 100)

    planned_charge_kwh = min(energy_to_full_kwh, charge_power_kw * slot_h * len(slots))
    usable_from_planned_charge = planned_charge_kwh * eta
    planned_discharge_kwh = min(max_discharge_from_target_kwh, current_discharge_available_kwh + usable_from_planned_charge)

    charge_slots_needed = _ceil_div_energy(planned_charge_kwh, charge_power_kw, slot_h)
    discharge_slots_needed = _ceil_div_energy(planned_discharge_kwh, discharge_power_kw, slot_h)

    charge_candidates: list[_Candidate] = []
    for slot in slots:
        if charge_policy in ("reseau", "auto"):
            charge_candidates.append(_Candidate(slot=slot, source="reseau", cost_chf_kwh=slot.integrated_chf_kwh))
        if charge_policy in ("pv_surplus", "auto"):
            charge_candidates.append(_Candidate(slot=slot, source="pv_surplus", cost_chf_kwh=slot.grid_chf_kwh))

    selected_charge: list[_Candidate] = []
    used_charge_slots: set[datetime] = set()
    for cand in sorted(charge_candidates, key=lambda c: (c.cost_chf_kwh, c.slot.start)):
        if len(selected_charge) >= charge_slots_needed:
            break
        # Ne pas prendre deux sources pour le même quart d'heure.
        if cand.slot.start in used_charge_slots:
            continue
        selected_charge.append(cand)
        used_charge_slots.add(cand.slot.start)

    # Décharge uniquement sur les prix d'achat les plus élevés, hors créneaux de charge.
    discharge_candidates = [s for s in slots if s.start not in used_charge_slots]
    selected_discharge = sorted(discharge_candidates, key=lambda s: (s.integrated_chf_kwh, s.start), reverse=True)[:discharge_slots_needed]

    charge_windows = _group_charge_windows(selected_charge, charge_power_kw, charge_target_soc)
    discharge_windows = _group_discharge_windows(selected_discharge, discharge_power_kw, discharge_target_soc)

    # Limite le nombre de fenêtres envoyées à GoodWe si la stratégie est fragmentée.
    charge_windows = sorted(charge_windows, key=lambda w: (w.avg_cost_price_chf_kwh, -w.energy_kwh))[:max_windows_per_action]
    discharge_windows = sorted(discharge_windows, key=lambda w: (-w.avg_buy_price_chf_kwh, -w.energy_kwh))[:max_windows_per_action]
    windows = sorted(charge_windows + discharge_windows, key=lambda w: w.start)

    charged_energy = sum(w.energy_kwh for w in charge_windows)
    usable_charged = charged_energy * eta
    discharged_energy = min(sum(w.energy_kwh for w in discharge_windows), current_discharge_available_kwh + usable_charged)

    avg_charge_cost = (
        sum(w.avg_cost_price_chf_kwh * w.energy_kwh for w in charge_windows) / charged_energy if charged_energy else 0.0
    )
    total_discharge_window_energy = sum(w.energy_kwh for w in discharge_windows)
    avg_discharge_value = (
        sum(w.avg_buy_price_chf_kwh * w.energy_kwh for w in discharge_windows) / total_discharge_window_energy
        if total_discharge_window_energy
        else 0.0
    )

    # Coût de charge sur l'énergie entrée batterie, valeur de décharge sur l'énergie sortie utilisable.
    charge_cost = charged_energy * avg_charge_cost
    discharge_value = discharged_energy * avg_discharge_value
    gross_gain = discharge_value - charge_cost

    if discharged_energy > 0 and charged_energy > 0:
        margin = (discharge_value / discharged_energy) - (charge_cost / max(usable_charged, 0.001))
    else:
        margin = 0.0

    if gross_gain <= 0 or margin < min_margin_chf_kwh:
        comment = "Gain net faible ou négatif selon les hypothèses. Vérifier avant envoi réel."
    elif charge_policy == "pv_surplus":
        comment = "Optimisation basée sur la valeur d'injection VARIO grid. Nécessite du surplus PV réel sur les créneaux de charge."
    elif charge_policy == "reseau":
        comment = "Optimisation par arbitrage réseau : charge aux prix d'achat bas, décharge aux prix d'achat hauts."
    else:
        comment = "Optimisation auto : coût de charge le plus bas entre réseau et opportunité d'injection PV."

    return StrategyResult(
        windows=windows,
        estimated_gain_chf=round(max(0.0, gross_gain), 2),
        charged_energy_kwh=round(charged_energy, 3),
        usable_charged_energy_kwh=round(usable_charged, 3),
        discharged_energy_kwh=round(discharged_energy, 3),
        avg_charge_cost=round(avg_charge_cost, 4),
        avg_discharge_value=round(avg_discharge_value, 4),
        strategy_comment=comment,
    )


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
