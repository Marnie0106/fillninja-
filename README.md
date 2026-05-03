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
cp .env.example .env
# Edit .env: OPENROUTER_API_KEY, and optionally DAYTONA_API_KEY, TAVILY_API_KEY, etc.
python3 -m uvicorn server.main:app --host 127.0.0.1 --port 8000
```

The server loads **`.env`** from the repo root automatically (`python-dotenv`). Use **`.env`** for secrets instead of pasting keys into the shell. For a one-off terminal session you may instead `export OPENROUTER_API_KEY=...` (and optional `TAVILY_API_KEY`, `FILLNINJA_SEARCH=auto`) before starting uvicorn.

Check [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) — JSON describes pipeline + AG2 roles. After you change server code, **restart uvicorn** so the running process matches `server/main.py` (the extension checks OpenAPI for routes such as `POST /agent/prepare_applicant_context`).

Defaults match the **build-with-ag2** quickstart: `base_url=https://openrouter.ai/api/v1`, `model=google/gemini-2.5-flash`. Override with `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`, and `OPENROUTER_MAX_COMPLETION_TOKENS` if needed.

The extension expects the API at **`http://127.0.0.1:8000`** (same as `localhost:8000`). If nothing is listening there, the popup shows **Disconnected**.

### Optional code sandbox (Daytona or Docker)

FillNinja’s fill agents still use the Chrome extension for browser actions. Separately, you can enable **`POST /sandbox/run`** to execute Python / bash / JavaScript / TypeScript inside an AG2 sandbox:

- Set **`FILLNINJA_CODE_BACKEND=daytona`**. **`requirements.txt`** installs **`ag2[openai,daytona]`** from the **GitHub** repo so **`autogen.beta.extensions`** (Daytona backend) is present; plain **`pip install "ag2[daytona]"`** from PyPI alone can miss that package path. Add **`DAYTONA_API_KEY`** to **`.env`** (see `.env.example`). **`DAYTONA_API_URL`** must be **`https://app.daytona.io/api`** (SDK default) or omitted—**`https://api.daytona.io/...`** is not the REST API and returns HTML errors. Use **`FILLNINJA_DAYTONA_SNAPSHOT`** or **`FILLNINJA_DAYTONA_IMAGE`**. Alternatively, after **`pip install -r requirements.txt`**, use an editable clone: **`pip install -e "/path/to/ag2[openai,daytona]"`**.
- Or set **`FILLNINJA_CODE_BACKEND=docker`**, install **`pip install "ag2[docker]"`** (or match the GitHub **`ag2`** install above so **`autogen.beta.extensions.docker`** exists), and run Docker locally (`FILLNINJA_DOCKER_IMAGE`, `FILLNINJA_DOCKER_NETWORK`).

Check **`GET /health`** → **`sandbox`** for whether the backend is enabled and imports succeed. **Do not expose `/sandbox/run` on the public internet**; it runs arbitrary code.

## Install the Chrome extension

Do this **after** the API runs without errors on port **8000** (see above).

1. **Clone or copy** this repo and stay at the project root (the folder that contains `browser-agent-extension/`).
2. Open Chrome and go to **`chrome://extensions`**.
3. Turn on **Developer mode** (toggle in the toolbar area of that page).
4. Click **Load unpacked**.
5. Select the **`browser-agent-extension`** directory inside the repo (the folder that contains `manifest.json`, `popup.html`, `background.js`, and `content.js`).

Chrome loads **FillNinja Agent** as an unpacked extension.

6. **Pin it** (optional): click the puzzle icon in the Chrome toolbar → **FillNinja Agent** → pin, so the FillNinja icon stays visible.
7. Open the **FillNinja** popup. The status line should show **Connected to FillNinja backend** when `GET http://127.0.0.1:8000/health` succeeds. If it says the backend is **outdated**, another process may be bound to port 8000 or uvicorn was not restarted after a pull—stop old servers, then from this repo run `python3 -m uvicorn server.main:app --host 127.0.0.1 --port 8000` again.
8. After you **git pull** or edit extension files, open **`chrome://extensions`** → **Reload** on FillNinja so the service worker and popup pick up changes.

You can load the same `browser-agent-extension` folder from a checkout elsewhere (for example an `ag2-main` tree that includes a copy); behavior is the same as long as the FillNinja API on this machine is the code you intend.

### My profile (in the popup)

Open the extension popup and use the **My profile** tab. That textarea is your **personal applicant context** (name, contact, education, etc.). It is stored only in **Chrome local storage** on your machine. Tap **Save profile** after edits.

When you **Run on this tab** or use **Fill forms**, the server receives **My profile** text plus, when available, **cached text from a profiled résumé** (PDF/DOCX/PPTX handled by `prepare_applicant_context` or the legacy attach path). Use **Agent** vs **My profile** tabs to switch; you do not need a separate browser tab for profile editing.

## Use it

### Single tab

1. Start the API server (above).
2. Open the target page, open the popup (connected).
3. Enter a task and **Run on this tab**.

### Pipeline (discover + parallel fill)

1. Enter a **goal**, **or** attach **PDF / DOCX / PPTX / video**, **or** paste a **public web link** to your project page (or a direct file link), **or combine** these.
2. Set **Max forms** and **Parallel tabs** in the popup.
3. **Discover forms** — JSON `POST /pipeline/discover` when you use text only; multipart `POST /pipeline/discover_from_document` when you attach a file or URL. Then use **Fill from last discovery** so the extension opens tabs and starts one fill agent per URL (batched).

**URL fetching** uses the FillNinja server: only **http(s)** to **public** hosts (localhost and private IPs are blocked). Fetched page text and file bytes are sent to your LLM for profiling.

Legacy Word **.doc** / PowerPoint **.ppt** are not supported; save as **.docx** / **.pptx** or PDF.

**Responsible use:** Respect site terms; use demo data; review URLs before mass automation.

## Privacy and safety

- A **reviewer** agent can approve or block planner actions before they run in the page. You should still review important fills and submissions yourself.
- **Data sent to your LLM / transcription endpoints** may include: objectives and prompts, uploaded document text, video audio (Whisper path), fetched public URL content, YouTube captions retrieved by the server, search snippets, discovered URLs, and DOM snapshots used for browser actions.
- Use **demo or non-sensitive data** when possible. Do not upload confidential files or URLs unless you trust your deployment and providers.
- Respect website terms of service and review discovered URLs before mass automation.

## Repo layout

| Path | Purpose |
|------|---------|
| `browser-agent-extension/` | Chrome extension (popup, service worker, content script). |
| `server/main.py` | FastAPI: `/agent/*`, `/pipeline/discover`, `/pipeline/discover_from_document`, fill loop (planner + reviewer). |
| `server/discovery.py` | Tavily or `ddgs` search + AG2 curator (`PromptedSchema(DiscoveryResult)`). |
| `server/video_transcribe.py` | ffmpeg audio extract + Whisper-compatible transcription for uploaded videos. |
| `server/web_fetch.py` | Fetch public https URLs as text (HTML, PDF, DOCX, PPTX) with basic SSRF blocks. |
| `server/smart_source_url.py` | Profile URL routing: YouTube caption transcripts, GitHub README/raw preference, then generic fetch. |
| `server/code_sandbox.py` | Optional `POST /sandbox/run`: Daytona or Docker via AG2 when `FILLNINJA_CODE_BACKEND` is set. |
| `server/document_extract.py` | PDF / DOCX / PPTX text extraction for profiling. |
| `server/project_profile.py` | AG2 profiler (`PromptedSchema(ProjectProfileSummary)`). |
| `server/json_util.py` | Markdown-fence stripping for model JSON. |
| `server/llm.py` | Shared `OpenAIConfig` for OpenRouter. |
| `fillninja-pitch-deck.html` | Single-file pitch deck. |
| `scripts/generate_icons.py` | Optional: regenerate `icons/*.png` with Pillow. |

## Icons

Toolbar and popup header use **`browser-agent-extension/icons/fillninja.png`**. Optional small assets (16/48/128) can be regenerated with:

```bash
pip install pillow
python3 scripts/generate_icons.py
```

## Built for the AG2 community

FillNinja demonstrates **multi-agent collaboration**, **parallel browser execution**, and **human-reviewable** automation: search, planning, profiling, and safety review as separate concerns instead of one opaque loop.
