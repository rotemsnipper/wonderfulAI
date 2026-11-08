"""Load the static system prompt and knowledge file, and append blocks generated from the settings and the manifest."""
from pathlib import Path

from backend.config import REPO_ROOT
from backend.scoring.label import scoring_text

PROMPTS_DIR = REPO_ROOT / "prompts"
SOURCE_LABELS = {
    "t100_summary": "T-100 airport-month summary (passengers, seats, departures)",
    "delay_causes": "BTS delay causes (arrival delays and causes)",
    "t100_segment": "T-100 segment (routes and distances)",
}


def data_block(manifest: dict) -> str:
    window = manifest.get("window", {})
    lines = ["## Data in this build"]
    if window.get("current"):
        lines.append(f"- Current window: {window['current']}; prior window: {window.get('prior', 'n/a')}; "
                     f"growth baseline year: {window.get('baseline_year', 'n/a')}.")
    for source, period in (manifest.get("periods") or {}).items():
        lines.append(f"- {SOURCE_LABELS.get(source, source)}: {period}.")
    cov = manifest.get("coverage")
    if cov:
        lines.append(f"- Airports: {cov.get('airports')} in the data, {cov.get('in_universe')} covered, "
                     f"{cov.get('in_universe_with_delay_data')} of those with delay data.")
    else:
        lines.append(f"- Airports in the data: {manifest.get('row_counts', {}).get('airports', 'n/a')}.")
    if manifest.get("build_date"):
        lines.append(f"- Build date: {manifest['build_date']}; score version {manifest.get('config_version', 'n/a')}.")
    return "\n".join(lines)


def build_system_prompt(manifest: dict, settings: dict, prompts_dir: Path = PROMPTS_DIR) -> str:
    """Weights and label thresholds come only from `settings` (the serving folder's copy), never the static files."""
    system = (prompts_dir / "system.md").read_text(encoding="utf-8").strip()
    knowledge = (prompts_dir / "knowledge.md").read_text(encoding="utf-8").strip()
    return f"{system}\n\n# Knowledge\n{knowledge}\n\n{scoring_text(settings)}\n\n{data_block(manifest)}\n"
