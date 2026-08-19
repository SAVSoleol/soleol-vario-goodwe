from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from forecast import ForecastSlot
from groupe_e import TariffSlot


@dataclass(frozen=True)
class TariffComparison:
    double_cost_chf: float
    vario_cost_chf: float
    saving_chf: float
    saving_pct: float
    import_kwh: float
    export_kwh: float


def is_double_high_tariff(dt: datetime) -> bool:
    """Groupe E 2026 Double: HT 07:00-12:00 and 17:00-23:00, otherwise BT."""
    minutes = dt.hour * 60 + dt.minute
    return (7 * 60 <= minutes < 12 * 60) or (17 * 60 <= minutes < 23 * 60)


def double_buy_price_chf_kwh(dt: datetime, high_ct_kwh: float, low_ct_kwh: float) -> float:
    return (high_ct_kwh if is_double_high_tariff(dt) else low_ct_kwh) / 100.0


def compare_double_vario(
    slots: list[TariffSlot],
    forecast: list[ForecastSlot],
    *,
    double_high_ct_kwh: float,
    double_low_ct_kwh: float,
    feed_in_ct_kwh: float = 0.0,
) -> TariffComparison:
    if len(slots) != len(forecast):
        raise ValueError("Les tarifs et le profil énergétique n'ont pas le même nombre de pas.")

    double_cost = 0.0
    vario_cost = 0.0
    import_kwh = 0.0
    export_kwh = 0.0
    feed_in = feed_in_ct_kwh / 100.0

    for slot, fc in zip(slots, forecast):
        if slot.start != fc.start or slot.end != fc.end:
            raise ValueError("Les pas tarifaires et énergétiques ne sont pas alignés.")
        net = fc.load_kwh - fc.pv_kwh
        if net >= 0:
            import_kwh += net
            double_cost += net * double_buy_price_chf_kwh(slot.start, double_high_ct_kwh, double_low_ct_kwh)
            vario_cost += net * slot.integrated_chf_kwh
        else:
            exported = -net
            export_kwh += exported
            # Same remuneration in both scenarios: it does not distort the Double vs VARIO comparison.
            double_cost -= exported * feed_in
            vario_cost -= exported * feed_in

    saving = double_cost - vario_cost
    saving_pct = (saving / double_cost * 100.0) if abs(double_cost) > 1e-9 else 0.0
    return TariffComparison(
        double_cost_chf=round(double_cost, 2),
        vario_cost_chf=round(vario_cost, 2),
        saving_chf=round(saving, 2),
        saving_pct=round(saving_pct, 2),
        import_kwh=round(import_kwh, 2),
        export_kwh=round(export_kwh, 2),
    )
