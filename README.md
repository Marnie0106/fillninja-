# FillNinja

Browser extension (Manifest V3) plus a **local FastAPI service** with an **[AG2](https://github.com/ag2ai/ag2) multi-agent** pipeline:

- **Search Curator** — `ddgs` (DuckDuckGo) live search + `PromptedSchema(DiscoveryResult)` to shortlist real application pages.
- **Fill agents** (per tab) — planner + optional reviewer, with **parallel runs** across tabs.

## Prerequisites

- Python 3.10+ (3.12 recommended if your environment blocks newer runtimes)
- Chrome or Chromium
- An [OpenRouter](https://openrouter.ai/) API key (`OPENROUTER_API_KEY`), or any OpenAI-compatible key you point at with `OPENROUTER_BASE_URL`

## Run the agent API

From the repository root:

```bash
cd /path/to/fillninja
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export OPENROUTER_API_KEY="sk-or-v1-..."   # OpenRouter; see .env.example for more vars
python3 -m uvicorn server.main:app --host 127.0.0.1 --port 8000
```

Check [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) — JSON describes pipeline + AG2 roles.

Defaults match the **build-with-ag2** quickstart: `base_url=https://openrouter.ai/api/v1`, `model=google/gemini-2.5-flash`. Override with `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`, and `OPENROUTER_MAX_COMPLETION_TOKENS` if needed.

The extension uses `http://localhost:8000` by default (same machine).

## Load the extension

1. Open **chrome://extensions**
2. Enable **Developer mode**
3. **Load unpacked** → choose the `browser-agent-extension/` folder

## Use it

### Single tab

1. Start the API server (above).
2. Open the target page, open the popup (connected).
3. Enter a task and **Run on this tab**.

### Pipeline (discover + parallel fill)

1. Enter a **goal** (e.g. “CS scholarships for US high school seniors”).
2. Set **Max forms** and **Parallel tabs** in the popup.
3. **Discover + fill (pipeline)** — server runs `POST /pipeline/discover` (search + curator); extension opens tabs and starts one fill agent per URL (batched).

**Responsible use:** Respect site terms; use demo data; review URLs before mass automation.

**Privacy:** Objectives, snippets, URLs, and DOM snapshots go to your LLM endpoint(s).

## Repo layout

| Path | Purpose |
|------|---------|
| `browser-agent-extension/` | Chrome extension (popup, service worker, content script). |
| `server/main.py` | FastAPI: `/agent/*`, `/pipeline/discover`, fill loop (planner + reviewer). |
| `server/discovery.py` | `ddgs` search + AG2 curator (`PromptedSchema(DiscoveryResult)`). |
| `server/llm.py` | Shared `OpenAIConfig` for OpenRouter. |
| `fillninja-pitch-deck.html` | Single-file pitch deck. |
| `scripts/generate_icons.py` | Optional: regenerate `icons/*.png` with Pillow. |

## Icons

PNG icons live under `browser-agent-extension/icons/`. Regenerate with:

```bash
pip install pillow
python3 scripts/generate_icons.py
```
