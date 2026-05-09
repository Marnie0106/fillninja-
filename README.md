# FillNinja — AG2 Multi-Agent Form Autofill

> **C5-AG2 Challenge Submission** — FillNinja adapted as an AG2 Beta multi-agent system with 5 collaborating agents that discover, profile, plan, and fill online application forms.

---

## What It Does

FillNinja is an AI-powered form-filling assistant. You give it a goal (e.g. "find and fill scholarship applications for my startup"), and a pipeline of five specialized agents handles the rest:

1. **Search Curator** — discovers real application pages from live web search  
2. **Project Profiler** — extracts structured applicant data from PDF / DOCX / PPTX documents  
3. **Contact Supplement** — second-pass extraction focused on identity and contact fields  
4. **Planner** — decides which browser action to perform next (FILL / CLICK / SELECT / SCROLL …)  
5. **Reviewer** *(optional)* — gates risky actions such as form submission or payment clicks  

---

## Agent Architecture

```
User Request
    │
    ▼
┌──────────────────┐     ┌────────────────────────┐
│  Search Curator  │     │  Project Profiler       │
│  (Agent 1)       │     │  (Agent 2)              │
│  finds forms     │     │  extracts applicant     │
└────────┬─────────┘     │  data from documents    │
         │               └──────────┬─────────────┘
         │                          │
         │               ┌──────────▼─────────────┐
         │               │  Contact Supplement     │
         │               │  (Agent 3)              │
         │               │  refines contact fields │
         │               └──────────┬─────────────┘
         │                          │
         ▼                          ▼
   Discovered Forms  +  Applicant Facts
         │                          │
         └──────────────┬───────────┘
                        ▼
         ┌──────────────────────────────┐
         │  Planner (Agent 4)           │
         │  FILL / CLICK / SELECT / …   │
         └──────────────┬───────────────┘
                        │
                        ▼
         ┌──────────────────────────────┐
         │  Reviewer (Agent 5) optional │
         │  approves or blocks action   │
         └──────────────┬───────────────┘
                        │
                        ▼
                 Browser Action
```

Each agent uses `autogen.beta.Agent` with `PromptedSchema` for structured JSON output — no free-form text parsing needed.

---

## Quick Start

### 1. Clone & create virtual environment

```bash
git clone https://github.com/Marnie0106/fillninja-
cd fillninja-
python -m venv .venv
```

### 2. Activate the virtual environment

```bash
# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

> ⚠️ `ag2` installs from the GitHub source — this takes a few minutes on first run.

### 4. Configure API keys

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

Open `.env` and add your **OpenRouter API key** (free at https://openrouter.ai):

```env
OPENROUTER_API_KEY=sk-or-v1-your-key-here
```

### 5. Start the server

```bash
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload
```

### 6. Verify agents are running

```bash
curl http://127.0.0.1:8000/health
```

Or open http://127.0.0.1:8000 in your browser — you should see all 4 (or 5) agents listed.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Health check — lists all active agents |
| `GET`  | `/docs` | Swagger UI (interactive API docs) |
| `POST` | `/pipeline/discover` | Agent 1: discover application forms for a goal |
| `POST` | `/pipeline/discover_from_document` | Agents 1–3: discover + enrich with document data |
| `POST` | `/agent/run` | Agents 4–5: planner (+ reviewer) fill a form |
| `POST` | `/agent/prepare_applicant_context` | Agent 2: extract structured profile from text |
| `POST` | `/pipeline/demo` | Demo: Agents 1–3 collaborate end-to-end |

### Quick demo (no browser extension needed)

```bash
curl -X POST http://127.0.0.1:8000/pipeline/demo \
  -H "Content-Type: application/json" \
  -d '{"objective": "undergraduate research fellowship application"}'
```

---

## Configuration

All settings via `.env` (copy from `.env.example`). **No API keys are hardcoded.**

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENROUTER_API_KEY` | ✅ Yes | — | LLM API key (OpenRouter) |
| `OPENROUTER_MODEL` | No | `google/gemini-2.5-flash` | Model name |
| `OPENROUTER_BASE_URL` | No | `https://openrouter.ai/api/v1` | API endpoint |
| `TAVILY_API_KEY` | No | — | Tavily search (falls back to DuckDuckGo) |
| `FILLNINJA_ENABLE_REVIEWER` | No | — | Set `1` to activate Reviewer (Agent 5) |

---

## Project Structure

```
fillninja-/
├── server/
│   ├── main.py              # FastAPI app + all 5 agent definitions
│   ├── discovery.py         # Agent 1: Search Curator
│   ├── project_profile.py   # Agents 2 & 3: Profiler + Contact Supplement
│   ├── llm.py               # LLM config builder (OpenRouter)
│   ├── json_util.py         # JSON / PromptedSchema helpers
│   ├── document_extract.py  # PDF / DOCX / PPTX text extraction
│   ├── smart_source_url.py  # URL profile fetcher
│   └── web_fetch.py         # Async HTTP utilities
├── .env.example             # Environment variable template (no secrets)
├── .gitignore               # Excludes .env and build artifacts
├── requirements.txt         # Python dependencies
├── README.md                # This file
├── ATTRIBUTION.md           # Fork source and library credits
└── AI_LOG.md                # AI-assisted development log
```

---

## AG2 Beta Highlights

This project demonstrates AG2 Beta's structured-output API:

```python
from autogen.beta import Agent, PromptedSchema

agent = Agent(
    "curator",
    prompt=[CURATOR_SYSTEM],
    config=openai_config,
    response_schema=PromptedSchema(DiscoveryResult),  # Pydantic model
)

reply = await agent.ask(user_message)
result: DiscoveryResult = await reply.content()
```

Each of the 5 agents uses this pattern with a different Pydantic schema, ensuring structured, type-safe outputs that flow cleanly between agents.

---

## Original Project

Based on [FillNinja](https://github.com/Xavierhuang/fillninja) by Xavier Huang — a browser extension + FastAPI service for AI-assisted form filling.

**Changes in this fork:**
- Rewrote `server/main.py` to expose all 5 agents via a clean FastAPI REST API  
- Added `/pipeline/demo` endpoint for standalone multi-agent demo (no browser extension required)  
- Removed video transcription and Daytona sandbox (simplified for local demo)  
- All agents use `autogen.beta.Agent` + `PromptedSchema` throughout  

---

## License

MIT
