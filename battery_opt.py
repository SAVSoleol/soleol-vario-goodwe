
"""Economic battery optimizer for the standalone Double / VARIO comparator.

Uses a linear program over the complete comparable period.

Decision variables, for every 15-minute interval:
- grid import
- grid export
- battery charge
- battery discharge
- battery SOC

Objective:
    minimize sum(import * buy_price - export * feed_in_price)

Constraints:
- exact site energy balance based on measured grid import/export before battery;
- charge/discharge power;
- battery usable SOC range;
- charge/discharge efficiency;
- optional ban on grid charging;
- final SOC = initial SOC so the optimizer cannot create an artificial end-of-period gain.

The measured import/export profile is sufficient because its net value represents
load minus PV at the point of connection.
"""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy.sparse import lil_matrix, csr_matrix


@dataclass
class OptimizedBatteryResult:
    import_after: np.ndarray
    export_after: np.ndarray
    charge_kwh: np.ndarray
    discharge_kwh: np.ndarray
    soc_kwh: np.ndarray
    cost_chf: float
    import_cost_chf: float
    export_revenue_chf: float
    wear_cost_chf: float
    economic_cost_chf: float
    cycles: float
    charged_kwh: float
    discharged_kwh: float
    success: bool
    message: str


def double_price_vector(timestamps, ht, bt):
    idx = pd.DatetimeIndex(pd.to_datetime(timestamps))
    h = idx.hour + idx.minute / 60.0
    high = ((h >= 7.0) & (h < 12.0)) | ((h >= 17.0) & (h < 23.0))
    return np.where(high, float(ht), float(bt)).astype(float)


def optimize_battery(
    df: pd.DataFrame,
    buy_prices,
    feed_in_chf_kwh: float,
    capacity_kwh: float,
    power_kw: float,
    dt_hours: float,
    roundtrip_eff: float,
    soc_min_pct: float = 5.0,
    soc_max_pct: float = 95.0,
    allow_grid_charge: bool = False,
    wear_cost_chf_per_kwh: float = 0.0,
) -> OptimizedBatteryResult:
    """Find the minimum-cost dispatch over the full historical period."""

    imp0 = np.asarray(df["import_kWh"], dtype=float)
    exp0 = np.asarray(df["export_kWh"], dtype=float)
    prices = np.asarray(buy_prices, dtype=float)

    n = len(df)
    if not (len(imp0) == len(exp0) == len(prices)):
        raise ValueError("Longueurs de séries incompatibles.")
    if n == 0:
        raise ValueError("Aucune donnée à optimiser.")

    cap = float(capacity_kwh)
    p_step = float(power_kw) * float(dt_hours)
    eta_c = eta_d = float(np.sqrt(roundtrip_eff))
    soc_min = cap * float(soc_min_pct) / 100.0
    soc_max = cap * float(soc_max_pct) / 100.0
    if soc_max <= soc_min:
        raise ValueError("SOC max doit être supérieur au SOC min.")

    # variable blocks: g, e, c, d, s
    G = 0
    E = n
    C = 2*n
    D = 3*n
    S = 4*n
    nv = 5*n

    obj = np.zeros(nv, dtype=float)
    obj[G:G+n] = prices
    feed = np.asarray(feed_in_chf_kwh, dtype=float)
    if feed.ndim == 0:
        feed = np.full(n, float(feed), dtype=float)
    if len(feed) != n:
        raise ValueError("Longueur du tarif de reprise incompatible avec les données.")
    obj[E:E+n] = -feed
    obj[D:D+n] = float(wear_cost_chf_per_kwh)

    # Bounds
    bounds = []

    # IMPORTANT:
    # Grid import/export must be physically bounded. Without these bounds the LP
    # can buy and sell an unlimited amount in the same quarter-hour whenever
    # the feed-in price is higher than the purchase price, which makes the
    # mathematical problem "unbounded".
    #
    # Import can cover the measured site import plus at most one battery
    # charging step. In PV-only mode no extra grid import is allowed.
    if allow_grid_charge:
        bounds.extend([
            # Grid charging is only permitted when there is no simultaneous
            # measured PV export. With a single point of connection, importing
            # energy to charge while preserving an export in the same interval
            # would be an artificial simultaneous buy/sell transaction.
            (
                0.0,
                max(0.0, float(imp0[i])) + (p_step if float(exp0[i]) <= 1e-12 else 0.0)
            )
            for i in range(n)
        ])
    else:
        bounds.extend([
            (0.0, max(0.0, float(imp0[i])))
            for i in range(n)
        ])

    # The battery is used for self-consumption / import avoidance, not for
    # exporting stored energy to the grid. Therefore post-battery export can
    # never exceed the site's original PV surplus for that interval.
    bounds.extend([
        (0.0, max(0.0, float(exp0[i])))
        for i in range(n)
    ])

    # Charge:
    # PV-only mode limits battery input to measured surplus available in that interval.
    if allow_grid_charge:
        bounds.extend([(0.0, p_step)] * n)
    else:
        bounds.extend([(0.0, min(p_step, max(0.0, float(exp0[i])))) for i in range(n)])

    bounds.extend([(0.0, p_step)] * n)  # discharge
    bounds.extend([(soc_min, soc_max)] * n)

    # Equality constraints:
    # 1) site balance: g - e + d - c = import_before - export_before
    # 2) SOC recursion
    # 3) final SOC = initial SOC (soc_min)
    neq = 2*n + 1
    Aeq = lil_matrix((neq, nv), dtype=float)
    beq = np.zeros(neq, dtype=float)

    net = imp0 - exp0
    for i in range(n):
        row = i
        Aeq[row, G+i] = 1.0
        Aeq[row, E+i] = -1.0
        Aeq[row, D+i] = 1.0
        Aeq[row, C+i] = -1.0
        beq[row] = net[i]

    for i in range(n):
        row = n + i
        Aeq[row, S+i] = 1.0
        Aeq[row, C+i] = -eta_c
        Aeq[row, D+i] = 1.0 / eta_d
        if i == 0:
            beq[row] = soc_min
        else:
            Aeq[row, S+i-1] = -1.0
            beq[row] = 0.0

    Aeq[2*n, S+n-1] = 1.0
    beq[2*n] = soc_min

    res = linprog(
        c=obj,
        A_eq=csr_matrix(Aeq),
        b_eq=beq,
        bounds=bounds,
        method="highs",
        options={"presolve": True},
    )

    if not res.success:
        raise RuntimeError(f"Optimisation batterie impossible : {res.message}")

    x = res.x
    g = x[G:G+n]
    e = x[E:E+n]
    c = x[C:C+n]
    d = x[D:D+n]
    s = x[S:S+n]

    import_cost = float(np.dot(g, prices))
    export_revenue = float(np.dot(e, feed))
    energy_bill_cost = import_cost - export_revenue
    wear_cost = float(d.sum() * float(wear_cost_chf_per_kwh))
    economic_cost = energy_bill_cost + wear_cost

    usable = soc_max - soc_min
    cycles = float(d.sum() / usable) if usable > 0 else 0.0

    return OptimizedBatteryResult(
        import_after=g,
        export_after=e,
        charge_kwh=c,
        discharge_kwh=d,
        soc_kwh=s,
        cost_chf=energy_bill_cost,
        import_cost_chf=import_cost,
        export_revenue_chf=export_revenue,
        wear_cost_chf=wear_cost,
        economic_cost_chf=economic_cost,
        cycles=cycles,
        charged_kwh=float(c.sum()),
        discharged_kwh=float(d.sum()),
        success=True,
        message=res.message,
    )
