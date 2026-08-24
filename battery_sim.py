
"""Battery simulation for the standalone Double vs VARIO comparator."""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class BatteryResult:
    import_after: np.ndarray
    export_after: np.ndarray
    soc_kwh: np.ndarray
    charge_kwh: np.ndarray
    discharge_kwh: np.ndarray
    cycles: float
    cost_chf: float
    import_cost_chf: float
    export_revenue_chf: float


def _double_tariffs(timestamps, ht, bt):
    idx = pd.DatetimeIndex(pd.to_datetime(timestamps))
    h = idx.hour + idx.minute / 60.0
    high = ((h >= 7) & (h < 12)) | ((h >= 17) & (h < 23))
    return np.where(high, float(ht), float(bt))


def _simulate(
    timestamps,
    imp,
    exp,
    buy_prices,
    feed_in,
    capacity,
    power_kw,
    dt_hours,
    roundtrip_eff,
    price_aware=False,
):
    imp = np.asarray(imp, dtype=float)
    exp = np.asarray(exp, dtype=float)
    prices = np.asarray(buy_prices, dtype=float)

    n = len(imp)
    eta = float(np.sqrt(roundtrip_eff))
    max_step = float(power_kw) * float(dt_hours)
    usable = max(float(capacity) * 0.95, 0.0)  # 5% SOC reserve
    soc = 0.0

    imp_after = imp.copy()
    exp_after = exp.copy()
    soc_arr = np.zeros(n)
    charge = np.zeros(n)
    discharge = np.zeros(n)

    # Future-price threshold: 75th percentile of the next 24 h.
    # This keeps stored PV for expensive VARIO slots instead of consuming it immediately.
    lookahead = max(1, int(round(24 / dt_hours)))
    thresholds = np.empty(n)
    if price_aware:
        for i in range(n):
            future = prices[i:min(n, i + lookahead)]
            thresholds[i] = float(np.quantile(future, 0.75)) if len(future) else prices[i]
    else:
        thresholds[:] = -np.inf

    for i in range(n):
        # Always store available PV surplus first.
        room_input = max(0.0, (usable - soc) / eta)
        c = min(exp_after[i], max_step, room_input)
        if c > 0:
            exp_after[i] -= c
            soc += c * eta
            charge[i] = c

        # Double+Battery: discharge whenever there is import.
        # VARIO+Battery: discharge only when the current price is in the expensive
        # part of the next 24h price distribution.
        can_discharge = (not price_aware) or (prices[i] >= thresholds[i] - 1e-12)
        if imp_after[i] > 0 and can_discharge and soc > 0:
            available_output = soc * eta
            d = min(imp_after[i], max_step, available_output)
            imp_after[i] -= d
            soc -= d / eta
            discharge[i] = d

        soc_arr[i] = soc

    import_cost = float((imp_after * prices).sum())
    export_revenue = float((exp_after * float(feed_in)).sum())
    net_cost = import_cost - export_revenue
    cycles = float(discharge.sum() / usable) if usable > 0 else 0.0

    return BatteryResult(
        import_after=imp_after,
        export_after=exp_after,
        soc_kwh=soc_arr,
        charge_kwh=charge,
        discharge_kwh=discharge,
        cycles=cycles,
        cost_chf=net_cost,
        import_cost_chf=import_cost,
        export_revenue_chf=export_revenue,
    )


def simulate_double_battery(df, ht, bt, feed_in, capacity, power_kw, dt_hours, roundtrip_eff):
    prices = _double_tariffs(df["timestamp"], ht, bt)
    return _simulate(
        df["timestamp"], df["import_kWh"], df["export_kWh"], prices, feed_in,
        capacity, power_kw, dt_hours, roundtrip_eff, price_aware=False,
    )


def simulate_vario_battery(df, feed_in, capacity, power_kw, dt_hours, roundtrip_eff):
    return _simulate(
        df["timestamp"], df["import_kWh"], df["export_kWh"], df["vario_chf_kwh"], feed_in,
        capacity, power_kw, dt_hours, roundtrip_eff, price_aware=True,
    )
