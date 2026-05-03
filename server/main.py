import asyncio
import json
import logging
import os
import uuid
from typing import Any

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


@app.get("/", response_class=HTMLResponse)
async def root() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>FillNinja Agent API</title></head>
<body>
<h1>FillNinja Agent API</h1>
<p>Server is running. Use the links below to verify the API or inspect routes.</p>
<ul>
  <li><a href="/health">GET /health</a> &mdash; readiness check</li>
  <li><a href="/docs">GET /docs</a> &mdash; interactive API (Swagger UI)</li>
</ul>
<p>Use the Chrome extension against <code>http://localhost:8000</code> (same as this host).</p>
<p>Autonomous pipeline: <code>POST /pipeline/discover</code> or <code>POST /pipeline/discover_from_document</code>, then parallel fills from the extension.</p>
</body>
</html>"""


PLANNER_SYSTEM = """You are the planner agent in a FillNinja browser automation team (AG2).
You receive the user's goal, page metadata, a DOM snapshot, and prior step results.

Your reply must match the JSON schema the framework provides exactly.

Rules:
- One browser action per step, or set done=true when finished or when you must refuse.
- Action types (uppercase in "type" field): FILL, CLICK, SELECT, SCROLL, NAVIGATE, WAIT_FOR_ELEMENT.
- FILL params: selector (CSS string or integer index over input,textarea,select in document order), value (string); elementType optional.
- CLICK params: selector (CSS or index), elementType "button" or "link" when using index.
- SELECT params: selector, optionText (substring match).
- SCROLL params: direction "up"|"down", amount (pixels, number).
- NAVIGATE params: url (string).
- WAIT_FOR_ELEMENT params: selector (CSS), timeout (ms).
- Prefer ids/names from the snapshot. For Apply / Submit, pick the control listed in "buttons" (index or CSS) that matches the form you filled—avoid unrelated actions (search, newsletter).
- When the task text includes the Applicant data extracted block (from uploaded materials), use those lines as the source of truth for FILL values (exact strings when labels match). Do not fabricate personal data not present there.
- Respond with one raw JSON object only (no markdown code fences, no prose outside the JSON)."""


REVIEWER_SYSTEM = """You are the reviewer agent in the FillNinja AG2 team.
You see the user's task, page URL/title, and one proposed browser action (type + params).

Approve normal form fills, in-page clicks, scrolling, and benign navigation.
Reject only for clear harm: exfiltration, phishing-like URLs, or actions that contradict the user's task.

Your reply must match the JSON schema exactly (approved + reason).
Respond with one raw JSON object only (no markdown code fences, no prose outside the JSON)."""


class RunRequest(BaseModel):
    task: str
    page_info: dict[str, Any]
    dom_snapshot: dict[str, Any]
    tab_id: int | None = None


class ActionResultBody(BaseModel):
    action_id: str
    result: Any | None = None
    error: str | None = None


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


class AgentTask:
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.stopped = False
        self._action_futures: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self.runner: asyncio.Task[None] | None = None

    async def wait_action_result(self, action_id: str) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._action_futures[action_id] = fut
        try:
            return await fut
        finally:
            self._action_futures.pop(action_id, None)

    def resolve_action(self, action_id: str, payload: dict[str, Any]) -> None:
        fut = self._action_futures.get(action_id)
        if fut is not None and not fut.done():
            fut.set_result(payload)


tasks: dict[str, AgentTask] = {}


async def _cleanup_task_slot(task_id: str) -> None:
    await asyncio.sleep(120)
    tasks.pop(task_id, None)


def truncate_snapshot(snap: dict[str, Any], max_chars: int = 24000) -> str:
    text = json.dumps(snap, default=str, ensure_ascii=False)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated]"


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


def reviewer_enabled() -> bool:
    v = os.environ.get("FILLNINJA_ENABLE_REVIEWER", "1").lower()
    return v not in ("0", "false", "no", "off")


def normalize_action_model(action: BrowserActionModel) -> tuple[str, dict[str, Any]]:
    at = str(action.type).strip().upper()
    return at, dict(action.params)


async def run_agent_task(
    task_id: str,
    task_text: str,
    page_info: dict[str, Any],
    dom_snapshot: dict[str, Any],
) -> None:
    session = tasks.get(task_id)
    if session is None:
        return

    results_log: list[dict[str, Any]] = []

    try:
        config = build_llm_config()
        planner = build_planner_agent(config)
        reviewer = build_reviewer_agent(config) if reviewer_enabled() else None
    except RuntimeError as e:
        await session.event_queue.put({"type": "error", "error": str(e)})
        return

    try:
        for step in range(28):
            if session.stopped:
                await session.event_queue.put(
                    {"type": "error", "error": "Task cancelled"}
                )
                return

            user_content = (
                f"Step {step + 1}.\n"
                f"Task: {task_text}\n\n"
                f"page_info: {json.dumps(page_info, default=str, ensure_ascii=False)}\n\n"
                f"dom_snapshot: {truncate_snapshot(dom_snapshot)}\n\n"
                f"previous_results: {json.dumps(results_log, default=str, ensure_ascii=False)}"
            )

            await session.event_queue.put(
                {"log": f"Planner step {step + 1}...", "log_type": "planner"}
            )

            try:
                preply = await planner.ask(user_content)
                decision = await parse_prompted_agent_reply(preply, PlannerOutput)
            except ValidationError as e:
                logger.exception("Planner schema validation failed")
                await session.event_queue.put(
                    {"log": f"Planner output invalid: {e}", "log_type": "planner"}
                )
                await session.event_queue.put(
                    {"type": "error", "error": f"Invalid planner response: {e}"}
                )
                return
            except Exception as e:
                logger.exception("Planner LLM failed")
                await session.event_queue.put({"type": "error", "error": str(e)})
                return

            if decision is None:
                await session.event_queue.put(
                    {
                        "type": "error",
                        "error": "Planner returned empty content",
                    }
                )
                return

            if decision.reasoning:
                await session.event_queue.put(
                    {"log": decision.reasoning, "log_type": "planner"}
                )

            if decision.done:
                await session.event_queue.put({"type": "complete"})
                return

            if decision.action is None:
                await session.event_queue.put(
                    {
                        "type": "error",
                        "error": "Planner returned no action while done is false",
                    }
                )
                return

            if reviewer is not None:
                review_input = (
                    f"user_task: {task_text}\n"
                    f"page_url: {page_info.get('url', '')}\n"
                    f"page_title: {page_info.get('title', '')}\n"
                    f"proposed_action: {decision.action.model_dump_json(ensure_ascii=False)}\n"
                )
                await session.event_queue.put(
                    {"log": "Reviewer checking action...", "log_type": "reviewer"}
                )
                try:
                    rreply = await reviewer.ask(review_input)
                    review = await parse_prompted_agent_reply(rreply, ReviewOutput)
                except ValidationError as e:
                    logger.exception("Reviewer schema validation failed")
                    await session.event_queue.put(
                        {"type": "error", "error": f"Invalid reviewer response: {e}"}
                    )
                    return
                except Exception as e:
                    logger.exception("Reviewer LLM failed")
                    await session.event_queue.put({"type": "error", "error": str(e)})
                    return

                if review is None:
                    await session.event_queue.put(
                        {"type": "error", "error": "Reviewer returned empty content"}
                    )
                    return

                if review.reason:
                    await session.event_queue.put(
                        {"log": f"Reviewer: {review.reason}", "log_type": "reviewer"}
                    )

                if not review.approved:
                    results_log.append(
                        {
                            "step": step,
                            "reviewer_rejected": True,
                            "reason": review.reason,
                            "blocked_action": decision.action.model_dump(),
                        }
                    )
                    continue

            try:
                atype, params = normalize_action_model(decision.action)
            except Exception as e:
                await session.event_queue.put({"type": "error", "error": str(e)})
                return

            action_id = str(uuid.uuid4())
            payload = {
                "log": f"Execute {atype} {params}",
                "log_type": "executor",
                "action": {"id": action_id, "type": atype, "params": params},
            }
            await session.event_queue.put(payload)

            outcome = await session.wait_action_result(action_id)
            results_log.append(
                {
                    "step": step,
                    "action": atype,
                    "params": params,
                    "result": outcome.get("result"),
                    "error": outcome.get("error"),
                }
            )

        await session.event_queue.put(
            {"log": "Stopped after maximum steps", "log_type": "planner"}
        )
        await session.event_queue.put({"type": "complete"})
    finally:
        asyncio.create_task(_cleanup_task_slot(task_id))


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "pipeline": {
            "discover": "POST /pipeline/discover (JSON)",
            "discover_from_document": "POST /pipeline/discover_from_document (multipart: optional file, optional source_url, optional objective)",
            "search": discovery_search_health_detail(),
        },
        "ag2": {
            "planner": "autogen.beta.Agent + PromptedSchema(PlannerOutput)",
            "reviewer": "autogen.beta.Agent + PromptedSchema(ReviewOutput)"
            if reviewer_enabled()
            else "disabled",
            "curator": "autogen.beta.Agent + PromptedSchema(DiscoveryResult)",
        },
    }


@app.post("/pipeline/discover")
async def pipeline_discover(body: DiscoverRequest) -> dict[str, Any]:
    if not (
        os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    ):
        raise HTTPException(
            status_code=503,
            detail="OPENROUTER_API_KEY (or OPENAI_API_KEY) is not configured on the server",
        )
    try:
        result = await run_discovery(body.objective, body.max_forms)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except RuntimeError as e:
        msg = str(e)
        if "TAVILY_API_KEY" in msg or "tavily-python" in msg.lower():
            raise HTTPException(status_code=503, detail=msg) from e
        raise HTTPException(status_code=500, detail=msg) from e
    return result.model_dump()


@app.post("/pipeline/discover_from_document")
async def pipeline_discover_from_document(
    objective: str = Form(""),
    max_forms: int = Form(8),
    source_url: str = Form(""),
    file: UploadFile | None = File(None),
) -> dict[str, Any]:
    if not (
        os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    ):
        raise HTTPException(
            status_code=503,
            detail="OPENROUTER_API_KEY (or OPENAI_API_KEY) is not configured on the server",
        )
    url = source_url.strip()
    raw_name = ""
    file_body: bytes | None = None
    if file is not None:
        raw_name = (file.filename or "").strip()
        if raw_name:
            file_body = await file.read()
            if not file_body:
                raise HTTPException(status_code=422, detail="Empty file")

    if not url and file_body is None:
        raise HTTPException(
            status_code=422,
            detail="Provide an uploaded file and/or source_url (https://...)",
        )

    chunks: list[str] = []
    if url:
        try:
            fetched = await fetch_smart_profile_url(url)
            chunks.append(f"[Source: web URL]\n{fetched}")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    if file_body is not None:
        try:
            chunks.append(f"[Source: uploaded file {raw_name}]\n" + extract_text_from_bytes(file_body, raw_name))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    doc_text = "\n\n---\n\n".join(chunks)

    m = min(max(max_forms, 1), 20)
    hints = objective.strip()
    try:
        profile = await summarize_document_for_grants(doc_text)
        rich_objective = format_discovery_objective(hints, profile)
        extras = [s.strip() for s in profile.search_query_suggestions if s.strip()][:5]
        result = await run_discovery(rich_objective, m, extra_search_queries=extras or None)
        enriched = enrich_discovered_forms_with_applicant_facts(result.forms, profile)
        out = result.model_dump()
        out["forms"] = [f.model_dump() for f in enriched]
        out["project_profile"] = profile.model_dump()
        return out
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except RuntimeError as e:
        msg = str(e)
        if "TAVILY_API_KEY" in msg or "tavily-python" in msg.lower():
            raise HTTPException(status_code=503, detail=msg) from e
        raise HTTPException(status_code=500, detail=msg) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/agent/run")
async def start_run(body: RunRequest) -> dict[str, str]:
    if not (
        os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    ):
        raise HTTPException(
            status_code=503,
            detail="OPENROUTER_API_KEY (or OPENAI_API_KEY) is not configured on the server",
        )

    task_id = str(uuid.uuid4())
    agent = AgentTask(task_id)
    tasks[task_id] = agent
    agent.runner = asyncio.create_task(
        run_agent_task(task_id, body.task, body.page_info, body.dom_snapshot)
    )
    return {"task_id": task_id}


@app.get("/agent/{task_id}/events")
async def agent_events(task_id: str) -> StreamingResponse:
    agent = tasks.get(task_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Unknown task")

    async def gen() -> Any:
        while True:
            msg = await agent.event_queue.get()
            yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
            if msg.get("type") in ("complete", "error"):
                break

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/agent/{task_id}/action-result")
async def action_result(task_id: str, body: ActionResultBody) -> dict[str, bool]:
    agent = tasks.get(task_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Unknown task")
    agent.resolve_action(
        body.action_id,
        {"result": body.result, "error": body.error},
    )
    return {"ok": True}


@app.post("/agent/{task_id}/stop")
async def stop_task(task_id: str) -> dict[str, bool]:
    agent = tasks.get(task_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Unknown task")
    agent.stopped = True
    for fut in list(agent._action_futures.values()):
        if not fut.done():
            fut.set_result({"result": None, "error": "stopped"})
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server.main:app", host="127.0.0.1", port=8000)
