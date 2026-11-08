"""Read-only access to a serving folder (tables, manifest, and the settings it was built with)."""
import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

REQUIRED_COLUMNS: dict[str, list[str]] = {
    "airports": [
        "airport_id", "code", "name", "city", "state", "runways_total", "runways_usable",
        "max_runway_ft", "size_tier", "in_universe",
    ],
    "airport_month": [
        "code", "year", "month", "ym", "departures", "passengers", "seats", "freight_lbs",
        "arr_flights", "arr_del15", "nas_ct", "weather_ct", "carrier_ct", "late_aircraft_ct",
        "security_ct", "arr_cancelled", "arr_delay_min", "has_delay_data",
    ],
    "routes": [
        "code", "year", "month", "dest", "dest_country", "distance_mi", "class",
        "departures", "passengers", "seats", "freight_lbs",
    ],
}

WINDOWS = ("current", "prior", "baseline")


class SchemaError(ValueError):
    pass


def _shift(ym: int, months: int) -> int:
    idx = (ym // 100) * 12 + (ym % 100 - 1) + months
    return (idx // 12) * 100 + idx % 12 + 1


def _month_range(end_ym: int, n: int) -> list[int]:
    return [_shift(end_ym, -i) for i in range(n - 1, -1, -1)]


def _parse_ym(text: str) -> int:
    y, m = text.split("-")
    return int(y) * 100 + int(m)


@dataclass
class Store:
    airports: pd.DataFrame
    airport_month: pd.DataFrame
    routes: pd.DataFrame
    manifest: dict
    settings: dict
    _window_cache: dict = field(default_factory=dict, init=False, repr=False, compare=False)

    @property
    def window_months(self) -> int:
        return int(self.settings["window_months"])

    @property
    def baseline_year(self) -> int:
        return int(self.settings["baseline_year"])

    @property
    def latest_ym(self) -> int:
        """Last month of the current window: from the manifest when stated, else the newest month in the data."""
        current = self.manifest.get("window", {}).get("current")
        if current:
            return _parse_ym(current.split("..")[1])
        return int(self.airport_month["ym"].max())

    def window(self, which: str) -> list[int]:
        """Month keys (yyyymm ints) of the current, prior or baseline window."""
        if which == "current":
            return _month_range(self.latest_ym, self.window_months)
        if which == "prior":
            return _month_range(_shift(self.latest_ym, -self.window_months), self.window_months)
        if which == "baseline":
            return _month_range(self.baseline_year * 100 + 12, 12)
        raise ValueError(f"unknown window {which!r}; expected one of {WINDOWS}")

    def window_label(self, which: str) -> str:
        ms = self.window(which)
        return f"{ms[0] // 100}-{ms[0] % 100:02d}..{ms[-1] // 100}-{ms[-1] % 100:02d}"

    def months(self, which: str, codes: list[str] | None = None) -> pd.DataFrame:
        """airport_month rows in a window, optionally for some airports."""
        if which not in self._window_cache:
            df = self.airport_month[self.airport_month["ym"].isin(self.window(which))]
            self._window_cache[which] = (df, {code: g for code, g in df.groupby("code")})
        df, by_code = self._window_cache[which]
        if codes is None:
            return df
        parts = [by_code[c] for c in codes if c in by_code]
        return pd.concat(parts) if len(parts) > 1 else (parts[0] if parts else df.iloc[0:0])

    def routes_in(self, which: str, codes: list[str] | None = None) -> pd.DataFrame:
        key = ("routes", which)
        if key not in self._window_cache:
            ym = self.routes["year"] * 100 + self.routes["month"]
            df = self.routes[ym.isin(self.window(which))]
            self._window_cache[key] = (df, {code: g for code, g in df.groupby("code")})
        df, by_code = self._window_cache[key]
        if codes is None:
            return df
        parts = [by_code[c] for c in codes if c in by_code]
        return pd.concat(parts) if len(parts) > 1 else (parts[0] if parts else df.iloc[0:0])

    def years_since_baseline(self) -> float:
        """Years between the baseline year's last month and the window's last month."""
        base = self.baseline_year * 12 + 11
        end = (self.latest_ym // 100) * 12 + (self.latest_ym % 100 - 1)
        return (end - base) / 12


def _check_columns(name: str, df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS[name] if c not in df.columns]
    if missing:
        raise SchemaError(f"serving table {name!r} is missing required columns: {', '.join(missing)}")


SUPPORT_FILES = ("manifest.json", "settings.yaml")


def load_store(path: Path | str) -> Store:
    """Load a serving folder: the three tables plus the manifest and settings the build wrote next to them. Raises SchemaError on a missing file or column; nothing is read from config/."""
    path = Path(path)
    tables = {}
    for name in REQUIRED_COLUMNS:
        file = path / f"{name}.parquet"
        if not file.exists():
            raise SchemaError(f"serving table {name!r} not found at {file}")
        df = pd.read_parquet(file)
        _check_columns(name, df)
        tables[name] = df
    for name in SUPPORT_FILES:
        if not (path / name).exists():
            raise SchemaError(f"serving file {name} not found at {path}; rebuild with python -m backend.ingest.build")
    return Store(
        **tables,
        manifest=json.loads((path / "manifest.json").read_text(encoding="utf-8")),
        settings=yaml.safe_load((path / "settings.yaml").read_text(encoding="utf-8")),
    )
