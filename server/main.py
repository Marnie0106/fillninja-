"""FillNinja Agent API — AG2 Beta multi-agent FastAPI server.

Agent roster (AG2 Beta):
  1. Search Curator  — discovers real application pages from web search
  2. Project Profiler — extracts structured applicant data from documents
  3. Contact Supplement — second-pass extraction for identity/contact fields
  4. Planner          — decides browser actions to fill forms
  5. Reviewer         — approves or blocks planner actions before execution
"""

import asyncio
import json
import logging
import os
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from autogen.beta import Agent, PromptedSchema
from autogen.beta.config import OpenAIConfig

from server.discovery import discovery_search_health_detail, run_discovery
from server.document_extract import extract_text_from_bytes
from server.project_profile import (
    enrich_discovered_forms_with_applicant_facts,
    format_discovery_objective,
    summarize_document_for_grants,
)
from server.smart_source_url import fetch_smart_profile_url
from server.llm import build_llm_config
from server.json_util import parse_prompted_agent_reply

logger = logging.getLogger(__name__)

app = FastAPI(title="FillNinja Agent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Agent system prompts
# ---------------------------------------------------------------------------

PLANNER_SYSTEM = """You are the planner agent in a FillNinja browser automation team (AG2).
You receive the user's goal, page metadata, a DOM snapshot, and prior step results.

Your reply must match the JSON schema the framework provides exactly.

Rules:
- One browser action per step, or set done=true when finished or when you must refuse.
- Action types (uppercase in "type" field): FILL, CLICK, SELECT, SCROLL, NAVIGATE, WAIT_FOR_ELEMENT.
- FILL params: selector (CSS string or integer index), value (string); elementType optional.
- CLICK params: selector (CSS or index), elementType "button" or "link" when using index.
- SELECT params: selector, optionText (substring match).
- SCROLL params: direction "up"|"down", amount (pixels, number).
- NAVIGATE params: url (string).
- WAIT_FOR_ELEMENT params: selector (CSS), timeout (ms).
- Prefer ids/names from the snapshot. Do not CLICK submit unless user explicitly asks to submit.
- When the task text includes the Applicant data block, use those lines as source of truth for FILL values.
- Respond with one raw JSON object only (no markdown code fences, no prose outside the JSON)."""

REVIEWER_SYSTEM = """You are the reviewer agent in the FillNinja AG2 team.
You see the user's task, page URL/title, and one proposed browser action (type + params).

Approve normal form fills, in-page clicks, scrolling, and benign navigation.
Reject CLICK when the proposed target would transmit the current form or complete payment, unless user_task explicitly requests submitting. Benign "Next", "Continue", "Apply" that advance a wizard are OK.
Reject for clear harm: exfiltration, phishing-like URLs, or actions contradicting the user's task.

Your reply must match the JSON schema exactly (approved + reason).
Respond with one raw JSON object only (no markdown code fences, no prose outside the JSON)."""


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class BrowserActionModel(BaseModel):
    type: str
    params: dict[str, Any] = Field(default_factory=dict)

class PlannerOutput(BaseModel):
    reasoning: str = ""
    done: bool = False
    action: BrowserActionModel | None = None

class ReviewOutput(BaseModel):
    approved: bool
    reason: str = ""

class DiscoverRequest(BaseModel):
    objective: str
    max_forms: int = 8

class RunRequest(BaseModel):
    task: str
    page_info: dict[str, Any]
    dom_snapshot: dict[str, Any]
    tab_id: int | None = None
    applicant_context: str | None = None

class PrepareApplicantContextBody(BaseModel):
    applicant_context: str


# ---------------------------------------------------------------------------
# Agent builders
# ---------------------------------------------------------------------------

def build_planner_agent(config: OpenAIConfig) -> Agent:
    return Agent(
        "planner",
        prompt=[PLANNER_SYSTEM],
        config=config,
        response_schema=PromptedSchema(PlannerOutput),
    )


def build_reviewer_agent(config: OpenAIConfig) -> Agent:
    return Agent(
        "reviewer",
        prompt=[REVIEWER_SYSTEM],
        config=config,
        response_schema=PromptedSchema(ReviewOutput),
    )


# ---------------------------------------------------------------------------
# Health & root
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def root() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>FillNinja Agent API</title></head>
<body>
<h1>FillNinja Agent API</h1>
<p>Server is running. <a href="/health">Health check</a> | <a href="/docs">Swagger UI</a></p>
<p>AG2 Beta multi-agent pipeline: Curator + Profiler + Planner + Reviewer</p>
</body></html>"""


@app.get("/health")
async def health() -> dict:
    search = discovery_search_health_detail()
    reviewer_enabled = bool(os.environ.get("FILLNINJA_ENABLE_REVIEWER", "").strip())
    agents_list = [
        {"name": "curator", "role": "Search Curator — discovers real application pages from web search"},
        {"name": "project_profiler", "role": "Project Profiler — extracts structured applicant data from documents"},
        {"name": "contact_supplement", "role": "Contact Supplement — second-pass extraction for identity/contact fields"},
        {"name": "planner", "role": "Planner — decides browser actions to fill forms"},
    ]
    if reviewer_enabled:
        agents_list.append({"name": "reviewer", "role": "Reviewer — approves or blocks planner actions"})
    return {
        "status": "ok",
        "pipeline": "AG2 Beta multi-agent",
        "agents": agents_list,
        "search": search,
        "reviewer_enabled": reviewer_enabled,
        "model": os.environ.get("OPENROUTER_MODEL", "google/gemini-2.5-flash"),
    }


# ---------------------------------------------------------------------------
# Discovery endpoints
# ---------------------------------------------------------------------------

@app.post("/pipeline/discover")
async def pipeline_discover(req: DiscoverRequest) -> dict:
    """Discover application forms for the given objective."""
    return await run_discovery(req.objective, req.max_forms)


@app.post("/pipeline/discover_from_document")
async def pipeline_discover_from_document(
    objective: str = Form(""),
    max_forms: int = Form(8),
    file: UploadFile | None = File(None),
    source_url: str = Form(""),
) -> dict:
    """Discover application forms enriched with document / URL profile data."""
    document_text = ""
    profile = None

    if file is not None:
        data = await file.read()
        document_text = extract_text_from_bytes(data, file.filename or "upload.pdf")
        profile = await summarize_document_for_grants(document_text)
    elif source_url.strip():
        url_text = await fetch_smart_profile_url(source_url.strip())
        if url_text:
            profile = await summarize_document_for_grants(url_text)

    # Build discovery objective
    disc_objective = objective.strip()
    extra_queries = None
    if profile is not None:
        disc_objective = format_discovery_objective(objective, profile)
        extra_queries = profile.search_query_suggestions

    result = await run_discovery(disc_objective, max_forms, extra_queries)

    # Enrich forms with applicant facts
    if profile is not None and result.get("forms"):
        result["forms"] = enrich_discovered_forms_with_applicant_facts(result["forms"], profile)
        result["profile"] = profile.model_dump()

    return result


# ---------------------------------------------------------------------------
# Agent run endpoint (planner + optional reviewer)
# ---------------------------------------------------------------------------

@app.post("/agent/run")
async def agent_run(req: RunRequest) -> dict:
    """Run the planner agent (and optionally reviewer) on a page."""
    config = build_llm_config()
    planner = build_planner_agent(config)

    context_parts = [
        f"User task: {req.task}",
        f"Page URL: {req.page_info.get('url', '')}",
        f"Page title: {req.page_info.get('title', '')}",
    ]
    if req.applicant_context:
        context_parts.append(f"\nApplicant context:\n{req.applicant_context}")
    context_parts.append(f"\nDOM snapshot:\n{json.dumps(req.dom_snapshot, ensure_ascii=False)[:8000]}")

    reply = await planner.ask("\n".join(context_parts))
    planner_result = await parse_prompted_agent_reply(reply, PlannerOutput)
    if planner_result is None:
        return {"error": "Planner returned unparseable output", "raw": str(reply.body if hasattr(reply, 'body') else reply)}

    # Optional reviewer
    reviewer_enabled = bool(os.environ.get("FILLNINJA_ENABLE_REVIEWER", "").strip())
    review = None
    if reviewer_enabled and planner_result.action and not planner_result.done:
        reviewer = build_reviewer_agent(config)
        review_prompt = (
            f"User task: {req.task}\n"
            f"Page: {req.page_info.get('url', '')}\n"
            f"Proposed action: {planner_result.action.type} {planner_result.action.params}"
        )
        rev_reply = await reviewer.ask(review_prompt)
        review = await parse_prompted_agent_reply(rev_reply, ReviewOutput)
        if review and not review.approved:
            return {
                "planner": planner_result.model_dump(),
                "review": review.model_dump(),
                "blocked": True,
                "block_reason": review.reason,
            }

    result: dict = {"planner": planner_result.model_dump()}
    if review:
        result["review"] = review.model_dump()
    return result


# ---------------------------------------------------------------------------
# Applicant context endpoint
# ---------------------------------------------------------------------------

@app.post("/agent/prepare_applicant_context")
async def prepare_applicant_context(body: PrepareApplicantContextBody) -> dict:
    """Process applicant context text through the profiler agent."""
    text = (body.applicant_context or "").strip()
    if not text:
        return {"profile": None}
    profile = await summarize_document_for_grants(text)
    return {"profile": profile.model_dump()}


# ---------------------------------------------------------------------------
# Standalone demo: multi-agent orchestration
# ---------------------------------------------------------------------------

@app.post("/pipeline/demo")
async def pipeline_demo(req: DiscoverRequest) -> dict:
    """Demo: Curator discovers forms, Profiler enriches with mock applicant data.

    This endpoint showcases 2+ AG2 Beta agents collaborating:
    1. Search Curator — finds relevant application pages
    2. Project Profiler — structures the user's objective into profile data
    3. Contact Supplement — refines contact fields (triggered inside profiler)
    """
    config = build_llm_config()

    # Agent 1: Curator discovers forms
    discovery = await run_discovery(req.objective, req.max_forms)

    # Agent 2+3: Profiler + Contact Supplement extract structured data
    profile = await summarize_document_for_grants(req.objective)

    # Enrich discovered forms with applicant facts
    if profile and discovery.get("forms"):
        discovery["forms"] = enrich_discovered_forms_with_applicant_facts(discovery["forms"], profile)

    return {
        "objective": req.objective,
        "discovery": discovery,
        "profile": profile.model_dump() if profile else None,
        "agents_used": ["curator", "project_profiler", "contact_supplement"],
    }
