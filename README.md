# FillNinja

Browser extension (Manifest V3) plus a **local FastAPI service** with an **[AG2](https://github.com/ag2ai/ag2) multi-agent** pipeline:

- **Search Curator** — **Tavily** (live web; [free API key](https://app.tavily.com)) when `TAVILY_API_KEY` is set, otherwise **`ddgs`** (DuckDuckGo), then `PromptedSchema(DiscoveryResult)` to shortlist real application pages. Override with `FILLNINJA_SEARCH=auto|tavily|ddgs`.
- **Fill agents** (per tab) — planner + optional reviewer, with **parallel runs** across tabs.
- **Project profiler** — **PDF / DOCX / PPTX**, **video** (see below), or a **public project URL**: one AG2 pass extracts discovery keywords plus **structured applicant facts** appended to each discovered form’s `fill_task` for real `FILL` values. **GitHub** repo links prefer **README/raw text**; **YouTube** watch links use **auto captions** when available (`youtube-transcript-api`). LLM extraction can miss text—verify critical applications. Legacy **.doc** / **.ppt** are not supported.
- **Video uploads** — **.mp4 / .webm / .mov / .mkv / …** (up to **50 MB** in the popup): the server runs **ffmpeg** (install and ensure it’s on `PATH`) to extract audio, then calls a **Whisper-compatible** API (`FILLNINJA_WHISPER_API_KEY` or **`OPENAI_API_KEY`** for `https://api.openai.com/v1` by default). **OpenRouter keys alone cannot run Whisper** unless you set `FILLNINJA_WHISPER_BASE_URL` to a compatible endpoint. Only **spoken audio** is transcribed (no vision/OCR for on-screen text).

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

1. Enter a **goal**, **or** attach **PDF / DOCX / PPTX / video**, **or** paste a **public web link** to your project page (or a direct file link), **or combine** these.
2. Set **Max forms** and **Parallel tabs** in the popup.
3. **Discover + fill (pipeline)** — JSON `POST /pipeline/discover` when you use text only; multipart `POST /pipeline/discover_from_document` when you attach a file or `source_url`; then the extension opens tabs and starts one fill agent per URL (batched).

**URL fetching** uses the FillNinja server: only **http(s)** to **public** hosts (localhost and private IPs are blocked). Fetched page text and file bytes are sent to your LLM for profiling.

Legacy Word **.doc** / PowerPoint **.ppt** are not supported; save as **.docx** / **.pptx** or PDF.

**Responsible use:** Respect site terms; use demo data; review URLs before mass automation.

**Privacy:** Objectives, **uploaded document text**, **video audio (sent to your Whisper provider)**, **fetched URL content** (including **YouTube captions** retrieved by the server), **search snippets**, URLs, and DOM snapshots go to your LLM endpoint(s). Do not use confidential URLs or files unless you trust your deployment.

## Repo layout

| Path | Purpose |
|------|---------|
| `browser-agent-extension/` | Chrome extension (popup, service worker, content script). |
| `server/main.py` | FastAPI: `/agent/*`, `/pipeline/discover`, `/pipeline/discover_from_document`, fill loop (planner + reviewer). |
| `server/discovery.py` | Tavily or `ddgs` search + AG2 curator (`PromptedSchema(DiscoveryResult)`). |
| `server/video_transcribe.py` | ffmpeg audio extract + Whisper-compatible transcription for uploaded videos. |
| `server/web_fetch.py` | Fetch public https URLs as text (HTML, PDF, DOCX, PPTX) with basic SSRF blocks. |
| `server/smart_source_url.py` | Profile URL routing: YouTube caption transcripts, GitHub README/raw preference, then generic fetch. |
| `server/document_extract.py` | PDF / DOCX / PPTX text extraction for profiling. |
| `server/project_profile.py` | AG2 profiler (`PromptedSchema(ProjectProfileSummary)`). |
| `server/json_util.py` | Markdown-fence stripping for model JSON. |
| `server/llm.py` | Shared `OpenAIConfig` for OpenRouter. |
| `fillninja-pitch-deck.html` | Single-file pitch deck. |
| `scripts/generate_icons.py` | Optional: regenerate `icons/*.png` with Pillow. |

## Icons

PNG icons live under `browser-agent-extension/icons/`. Regenerate with:

```bash
pip install pillow
python3 scripts/generate_icons.py
```
