# Airport investment agent

A chat agent that helps analysts find US airports where terminal renovation or expansion is likely to pay off, using public BTS and OurAirports data.
Deterministic Python code computes every number. The language model (Gemini) picks the tools and writes the comparison, verdict and reasoning, and code checks every number it writes.

The design, scoring methodology and tradeoffs are in [docs/design.md](docs/design.md).

## Requirements
- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- A Gemini API key (only for the chat UI and the evals; the tests run without it)

## Setup
```
uv sync
cp .env.example .env
```
Open `.env` and set `GEMINI_API_KEY`. The default model is `gemini-3.8-flash`; set `GEMINI_MODEL` to override it.

## Data
The serving dataset is in the repo at `data/serving/`, so no download is needed to run the agent. The current window is 2025-08 to 2026-07.

Optional: rebuild the serving dataset, for example after changing `config/settings.yaml`. This needs the raw downloads in `data/raw/`. They are not in the repo; the fetchers that download them are in `backend/ingest/`.
```
uv run python -m backend.ingest.build
```
The build runs its checks and replaces `data/serving/` only if every check passes.

To download the newest public data and rebuild in one step (about 75 seconds), run `uv run python -m backend.ingest.refresh`, or ask the agent to update the data. Nothing is replaced unless the build passes and a newer month exists.

## Tests
```
uv run python -m pytest -q -W ignore::SyntaxWarning
```
The `-W` flag hides SyntaxWarnings printed by a dependency. The tests use a fixture dataset and a fake model; they make no network calls.

## Chat UI
```
uv run --env-file .env streamlit run backend/ui/app.py
```
Streamlit opens the app in the browser. It is a local app with a single user. To ask by voice, use the microphone in the chat bar; the Listen button under an answer reads its verdict aloud (Chrome or Edge on a desktop work best). Conversations are kept in memory and last only while the server runs. The sidebar has the four sample questions:

1. Which airports in New England are strong candidates for terminal expansion?
2. Compare LA and Santa Ana airport congestion levels.
3. What is the percentage of long-haul flights out of Anchorage airport?
4. What is the unmet flight demand in SFO airport and why?

It also answers follow-ups such as "What if growth counted twice as much?" (a re-ranking with custom weights), "How have passengers at BOS changed month by month?" (a trend) and "Are there delays at SFO right now?" (live FAA airport status).

## Evals
The evals call the real model and are graded by code. Run them from the project root:
```
uv run --env-file .env python -m backend.evals.run_evals
uv run --env-file .env python -m backend.evals.run_evals --case q1_new_england
```
A full run takes about five minutes on the free tier. Results are written to `backend/evals/results/`.

## Repo layout
| Path | Contents |
|---|---|
| `backend/ingest/` | fetchers, cleaning, build checks and the serving build |
| `backend/scoring/` | formulas, capacity-need score, label, robustness, unmet demand, warnings |
| `backend/tools/` | the agent tools (five data tools, live FAA status, two data-update tools), the airport resolver and the data store |
| `backend/agent/` | Gemini adapter, agent loop, number checks, footer, session store, prompt builder |
| `backend/report/` | report renderer and section definitions |
| `backend/ui/` | Streamlit chat app and its backend |
| `backend/evals/` | eval cases, graders, runner and results |
| `backend/tests/` | unit and integration tests, fixture dataset |
| `config/` | `settings.yaml`: weights, thresholds, cutoffs, window rules (build input) |
| `data/serving/` | the serving dataset the app reads |
| `prompts/` | system prompt and knowledge file |
| `scripts/recompute/` | independent recompute of the sample-question figures from the raw files |
| `docs/` | design document |
