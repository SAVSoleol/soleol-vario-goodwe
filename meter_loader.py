
"""Standalone meter loader for Double/VARIO + battery comparison.

Independent from Battery Sizer.
Returns timestamp, import_kWh and export_kWh (export is optional; zero if unavailable).
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
    export_column: str
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
    raw = series.astype(str).str.strip()
    has_offset = raw.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})\s*$", regex=True, na=False).mean() > 0.2
    if has_offset:
        ts = pd.to_datetime(raw, errors="coerce", format="mixed", utc=True, dayfirst=True)
        return ts.dt.tz_convert("Europe/Zurich").dt.tz_localize(None)
    return pd.to_datetime(raw, errors="coerce", format="mixed", dayfirst=True)


def _infer_dt_hours(ts: pd.Series) -> float:
    d = ts.sort_values().diff().dt.total_seconds().div(3600)
    d = d[(d > 0) & (d <= 4)]
    return float(d.median()) if not d.empty else 0.25


def _detect_unit(*column_names, default="kWh") -> str:
    c = " | ".join(_norm(x).replace(" ", "") for x in column_names if x)
    if "kwh" in c:
        return "kWh"
    if "wh" in c:
        return "Wh"
    if "kw" in c:
        return "kW"
    if "(w)" in c or c.endswith("w"):
        return "W"
    return default


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str)
        .str.replace("'", "", regex=False)
        .str.replace("\u202f", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace(",", ".", regex=False),
        errors="coerce",
    )


def _to_kwh(values: pd.Series, unit: str, dt_hours: float) -> pd.Series:
    v = _numeric(values)
    if unit == "kWh": return v
    if unit == "Wh": return v / 1000.0
    if unit == "kW": return v * float(dt_hours)
    if unit == "W": return v * float(dt_hours) / 1000.0
    raise UnsupportedFormatError(f"Unité inconnue : {unit}")


def _pick_cols(columns):
    date_tokens = ("date", "heure", "timestamp", "horodat", "debut", "time")
    imp_tokens = ("soutirage", "import", "consommation", "achat", "prelev", "load")
    exp_tokens = ("surplus", "export", "injection", "refoule", "excedent", "revente")

    date_col = imp_col = exp_col = None
    for c in columns:
        n = _norm(c)
        if date_col is None and any(t in n for t in date_tokens): date_col = c
        if imp_col is None and any(t in n for t in imp_tokens): imp_col = c
        if exp_col is None and any(t in n for t in exp_tokens): exp_col = c
    return date_col, imp_col, exp_col


def _find_header(path: Path, max_rows=35):
    preview = pd.read_excel(path, header=None, nrows=max_rows)
    for i in range(len(preview)):
        vals = [v for v in preview.iloc[i].tolist() if str(v).strip() and str(v).lower() != "nan"]
        d, imp, _ = _pick_cols(vals)
        if d is not None and imp is not None:
            return i
    return None


def _read_csv_auto(path: Path):
    return pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")


def load_consumption_file(path: str | Path, forced_unit: str = "auto"):
    path = Path(path)
    ext = path.suffix.lower()

    vendor = "generic"
    timestamp_convention = "début d'intervalle"

    if ext in (".xlsx", ".xls"):
        header = _find_header(path)
        if header is None:
            raise UnsupportedFormatError("Impossible de trouver automatiquement les colonnes.")
        df = pd.read_excel(path, header=header)
        date_col, imp_col, exp_col = _pick_cols(df.columns)
        blob = " | ".join(_norm(c) for c in df.columns)
        if "soutirage" in blob:
            vendor = "groupe_e_xlsx"
            default_unit = "kW"
            timestamp_convention = "fin d'intervalle Groupe E"
        else:
            default_unit = _detect_unit(imp_col, exp_col, default="kWh")
    elif ext == ".csv":
        df = _read_csv_auto(path)
        date_col, imp_col, exp_col = _pick_cols(df.columns)
        vendor = "generic_csv"
        default_unit = _detect_unit(imp_col, exp_col, default="kWh")
    else:
        raise UnsupportedFormatError("Formats acceptés : .xlsx, .xls, .csv")

    if date_col is None or imp_col is None:
        raise UnsupportedFormatError("Colonnes date/heure ou soutirage non trouvées.")

    ts = _parse_datetime(df[date_col])
    dt_hours = _infer_dt_hours(ts)
    unit = default_unit if forced_unit == "auto" else forced_unit

    imp = _to_kwh(df[imp_col], unit, dt_hours)
    exp = _to_kwh(df[exp_col], unit, dt_hours) if exp_col is not None else pd.Series(0.0, index=df.index)

    out = pd.DataFrame({"timestamp": ts, "import_kWh": imp, "export_kWh": exp})
    out = out.dropna(subset=["timestamp"]).copy()

    # Groupe E blanks commonly mean 0 on the opposite flow.
    if vendor == "groupe_e_xlsx":
        out["import_kWh"] = out["import_kWh"].fillna(0.0)
        out["export_kWh"] = out["export_kWh"].fillna(0.0)
    else:
        out["import_kWh"] = out["import_kWh"].fillna(0.0)
        out["export_kWh"] = out["export_kWh"].fillna(0.0)

    out["import_kWh"] = out["import_kWh"].clip(lower=0.0)
    out["export_kWh"] = out["export_kWh"].clip(lower=0.0)

    if vendor == "groupe_e_xlsx":
        out["timestamp"] = out["timestamp"] - pd.to_timedelta(dt_hours, unit="h")

    out = out.sort_values("timestamp").reset_index(drop=True)
    if out.empty:
        raise UnsupportedFormatError("Aucune mesure exploitable.")

    span = out["timestamp"].iloc[-1] - out["timestamp"].iloc[0]
    meta = LoadMeta(
        vendor=vendor,
        source=path.name,
        date_column=str(date_col),
        import_column=str(imp_col),
        export_column=str(exp_col or "non disponible"),
        input_unit=unit,
        dt_hours=float(dt_hours),
        n_rows=len(out),
        coverage_days=float(span.total_seconds()/86400 + dt_hours/24),
        timestamp_convention=timestamp_convention,
    )
    return out, meta
