
"""Standalone meter loader for the Double vs VARIO comparator.

This file is independent from the Battery Sizer.
It borrows the proven ideas (not the code dependency) of:
- vendor/layout detection;
- robust Swiss timestamps;
- kW/W -> interval kWh conversion;
- automatic header detection.

Only GRID IMPORT / SOUTIRAGE is required.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


class UnsupportedFormatError(ValueError):
    pass


@dataclass
class LoadMeta:
    vendor: str
    source: str
    date_column: str
    import_column: str
    input_unit: str
    dt_hours: float
    n_rows: int
    coverage_days: float
    timestamp_convention: str


def _norm(value) -> str:
    s = str(value).lower().strip()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s)


def _parse_datetime(series: pd.Series) -> pd.Series:
    """Parse mixed timestamps and return naive Europe/Zurich local time."""
    raw = series.astype(str).str.strip()
    # First parse timestamps that already carry offsets in a DST-safe way.
    try:
        ts_utc = pd.to_datetime(raw, errors="coerce", format="mixed", utc=True, dayfirst=True)
        good = ts_utc.notna().mean()
    except Exception:
        good = 0.0
        ts_utc = pd.Series(pd.NaT, index=series.index)

    # If values are plain local Excel datetimes, parsing as UTC would shift them.
    # Detect this case by checking whether the raw strings contain explicit offsets/Z.
    has_offset = raw.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})\s*$", regex=True, na=False).mean() > 0.2
    if has_offset and good > 0.5:
        return ts_utc.dt.tz_convert("Europe/Zurich").dt.tz_localize(None)

    return pd.to_datetime(raw, errors="coerce", format="mixed", dayfirst=True)


def _infer_dt_hours(ts: pd.Series) -> float:
    d = ts.sort_values().diff().dt.total_seconds().div(3600)
    d = d[(d > 0) & (d <= 4)]
    if d.empty:
        return 0.25
    return float(d.median())


def _detect_unit(column_name: str, default: str = "kWh") -> str:
    c = _norm(column_name).replace(" ", "")
    if "kwh" in c:
        return "kWh"
    if "wh" in c:
        return "Wh"
    if "kw" in c:
        return "kW"
    if "(w)" in c or c.endswith("_w") or c.endswith("w"):
        return "W"
    return default


def _to_kwh(values: pd.Series, unit: str, dt_hours: float) -> pd.Series:
    values = pd.to_numeric(
        values.astype(str)
        .str.replace("'", "", regex=False)
        .str.replace("\u202f", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace(",", ".", regex=False),
        errors="coerce",
    )
    if unit == "kWh":
        return values
    if unit == "Wh":
        return values / 1000.0
    if unit == "kW":
        return values * float(dt_hours)
    if unit == "W":
        return values * float(dt_hours) / 1000.0
    raise UnsupportedFormatError(f"Unité inconnue : {unit}")


def _find_groupe_e_header(path: Path) -> int | None:
    preview = pd.read_excel(path, header=None, nrows=30)
    for i in range(len(preview)):
        row = " | ".join(_norm(v) for v in preview.iloc[i].tolist())
        if "date" in row and "soutirage" in row:
            return i
    return None


def _pick_date_and_import(columns) -> tuple[str | None, str | None]:
    date_tokens = ("date", "heure", "timestamp", "horodat", "debut", "début", "time")
    imp_tokens = ("soutirage", "import", "consommation", "achat", "prelev", "prélèv", "load")

    date_col = None
    imp_col = None

    for c in columns:
        n = _norm(c)
        if date_col is None and any(t in n for t in date_tokens):
            date_col = c
        if imp_col is None and any(t in n for t in imp_tokens):
            imp_col = c
    return date_col, imp_col


def _find_generic_excel_header(path: Path) -> int | None:
    preview = pd.read_excel(path, header=None, nrows=35)
    for i in range(len(preview)):
        vals = [v for v in preview.iloc[i].tolist() if str(v).strip() and str(v).lower() != "nan"]
        date_col, imp_col = _pick_date_and_import(vals)
        if date_col is not None and imp_col is not None:
            return i
    return None


def _read_csv_auto(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")


def load_consumption_file(path: str | Path, forced_unit: str = "auto") -> tuple[pd.DataFrame, LoadMeta]:
    """Return columns timestamp + import_kWh.

    For Groupe E Excel load curves, timestamps such as 00:15 represent the
    interval ending at 00:15. They are shifted back by one detected interval so
    they align with VARIO API slots starting at 00:00.
    """
    path = Path(path)
    ext = path.suffix.lower()

    vendor = "generic"
    timestamp_convention = "début d'intervalle"

    if ext in (".xlsx", ".xls"):
        ge_header = _find_groupe_e_header(path)
        if ge_header is not None:
            vendor = "groupe_e_xlsx"
            df = pd.read_excel(path, header=ge_header)
            date_col = next((c for c in df.columns if "date" in _norm(c)), None)
            imp_col = next((c for c in df.columns if "soutirage" in _norm(c)), None)
            default_unit = "kW"
            timestamp_convention = "fin d'intervalle Groupe E"
        else:
            header = _find_generic_excel_header(path)
            if header is None:
                raise UnsupportedFormatError("Impossible de trouver automatiquement les colonnes date/heure et consommation.")
            df = pd.read_excel(path, header=header)
            date_col, imp_col = _pick_date_and_import(df.columns)
            default_unit = _detect_unit(imp_col or "", "kWh")
    elif ext == ".csv":
        df = _read_csv_auto(path)
        date_col, imp_col = _pick_date_and_import(df.columns)
        if date_col is None or imp_col is None:
            raise UnsupportedFormatError("CSV : colonnes date/heure et consommation non détectées.")
        default_unit = _detect_unit(imp_col, "kWh")
        vendor = "generic_csv"
    else:
        raise UnsupportedFormatError("Formats acceptés : .xlsx, .xls, .csv")

    if date_col is None or imp_col is None:
        raise UnsupportedFormatError("Colonnes date/heure ou soutirage non trouvées.")

    ts = _parse_datetime(df[date_col])
    dt_hours = _infer_dt_hours(ts)

    if forced_unit == "auto":
        unit = _detect_unit(imp_col, default_unit)
    else:
        unit = forced_unit

    import_kwh = _to_kwh(df[imp_col], unit, dt_hours)
    out = pd.DataFrame({"timestamp": ts, "import_kWh": import_kwh})

    # In Groupe E load-curve exports, an empty "Soutirage" cell commonly means
    # zero grid import during an interval where the site is exporting. Keep the
    # quarter-hour and treat the blank as 0 instead of deleting it.
    out = out.dropna(subset=["timestamp"]).copy()
    if vendor == "groupe_e_xlsx":
        out["import_kWh"] = out["import_kWh"].fillna(0.0)
    else:
        out = out.dropna(subset=["import_kWh"]).copy()

    out["import_kWh"] = out["import_kWh"].clip(lower=0.0)

    # Groupe E's load-curve timestamps label the END of each 15-minute interval.
    if vendor == "groupe_e_xlsx":
        out["timestamp"] = out["timestamp"] - pd.to_timedelta(dt_hours, unit="h")

    out = out.sort_values("timestamp").reset_index(drop=True)
    if out.empty:
        raise UnsupportedFormatError("Aucune mesure exploitable.")

    # Preserve real DST duplicate local timestamps. Aggregation is only used for
    # accidental duplicates outside DST and will not change yearly energy materially.
    span = out["timestamp"].iloc[-1] - out["timestamp"].iloc[0]
    meta = LoadMeta(
        vendor=vendor,
        source=path.name,
        date_column=str(date_col),
        import_column=str(imp_col),
        input_unit=unit,
        dt_hours=float(dt_hours),
        n_rows=len(out),
        coverage_days=float(span.total_seconds() / 86400.0 + dt_hours / 24.0),
        timestamp_convention=timestamp_convention,
    )
    return out, meta
