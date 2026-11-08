import json
import re
from pathlib import Path

import yaml

from backend.agent.prompt import PROMPTS_DIR, build_system_prompt, data_block
from backend.evals.graders import load_cases

FIXTURE_MANIFEST = Path(__file__).resolve().parents[1] / "fixtures" / "serving" / "manifest.json"
FIXTURE_SETTINGS = FIXTURE_MANIFEST.with_name("settings.yaml")


def manifest():
    return json.loads(FIXTURE_MANIFEST.read_text())


def settings():
    return yaml.safe_load(FIXTURE_SETTINGS.read_text())


def test_loader_appends_data_block_from_fixture_manifest():
    prompt = build_system_prompt(manifest(), settings())
    assert prompt.startswith("You are an airport investment analyst assistant.")
    assert "# Knowledge" in prompt
    assert "Current window: 2025-08..2026-07" in prompt
    assert "T-100 segment (routes and distances): 2025-08..2026-07." in prompt
    assert "Airports in the data: 12." in prompt


def test_data_block_uses_coverage_when_present():
    m = manifest() | {"coverage": {"airports": 1072, "in_universe": 184, "in_universe_with_delay_data": 175}}
    assert "1072 in the data, 184 covered, 175 of those with delay data" in data_block(m)


def test_every_prompt_rule_maps_to_an_eval_case():
    rules = set(re.findall(r"(?m)^(R\d+)\.", (PROMPTS_DIR / "system.md").read_text(encoding="utf-8")))
    covered = {r for c in load_cases() for r in c["rules"]}
    assert rules and rules <= covered, f"rules without an eval case: {sorted(rules - covered)}"


def test_prompt_has_the_three_examples_and_background_rule():
    text = (PROMPTS_DIR / "system.md").read_text(encoding="utf-8")
    for marker in ("Example 1 (data answer)", "Example 2 (clarifying question)", "Example 3 (decline)",
                   "Background (not from our data):"):
        assert marker in text


def test_examples_contain_no_copyable_figures():
    text = (PROMPTS_DIR / "system.md").read_text(encoding="utf-8")
    examples = text.split("## Examples", 1)[1]
    assert not re.search(r"\d+(\.\d+)?\s?%", examples)


def test_scoring_rules_are_generated_from_settings():
    s = settings()
    s["label"] = {**s["label"], "high_min": 72}
    prompt = build_system_prompt(manifest(), s)
    assert "## Scoring rules (generated from the settings)" in prompt
    assert "high at a score of 72 or more" in prompt
    assert "proxy for profit" in prompt
