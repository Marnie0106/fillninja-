import asyncio
import json
import logging
import os
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from autogen.beta import Agent
from autogen.beta.config import OpenAIConfig

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
</body>
</html>"""


SYSTEM_PROMPT = """You are a browser automation agent. You receive a user task and a structured DOM snapshot (forms, inputs with indices, buttons, links).

Respond with ONLY valid JSON (no markdown fences) using this shape:
{
  "reasoning": "one short sentence",
  "done": true or false,
  "action": null or {
    "type": "FILL|CLICK|SELECT|SCROLL|NAVIGATE|WAIT_FOR_ELEMENT",
    "params": { }
  }
}

Param shapes:
- FILL: {"selector": "<css selector>" | <integer index>, "value": "<text>", "elementType": optional (ignored for css)}
  Index counts all input, textarea, select in document order (same as snapshot inputs[].index).
- CLICK: {"selector": "<css>" | <index>, "elementType": "button" | "link"} (elementType required when using integer index; default "button")
- SELECT: {"selector": "<css>" | <index>, "optionText": "<substring of option label or value>"}
- SCROLL: {"direction": "down" | "up", "amount": 500}
- NAVIGATE: {"url": "https://..."}
- WAIT_FOR_ELEMENT: {"selector": "<css>", "timeout": 5000}

Rules:
- One action per response. After each action you will see the result in previous_results.
- Prefer CSS selectors using id, name, or data-* from the snapshot when present.
- Set done:true when the task is finished or cannot be completed safely.
- For sensitive pages, refuse and set done:true with reasoning explaining why."""


class RunRequest(BaseModel):
    task: str
    page_info: dict[str, Any]
    dom_snapshot: dict[str, Any]
    tab_id: int | None = None


class ActionResultBody(BaseModel):
    action_id: str
    result: Any | None = None
    error: str | None = None


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


def parse_model_json(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines)
    return json.loads(raw)


def _openrouter_headers() -> dict[str, str]:
    referer = os.environ.get("OPENROUTER_HTTP_REFERER")
    title = os.environ.get("OPENROUTER_APP_TITLE", "FillNinja")
    headers: dict[str, str] = {"X-Title": title}
    if referer:
        headers["HTTP-Referer"] = referer
    return headers


def llm_api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError(
            "Set OPENROUTER_API_KEY (OpenRouter) or OPENAI_API_KEY in the environment"
        )
    return key


def build_fillninja_agent() -> Agent:
    config = OpenAIConfig(
        model=os.environ.get("OPENROUTER_MODEL", "google/gemini-2.5-flash"),
        streaming=False,
        api_key=llm_api_key(),
        base_url=os.environ.get(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ),
        max_completion_tokens=int(
            os.environ.get("OPENROUTER_MAX_COMPLETION_TOKENS", "1024")
        ),
        temperature=0.2,
        default_headers=_openrouter_headers(),
    )
    return Agent("fillninja", prompt=[SYSTEM_PROMPT], config=config)


def normalize_action(action: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    at = str(action["type"]).strip().upper()
    params = action.get("params")
    if not isinstance(params, dict):
        params = {}
    return at, params


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
        llm_agent = build_fillninja_agent()
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
                {"log": f"Planning step {step + 1}...", "log_type": "agent"}
            )

            try:
                reply = await llm_agent.ask(user_content)
                text = reply.body or "{}"
                decision = parse_model_json(text)
            except json.JSONDecodeError as e:
                logger.exception("Model JSON parse failed")
                await session.event_queue.put(
                    {"log": f"Model returned invalid JSON: {e}", "log_type": "agent"}
                )
                await session.event_queue.put(
                    {"type": "error", "error": f"Invalid model response: {e}"}
                )
                return
            except Exception as e:
                logger.exception("LLM call failed")
                await session.event_queue.put({"type": "error", "error": str(e)})
                return

            reasoning = decision.get("reasoning", "")
            if reasoning:
                await session.event_queue.put({"log": reasoning, "log_type": "agent"})

            if decision.get("done") is True:
                await session.event_queue.put({"type": "complete"})
                return

            action = decision.get("action")
            if not action or not isinstance(action, dict):
                await session.event_queue.put(
                    {
                        "type": "error",
                        "error": "Model returned no action while done is false",
                    }
                )
                return

            try:
                atype, params = normalize_action(action)
            except Exception as e:
                await session.event_queue.put({"type": "error", "error": str(e)})
                return

            action_id = str(uuid.uuid4())
            payload = {
                "log": f"Run {atype} {params}",
                "log_type": "agent",
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
            {"log": "Stopped after maximum steps", "log_type": "agent"}
        )
        await session.event_queue.put({"type": "complete"})
    finally:
        asyncio.create_task(_cleanup_task_slot(task_id))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
