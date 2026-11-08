from functools import lru_cache
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = REPO_ROOT / "config" / "settings.yaml"
# The running app reads settings and aliases from the serving folder (copied there by the build),
# so data and settings always match; config/ is what the build reads from.
SERVING_DIR = REPO_ROOT / "data" / "serving"


@lru_cache(maxsize=None)
def _load(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_settings(path: Path | None = None) -> dict:
    """Return the settings dict from config/settings.yaml (cached; treat as read-only)."""
    return _load(str(path or SETTINGS_PATH))
