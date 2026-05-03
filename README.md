# FillNinja

Browser extension (Manifest V3) plus a **local FastAPI agent** that plans form actions from the DOM and streams them to the extension over SSE.

## Prerequisites

- Python 3.10+
- Chrome or Chromium
- [OpenAI API key](https://platform.openai.com/) (`OPENAI_API_KEY`)

## Run the agent API

From the repository root:

```bash
cd /path/to/fillninja
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...
# optional:
# export OPENAI_MODEL=gpt-4o-mini
python3 -m uvicorn server.main:app --host 127.0.0.1 --port 8000
```

Check [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) — it should return `{"status":"ok"}`.

The extension uses `http://localhost:8000` by default (same machine).

## Load the extension

1. Open **chrome://extensions**
2. Enable **Developer mode**
3. **Load unpacked** → choose the `browser-agent-extension/` folder

## Use it

1. Start the API server (above).
2. Pin the extension, open a page with a form (or any page for navigation tasks).
3. Open the popup: status should show **Connected to AG2 Agent**.
4. Enter a task (e.g. “Fill the contact form with name Jane Doe, email jane@example.com”) and run.

**Privacy:** Your task text, page URL, and DOM snapshot are sent to the configured LLM provider to plan actions. Review sensitive pages before running.

## Repo layout

| Path | Purpose |
|------|---------|
| `browser-agent-extension/` | Chrome extension (popup, service worker, content script). |
| `server/main.py` | FastAPI app: `/health`, `POST /agent/run`, `GET /agent/{id}/events` (SSE), `POST /agent/{id}/action-result`, `POST /agent/{id}/stop`. |
| `fillninja-pitch-deck.html` | Single-file pitch deck. |
| `scripts/generate_icons.py` | Optional: regenerate `icons/*.png` with Pillow. |

## Icons

PNG icons live under `browser-agent-extension/icons/`. Regenerate with:

```bash
pip install pillow
python3 scripts/generate_icons.py
```
