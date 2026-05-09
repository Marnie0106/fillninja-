# AI_LOG.md — AI-Assisted Development Log

## Project: FillNinja — C5-AG2 Challenge Submission

**Challenge:** C5-AG2 — Adapt an open-source project using AG2 Beta multi-agent framework  
**Base Repo:** https://github.com/Xavierhuang/fillninja  
**Fork:** https://github.com/Marnie0106/fillninja-  
**AI Tool:** WorkBuddy (AutoClaw)  

---

## Iteration 1 — Codebase Analysis

**Prompt:** Analyze the FillNinja GitHub repo. What agents does it already have? How are they structured?

**AI Output:**
- Identified existing use of `autogen.beta.Agent` and `PromptedSchema` in the original codebase
- Mapped 5 agent roles: Search Curator, Project Profiler, Contact Supplement, Planner, Reviewer
- Found that the original project had the agents but lacked a clean standalone demo endpoint

**Decision:** Keep the existing AG2 Beta patterns; add a `/pipeline/demo` endpoint that works without the Chrome extension.

---

## Iteration 2 — Multi-Agent Server Design

**Prompt:** Generate a FastAPI server that wires up all 5 AG2 Beta agents with clean REST endpoints. Use `PromptedSchema` for structured output.

**AI Output:**
- Generated `server/main.py` with 6 endpoints covering all agent combinations
- Each agent uses `autogen.beta.Agent` + `PromptedSchema(PydanticModel)` for typed, structured JSON replies
- Planner ↔ Reviewer two-agent mode controlled by `FILLNINJA_ENABLE_REVIEWER` env var (opt-in)

**Key design decision:** Reviewer is disabled by default to keep the demo simple; set `FILLNINJA_ENABLE_REVIEWER=1` to activate the 5th agent.

---

## Iteration 3 — Discovery & Profiler Agents

**Prompt:** Show me how Curator discovers forms and how Profiler extracts structured data. How do they collaborate?

**AI Output:**
- `discovery.py`: Curator receives web search snippets (DuckDuckGo or Tavily), returns `DiscoveryResult` with a list of `DiscoveredForm` objects (url, title, fill_task)
- `project_profile.py`: Profiler returns `ProjectProfileSummary`; Contact Supplement runs a second pass for email/phone/name fields
- Collaboration: Curator output + Profiler output merge in `/pipeline/discover_from_document`

**Refinement:** Added `enrich_discovered_forms_with_applicant_facts()` so each discovered form includes applicant facts inline — the Planner then uses them directly.

---

## Iteration 4 — Security & Clean Environment

**Prompt:** Check that no real API keys are committed. Clean up `.env` and `.env.example`.

**AI Output:**
- Found a Tavily API key commented inside `.env` — removed it
- Rewrote `.env.example` with placeholder values and clear comments
- Updated `.gitignore` to exclude `.env`, `__pycache__`, `.venv`, and build artifacts

---

## Iteration 5 — Documentation

**Prompt:** Write a README with an ASCII architecture diagram, quick-start steps, API table, and project structure.

**AI Output:**
- Full `README.md` with 5-agent pipeline diagram showing data flow
- Step-by-step quick start (venv → install → configure → run → verify)
- API endpoint reference table
- AG2 Beta code snippet showing the `PromptedSchema` pattern

---

## Agent Summary

| # | Agent | AG2 API | Schema | Role |
|---|-------|---------|--------|------|
| 1 | Search Curator | `autogen.beta.Agent` | `PromptedSchema(DiscoveryResult)` | Finds application form URLs from web search |
| 2 | Project Profiler | `autogen.beta.Agent` | `PromptedSchema(ProjectProfileSummary)` | Extracts structured applicant data from documents |
| 3 | Contact Supplement | `autogen.beta.Agent` | `PromptedSchema(ContactSupplement)` | Refines email, phone, name fields (second pass) |
| 4 | Planner | `autogen.beta.Agent` | `PromptedSchema(PlannerOutput)` | Decides browser action: FILL / CLICK / SELECT / … |
| 5 | Reviewer | `autogen.beta.Agent` | `PromptedSchema(ReviewOutput)` | Approves or blocks actions (submit / payment guard) |

---

## Multi-Agent Collaboration Patterns Demonstrated

- **Sequential pipeline:** Curator → Profiler + Contact Supplement → Planner → Reviewer  
- **Gating pattern:** Reviewer blocks Planner if action would submit a form without explicit user intent  
- **Enrichment pattern:** Profiler facts injected into every discovered form so Planner has full context  
- **Opt-in escalation:** 4-agent mode by default; 5th agent activated by environment flag  
