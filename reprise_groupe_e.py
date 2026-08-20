
"""Groupe E PV repurchase prices used by the standalone VARIO comparator.

2026 principle:
- PV energy repurchase follows the quarterly OFEN reference market price.
- For PV < 30 kW without GO, Groupe E applies a 6 ct/kWh minimum.
- GO is optional. Up to 100 kW, the total energy + GO remuneration is capped
  at 10.96 ct/kWh in 2026.

Published official values currently encoded:
- Q1 2026 OFEN: 10.266 ct/kWh
- Q2 2026 OFEN: 3.896 ct/kWh -> Groupe E minimum 6.000 ct/kWh (<30 kW, no GO)

Q3/Q4 remain provisional until published. The app asks for a provisional value
and labels it clearly.
"""

from __future__ import annotations
import numpy as np
import pandas as pd

# Official published OFEN quarterly PV reference prices, ct/kWh.
OFEN_PV_CT = {
    (2025, 4): 9.508,
    (2026, 1): 10.266,
    (2026, 2): 3.896,
}

def quarter_of(ts: pd.Timestamp) -> int:
    return (int(ts.month) - 1) // 3 + 1

def groupe_e_repurchase_ct(
    year: int,
    quarter: int,
    *,
    installation_kw: float = 29.9,
    sell_go: bool = False,
    provisional_ct: float = 6.0,
) -> tuple[float, str]:
    """Return applicable/provisional Groupe E PV repurchase in ct/kWh.

    This implementation is exact for installations <30 kW.
    For >=30 kW the legal minimum is power-dependent; the app warns the user and
    uses the OFEN quarterly price (or provisional value) unless manually adapted.
    """
    ref = OFEN_PV_CT.get((int(year), int(quarter)))

    if int(year) == 2025 and int(quarter) == 4:
        if sell_go:
            return 13.508, "publié Groupe E Q4 2025 avec GO"
        return 9.508, "publié Groupe E Q4 2025 sans GO"

    if int(year) == 2026:
        winter = quarter in (1, 4)
        go_ct = 3.0 if winter else 1.0

        if ref is None:
            # Quarter not yet published.
            base = float(provisional_ct)
            if sell_go:
                total = min(base + go_ct, 10.96) if installation_kw <= 100 else base + go_ct
                return total, f"provisoire Q{quarter} {year} avec GO"
            return base, f"provisoire Q{quarter} {year} sans GO"

        # Published quarter.
        if installation_kw < 30:
            energy = max(float(ref), 6.0)
        else:
            # The exact Groupe E minimum is degressive from 30 to 150 kW.
            # Use reference price here and flag in label.
            energy = float(ref)

        if sell_go:
            total = energy + go_ct
            if installation_kw <= 100:
                total = min(total, 10.96)
            label = f"publié Q{quarter} {year} avec GO"
        else:
            total = energy
            label = f"publié Q{quarter} {year} sans GO"

        if installation_kw >= 30:
            label += " — minimum >30 kW à vérifier"
        return total, label

    return float(provisional_ct), f"provisoire Q{quarter} {year}"

def repurchase_vector(
    timestamps,
    *,
    installation_kw: float = 29.9,
    sell_go: bool = False,
    provisional_ct: float = 6.0,
):
    idx = pd.DatetimeIndex(pd.to_datetime(timestamps))
    vals = np.zeros(len(idx), dtype=float)
    labels = []
    for i, ts in enumerate(idx):
        q = quarter_of(ts)
        ct, label = groupe_e_repurchase_ct(
            ts.year, q,
            installation_kw=installation_kw,
            sell_go=sell_go,
            provisional_ct=provisional_ct,
        )
        vals[i] = ct / 100.0
        labels.append(label)
    return vals, labels

def quarterly_summary(timestamps, **kwargs) -> pd.DataFrame:
    idx = pd.DatetimeIndex(pd.to_datetime(timestamps))
    rows = []
    seen = set()
    for ts in idx:
        q = quarter_of(ts)
        key = (ts.year, q)
        if key in seen:
            continue
        seen.add(key)
        ct, label = groupe_e_repurchase_ct(ts.year, q, **kwargs)
        rows.append({
            "Période": f"Q{q} {ts.year}",
            "Reprise (ct/kWh)": ct,
            "Statut": label,
        })
    return pd.DataFrame(rows)
