# 🥷 FillNinja

**AG2 Hackathon @ Fordham Gabelli Submission**

FillNinja is a **multi-agent autonomous pipeline** built on the [AG2](https://github.com/ag2ai/ag2) framework that discovers, curates, and fills web forms in parallel.

Instead of an autofill tool that only works when you are already on a form, FillNinja turns a high-level natural language goal (for example, *"Find CS scholarships for high school seniors"*) into a complete end-to-end workflow across multiple browser tabs.

  

***

## 🏆 Hackathon Tracks Targeted

FillNinja was built to target the **Best Multi-Agent Collaboration on the AG2 Network** and **Most Impressive AG2 Build** prizes.

It demonstrates true multi-agent collaboration by separating concerns:
1. A single agent should not safely search the web, reason over a complex DOM, and execute actions simultaneously.
2. By splitting the pipeline into specialized agents, FillNinja achieves fast parallel execution with an explicit review layer.

***

## 🧠 The Multi-Agent Pipeline

FillNinja uses distinct AG2 agents, each with a clear responsibility and structured output via `PromptedSchema`.

| Agent | Role | Implementation |
|-------|------|----------------|
| **Search Curator** | **Discovery:** Uses **Tavily** live search when `TAVILY_API_KEY` is set, otherwise falls back to **`ddgs`** (DuckDuckGo), then curates and ranks the best URLs while filtering out junk and dead links. You can override search behavior with `FILLNINJA_SEARCH=auto|tavily|ddgs`. | `autogen.beta.Agent` + `PromptedSchema(DiscoveryResult)` |
| **Planner** | **Execution:** Runs on each opened tab. Receives a DOM snapshot and reasons step-by-step to propose browser actions such as `FILL`, `CLICK`, and `SELECT`. | `autogen.beta.Agent` + `PromptedSchema(PlannerOutput)` |
| **Reviewer** | **Safety:** Evaluates Planner actions against safety rules to block phishing, data exfiltration, or contradictory actions before execution. | `autogen.beta.Agent` + `PromptedSchema(ReviewOutput)` |
| **Project Profiler** | **Context extraction:** Profiles a **PDF / DOCX / PPTX**, **video**, or **public project URL** to extract discovery keywords and structured applicant facts that are appended to each discovered form's `fill_task` for better real-world `FILL` values. | `PromptedSchema(ProjectProfileSummary)` |

### How It Works

1. **Instruct:** Enter a goal in the Chrome extension popup (for example, *"Apply to software engineering roles in NYC"*).
2. **Discover:** The backend triggers the **Search Curator**, which searches the web and curates a list of target URLs.
3. **Fan-out:** The extension opens the discovered URLs in parallel tabs.
4. **Execute:** Each tab gets its own **Planner + Reviewer** loop. Actions stream through Server-Sent Events (SSE) to the service worker, which executes them in the live DOM.
5. **Feedback:** The result of each action is fed back into the Planner for the next step.

***

## 📄 Project Profiling

FillNinja can profile more than plain text goals.

You can provide any of the following as project context:
- **PDF / DOCX / PPTX** files
- **Video uploads**
- A **public project URL**
- A **GitHub repository link**
- A **YouTube watch URL**

The profiler performs one AG2 pass to extract:
- discovery keywords for finding relevant forms
- structured applicant facts that can be reused during filling

### Smart source handling

- **GitHub repo links** prefer **README/raw text** when available.
- **YouTube watch links** use **auto captions** when available via `youtube-transcript-api`.
- Generic public URLs are fetched and converted into text for profiling.

> LLM-based extraction can miss details in source material. Always verify critical applications before submitting.

Legacy **`.doc`** and **`.ppt`** files are not supported. Save them as **`.docx`**, **`.pptx`**, or PDF first.

***

## 🎥 Video Upload Support

FillNinja supports uploaded video files such as **`.mp4`**, **`.webm`**, **`.mov`**, and **`.mkv`** (up to **50 MB** in the popup).

For video profiling:
- the server uses **ffmpeg** to extract audio, so `ffmpeg` must be installed and available on `PATH`
- audio is sent to a **Whisper-compatible** API
- set `FILLNINJA_WHISPER_API_KEY`, or use `OPENAI_API_KEY` with `https://api.openai.com/v1` by default
- **OpenRouter keys alone do not run Whisper** unless `FILLNINJA_WHISPER_BASE_URL` points to a compatible endpoint

Only **spoken audio** is transcribed. On-screen text is **not** extracted via OCR or vision.

***

## 🛠️ Tech Stack

- **Agent Framework:** AG2 (`autogen.beta`), `PromptedSchema`, `OpenAIConfig`
- **Search:** Tavily Search API with DuckDuckGo `ddgs` fallback
- **LLM Routing:** OpenRouter by default, using an OpenAI-compatible configuration
- **Backend:** FastAPI, Python 3.10+, Server-Sent Events (SSE)
- **Frontend:** Manifest V3 Chrome Extension (popup, service worker, content scripts)
- **Document Profiling:** PDF / DOCX / PPTX extraction
- **Video Profiling:** ffmpeg + Whisper-compatible transcription

***

## 🚀 Getting Started

### Prerequisites

- Python 3.10+ (3.12 recommended if your environment blocks newer runtimes)
- Chrome or Chromium
- An [OpenRouter](https://openrouter.ai/) API key (`OPENROUTER_API_KEY`), or any OpenAI-compatible key routed through `OPENROUTER_BASE_URL`
- A [Tavily](https://app.tavily.com/) API key for live web search if you want Tavily instead of the DuckDuckGo fallback
- `ffmpeg` installed locally if you want to use video uploads

### 1. Run the Agent API

From the repository root:

```bash
cd /path/to/fillninja
python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

export OPENROUTER_API_KEY="sk-or-v1-..."
export TAVILY_API_KEY="tvly-..."          # optional but recommended for live search
export FILLNINJA_SEARCH="auto"            # auto | tavily | ddgs

python3 -m uvicorn server.main:app --host 127.0.0.1 --port 8000
```

Verify the server at [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health).

Default settings match the AG2 quickstart pattern:
- `base_url=https://openrouter.ai/api/v1`
- `model=google/gemini-2.5-flash`

Override these with:
- `OPENROUTER_MODEL`
- `OPENROUTER_BASE_URL`
- `OPENROUTER_MAX_COMPLETION_TOKENS`

The extension connects to `http://localhost:8000` by default.

### 2. Load the Chrome Extension

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select the `browser-agent-extension/` folder

### 3. Run FillNinja

#### Single tab

1. Start the API server.
2. Open the target form page.
3. Open the FillNinja popup.
4. Enter a task and click **Run on this tab**.

#### Full pipeline: discover + parallel fill

1. Enter a **goal**, **or** attach a **PDF / DOCX / PPTX / video**, **or** paste a **public project URL**, **or combine these sources**.
2. Set **Max forms** and **Parallel tabs** in the popup.
3. Click **Discover + fill (pipeline)**.

Implementation details:
- FillNinja uses JSON `POST /pipeline/discover` for text-only discovery.
- It uses multipart `POST /pipeline/discover_from_document` when a file or `source_url` is attached.
- The extension then opens discovered URLs and launches one fill agent per tab in batches.

***

## 🔒 Privacy, Safety, and Responsible Use

### Safety model

- A **Reviewer** can validate Planner actions before they touch the DOM.
- The system is designed to reduce unsafe actions such as phishing flows, contradiction, or accidental misuse.
- Users should still review important actions and submissions.

### Data handling

The following may be sent to your configured LLM or transcription endpoint(s):
- objectives and prompts
- uploaded document text
- video audio sent to your Whisper provider
- fetched public URL content
- YouTube captions retrieved by the server
- search snippets and discovered URLs
- DOM snapshots needed for browser actions

### Important notes

- Use **demo or non-sensitive data** when possible.
- Do **not** upload confidential files or URLs unless you trust your deployment and providers.
- FillNinja only fetches **public `http(s)` hosts**; localhost and private IP ranges are blocked.
- Respect website terms of service and review discovered URLs before mass automation.

***

## 🗂️ Repo Layout

| Path | Purpose |
|------|---------|
| `browser-agent-extension/` | Chrome extension (popup, service worker, content script). |
| `server/main.py` | FastAPI app exposing `/agent/*`, `/pipeline/discover`, and `/pipeline/discover_from_document`, plus the fill loop. |
| `server/discovery.py` | Tavily or `ddgs` search plus AG2 curator logic via `PromptedSchema(DiscoveryResult)`. |
| `server/video_transcribe.py` | ffmpeg audio extraction plus Whisper-compatible transcription for uploaded videos. |
| `server/web_fetch.py` | Fetches public `https` URLs as text, including HTML, PDF, DOCX, and PPTX, with basic SSRF protections. |
| `server/smart_source_url.py` | Routes source URLs intelligently: YouTube captions, GitHub README/raw preference, then generic fetch. |
| `server/document_extract.py` | Text extraction for PDF / DOCX / PPTX profiling. |
| `server/project_profile.py` | AG2 profiling pipeline via `PromptedSchema(ProjectProfileSummary)`. |
| `server/json_util.py` | Markdown-fence stripping and JSON cleanup helpers. |
| `server/llm.py` | Shared `OpenAIConfig` setup for OpenRouter and compatible endpoints. |
| `fillninja-pitch-deck.html` | Single-file pitch deck. |
| `scripts/generate_icons.py` | Optional script to regenerate extension icons. |

***

## 🎨 Icons

PNG icons live under `browser-agent-extension/icons/`.

To regenerate them:

```bash
pip install pillow
python3 scripts/generate_icons.py
```

***

## ❤️ Built For the AG2 Hackathon

FillNinja was designed as a practical demonstration of **multi-agent collaboration**, **parallel browser execution**, and **human-reviewable autonomous workflows**.

It is intended to show that browser automation becomes more capable when search, planning, profiling, and safety review are split into specialized agents rather than compressed into a single loop.
