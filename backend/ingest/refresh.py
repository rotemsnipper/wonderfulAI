"""Refresh the raw downloads and rebuild the serving data: python -m backend.ingest.refresh

Everything is downloaded and built in a temporary folder next to data/. The new raw and serving folders
replace the old ones only when the build passes and the window moved to a newer month, so a failed
download or build, or a refresh with nothing new, leaves data/raw and data/serving untouched.
A full refresh takes about 75 seconds (measured 2026-11-08; most of it is the T-100 segment download).
"""
import json
import logging
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from datetime import date
from pathlib import Path

from backend.config import SERVING_DIR, load_settings
from backend.ingest import fetch_delay, fetch_ourairports, fetch_t100_segment, fetch_t100_summary
from backend.ingest._download import DownloadError
from backend.ingest.build import RAW_DIR, build

log = logging.getLogger("backend.ingest.refresh")

Progress = Callable[[str], None]


def fetch_all(raw: Path, current_raw: Path, today: date, progress: Progress) -> None:
    """Download every source into `raw`. Segment years before the newest one already downloaded are complete,
    so they are copied from `current_raw` instead of downloaded again."""
    progress("downloading T-100 summary")
    fetch_t100_summary.fetch(raw / "bts_t100_summary", start_year=load_settings()["baseline_year"])
    progress("downloading delay causes")
    fetch_delay.fetch(raw / "bts_delay_causes", (today.year - 2, 1), (today.year, 12))

    seg = raw / "bts_t100_segment"
    seg.mkdir(parents=True)
    have = {int(p.stem.rsplit("_", 1)[1]): p for p in (current_raw / "bts_t100_segment").glob("t100_segment_*.zip")}
    newest = max(have, default=today.year)
    for year, path in have.items():
        if year < newest:
            shutil.copy2(path, seg / path.name)
    for year in range(newest, today.year + 1):
        progress(f"downloading T-100 segment {year}")
        try:
            fetch_t100_segment.fetch(seg, year)
        except DownloadError:
            if year == newest:
                raise
            log.info("T-100 segment %s is not published yet", year)  # early in a year

    progress("downloading OurAirports")
    fetch_ourairports.fetch(raw / "ourairports")


def refresh(raw: Path = RAW_DIR, out: Path = SERVING_DIR, fetch=fetch_all, build_fn=build,
            today: date | None = None, progress: Progress = lambda step: None) -> dict:
    """Return {status: "refreshed" | "no_newer_data", old_window, new_window, checks}. Download and build
    errors propagate (DownloadError, FormatError, BuildFailed); nothing is replaced when they do."""
    raw, out = Path(raw), Path(out)
    old = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["window"]
    with tempfile.TemporaryDirectory(dir=raw.parent, prefix=".refresh.") as tmp:
        tmp = Path(tmp)
        new_raw, new_out = tmp / "raw", tmp / "serving"
        fetch(new_raw, raw, today or date.today(), progress)
        progress("building the serving data")
        manifest = build_fn(new_raw, new_out)
        result = {"old_window": old, "new_window": manifest["window"],
                  "checks": [{"name": name, "passed": status == "pass"}
                             for name, status in manifest.get("checks", {}).items()]}
        if manifest["window"]["current"] == old["current"]:
            return {"status": "no_newer_data", **result}
        for current, new in ((raw, new_raw), (out, new_out)):
            if current.exists():
                os.replace(current, tmp / f"old_{current.name}")
            os.replace(new, current)
    return {"status": "refreshed", **result}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    result = refresh(progress=lambda step: log.info(step))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
