# FillNinja

Browser extension (Manifest V3) plus a **local FastAPI service** that runs an **[AG2](https://github.com/ag2ai/ag2) `beta.Agent`** to plan browser actions from the DOM and stream them to the extension over SSE.

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

Check [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) — it should return `{"status":"ok"}`.

Defaults match the **build-with-ag2** quickstart: `base_url=https://openrouter.ai/api/v1`, `model=google/gemini-2.5-flash`. Override with `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`, and `OPENROUTER_MAX_COMPLETION_TOKENS` if needed.

The extension uses `http://localhost:8000` by default (same machine).

## Load the extension

1. Open **chrome://extensions**
2. Enable **Developer mode**
3. **Load unpacked** → choose the `browser-agent-extension/` folder

## Use it

1. Start the API server (above).
2. Pin the extension, open a page with a form (or any page for navigation tasks).
3. Open the popup: status should show **Connected to FillNinja backend**.
4. Enter a task (e.g. “Fill the contact form with name Jane Doe, email jane@example.com”) and run.

**Privacy:** Your task text, page URL, and DOM snapshot are sent to the configured model endpoint to plan actions. Review sensitive pages before running.

## Repo layout

| Path | Purpose |
|------|---------|
| `browser-agent-extension/` | Chrome extension (popup, service worker, content script). |
| `server/main.py` | FastAPI app plus AG2 `Agent` + `OpenAIConfig` (OpenRouter-compatible). |
| `fillninja-pitch-deck.html` | Single-file pitch deck. |
| `scripts/generate_icons.py` | Optional: regenerate `icons/*.png` with Pillow. |

## Icons

PNG icons live under `browser-agent-extension/icons/`. Regenerate with:

```bash
pip install pillow
python3 scripts/generate_icons.py
```
