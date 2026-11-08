"""One-command serving build: python -m backend.ingest.build [--raw data/raw] [--out data/serving]

Builds airports, airport_month and routes from the raw files, runs the build-stopping checks, and writes
the parquet files, manifest.json, and the settings it used, only if every
check passes. The running app reads only this folder (plus prompts/). On any failure the
previous serving files are left untouched.
"""
import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd
import yaml

from backend.config import REPO_ROOT, SERVING_DIR, load_settings
from backend.ingest.build_airport_month import build_airport_month
from backend.ingest.build_airports import build_airports
from backend.ingest.build_routes import build_routes
from backend.ingest.checks import NAMED_AIRPORTS, run_checks
from backend.ingest.manifest import build_manifest

log = logging.getLogger("backend.ingest.build")

RAW_DIR = REPO_ROOT / "data" / "raw"


class BuildFailed(RuntimeError):
    def __init__(self, checks: list[dict]):
        self.checks = checks
        failed = [c for c in checks if not c["passed"]]
        super().__init__("build checks failed: " + "; ".join(f"{c['name']}: {c['detail']}" for c in failed))


def shift(ym: int, months: int) -> int:
    idx = (ym // 100) * 12 + (ym % 100 - 1) + months
    return (idx // 12) * 100 + idx % 12 + 1


def window(end_ym: int, n: int) -> list[int]:
    return [shift(end_ym, -i) for i in range(n - 1, -1, -1)]


def raw_paths(raw: Path) -> dict:
    return {
        "t100": raw / "bts_t100_summary" / "t100_by_origin.csv",
        "delay": raw / "bts_delay_causes" / "Airline_Delay_Cause.csv",
        "segment": sorted((raw / "bts_t100_segment").glob("t100_segment_*.zip")),
        "ourairports": raw / "ourairports",
    }


def _t100_ids(t100_path: Path) -> pd.DataFrame:
    t = pd.read_csv(t100_path, low_memory=False, usecols=["origin_airport_id", "origin_airport_code", "reporting_month"])
    t = t.sort_values("reporting_month").drop_duplicates("origin_airport_code", keep="last")
    return t.rename(columns={"origin_airport_code": "code", "origin_airport_id": "airport_id"})[["code", "airport_id"]]


def build(raw: Path = RAW_DIR, out: Path = SERVING_DIR, settings: dict | None = None,
          named: list[str] = NAMED_AIRPORTS) -> dict:
    """Run the build; return the manifest. Raises BuildFailed (serving files untouched) when a check fails."""
    settings = settings or load_settings()
    paths = raw_paths(Path(raw))
    n = settings["window_months"]

    am, am_latest = build_airport_month(paths["t100"], paths["delay"], settings["baseline_year"])
    routes_all, _ = build_routes(paths["segment"])
    seg_latest = int((routes_all["year"] * 100 + routes_all["month"]).max())
    latest = min(am_latest["t100_latest_ym"], am_latest["delay_latest_ym"], seg_latest)
    windows = {"current": window(latest, n), "prior": window(shift(latest, -n), n)}
    log.info("latest common month %s; current window %s..%s", latest, windows["current"][0], latest)

    am = am[am["ym"] <= latest]
    pax = am[am["ym"].isin(windows["current"])].groupby("code")["passengers"].sum().rename("passengers_12m")
    t100 = _t100_ids(paths["t100"]).merge(pax.reset_index(), on="code", how="inner")
    t100 = t100[t100["passengers_12m"] > 0]
    airports, _ = build_airports(paths["ourairports"], t100, settings)

    codes = set(airports["code"])
    am = am[am["code"].isin(codes)].reset_index(drop=True)
    rym = routes_all["year"] * 100 + routes_all["month"]
    routes = routes_all[routes_all["code"].isin(codes) & rym.isin(windows["current"])].reset_index(drop=True)

    checks = run_checks(airports, am, routes, windows["current"], named)
    if not all(c["passed"] for c in checks):
        raise BuildFailed(checks)

    manifest = build_manifest(
        airports=airports, airport_month=am, routes=routes, windows=windows,
        baseline_year=settings["baseline_year"], checks=checks, settings=settings,
    )
    write_serving(Path(out), {"airports": airports, "airport_month": am, "routes": routes}, manifest,
                  yaml.safe_dump(settings, sort_keys=False))
    return manifest


def write_serving(out: Path, tables: dict[str, pd.DataFrame], manifest: dict, settings_text: str) -> None:
    """Write everything to a temp directory first, then move the files over the old ones.

    The settings written are the ones this build used, so the serving folder is self-contained.
    """
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent, prefix=f".{out.name}.") as tmp:
        tmp = Path(tmp)
        for name, df in tables.items():
            df.to_parquet(tmp / f"{name}.parquet", index=False)
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
        (tmp / "settings.yaml").write_text(settings_text, encoding="utf-8")
        for f in tmp.iterdir():
            os.replace(f, out / f.name)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--raw", type=Path, default=RAW_DIR)
    p.add_argument("--out", type=Path, default=SERVING_DIR)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        manifest = build(args.raw, args.out)
    except BuildFailed as e:
        log.error("%s; previous serving files kept", e)
        return 1
    print(json.dumps({k: manifest[k] for k in ("periods", "window", "row_counts", "checks")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
