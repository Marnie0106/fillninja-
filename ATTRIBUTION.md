# ATTRIBUTION.md

## Original Project

This project is a fork of **FillNinja** by Xavier Huang:

- **Repository:** https://github.com/Xavierhuang/fillninja
- **License:** MIT
- **Description:** A browser extension + FastAPI backend that uses an AG2 multi-agent pipeline to discover and auto-fill online application forms.

## What Changed in This Fork

| Area | Change |
|------|--------|
| `server/main.py` | Rewrote to cleanly expose all 5 AG2 Beta agents via FastAPI REST endpoints |
| `server/discovery.py` | Retained and refined the Search Curator agent with `PromptedSchema(DiscoveryResult)` |
| `server/project_profile.py` | Retained Project Profiler + Contact Supplement agents with structured Pydantic schemas |
| `/pipeline/demo` endpoint | **Added** — showcases 3-agent collaboration without requiring the Chrome extension |
| Video transcription | **Removed** — not required for the multi-agent demo |
| Daytona sandbox | **Removed** — simplified for local standalone run |
| `.env.example` | Updated with clear comments; no real API keys |
| `README.md` | Rewritten with architecture diagram, quick-start, and API reference |

## Frameworks & Libraries

| Library | License | Usage |
|---------|---------|-------|
| [AG2](https://github.com/ag2ai/ag2) | Apache-2.0 | Core multi-agent framework (`autogen.beta` API) |
| [FastAPI](https://github.com/tiangolo/fastapi) | MIT | HTTP API server |
| [Pydantic](https://github.com/pydantic/pydantic) | MIT | Structured agent output schemas |
| [Uvicorn](https://github.com/encode/uvicorn) | BSD-3-Clause | ASGI server |
| [ddgs](https://github.com/deedy5/duckduckgo_search) | MIT | DuckDuckGo web search fallback |
| [tavily-python](https://github.com/tavily-ai/tavily-python) | MIT | Tavily search API client (optional) |
| [pypdf](https://github.com/py-pdf/pypdf) | BSD-3-Clause | PDF text extraction |
| [python-docx](https://github.com/python-openxml/python-docx) | MIT | Word .docx text extraction |
| [python-pptx](https://github.com/scanny/python-pptx) | MIT | PowerPoint .pptx text extraction |
| [httpx](https://github.com/encode/httpx) | BSD-3-Clause | Async HTTP client |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | BSD-3-Clause | .env file loading |
| [beautifulsoup4](https://www.crummy.com/software/BeautifulSoup/) | MIT | HTML parsing for web fetch |

## AI Assistance

This fork was adapted for the C5-AG2 Challenge with AI assistance (WorkBuddy / AutoClaw). AI helped with:

- Analyzing the original FillNinja codebase and mapping existing agent patterns
- Generating the multi-agent FastAPI server (`server/main.py`) with all 5 AG2 Beta agents
- Designing the Planner → Reviewer gating flow
- Writing documentation (README.md, AI_LOG.md, ATTRIBUTION.md)
- Code review and security check (confirming no API keys are committed)

All generated code builds directly on the original FillNinja architecture and AG2 Beta patterns (`autogen.beta.Agent`, `PromptedSchema`, `OpenAIConfig`).
