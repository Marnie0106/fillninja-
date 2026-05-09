import asyncio
import logging
import os
from typing import Any, Literal

from ddgs import DDGS
from pydantic import BaseModel, Field, ValidationError

from autogen.beta import Agent, PromptedSchema

from server.json_util import strip_markdown_json_fence
from server.llm import build_llm_config

try:
    from tavily import AsyncTavilyClient
except ImportError:
    AsyncTavilyClient = None

logger = logging.getLogger(__name__)

CURATOR_SYSTEM = """You are the Search Curator agent in FillNinja's multi-agent pipeline.
You receive the user's goal (scholarships, grants, surveys, job applications, programs, etc.) and noisy web search snippets (titles, URLs, short blurbs).

Pick distinct HTTPS pages where someone would realistically complete an application, registration, survey, or intake form.
Avoid: generic homepages with no form path, pure news, social timelines, obvious junk. Prefer .edu, foundations, company career portals, government forms when relevant.

Each item must include fill_task: a short high-level instruction for the Fill agents (what to accomplish on this page). Concrete personal field values are appended automatically when the user supplied a document or project URL. Prefer: fill required fields using user-provided facts; do not instruct the fill agent to submit or send the form unless the user's objective explicitly asks for submission. Do not submit if the user asked for a dry-run.

Return one JSON object only: no markdown, no code fences, no text before or after."""

MAX_SNIPPET_CHARS = 22000
MAX_RAW_RESULTS = 80


class DiscoveredForm(BaseModel):
    url: str
    title: str = ""
    fill_task: str
    relevance: str = ""


class DiscoveryResult(BaseModel):
    summary: str = ""
    forms: list[DiscoveredForm] = Field(default_factory=list)


def resolve_search_backend() -> Literal["tavily", "ddgs"]:
    mode = os.environ.get("FILLNINJA_SEARCH", "auto").strip().lower()
    if mode not in ("auto", "tavily", "ddgs"):
        mode = "auto"
    if mode == "tavily":
        return "tavily"
    if mode == "ddgs":
        return "ddgs"
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    return "tavily" if key else "ddgs"


def discovery_search_health_detail() -> dict[str, str]:
    backend = resolve_search_backend()
    if backend == "tavily":
        desc = "Tavily Search (live web) + AG2 curator agent"
    else:
        desc = "ddgs (DuckDuckGo) + AG2 curator agent"
    return {"backend": backend, "description": desc}


def _discovery_queries(objective: str) -> list[str]:
    o = objective.strip()
    if not o:
        o = "research grants fellowships scholarships application"
    return [
        f"{o} apply online application",
        f"{o} application form register",
        f"{o} scholarship grant fellowship apply",
    ]


def merged_search_queries(objective: str, extra: list[str] | None, max_queries: int = 6) -> list[str]:
    base = _discovery_queries(objective)
    if not extra:
        return base[:max_queries]
    seen: set[str] = {q.casefold() for q in base}
    out = list(base)
    for raw in extra:
        q = (raw or "").strip()
        if not q or q.casefold() in seen:
            continue
        seen.add(q.casefold())
        out.append(q)
        if len(out) >= max_queries:
            break
    return out


def _format_snippet_chunks(chunks: list[str]) -> str:
    if not chunks:
        return "No search results returned. Broaden the objective or check network."
    text = "\n\n---\n\n".join(chunks)
    if len(text) > MAX_SNIPPET_CHARS:
        return text[:MAX_SNIPPET_CHARS] + "\n... [truncated]"
    return text


def collect_search_snippets_ddgs(queries: list[str], max_per_query: int = 8) -> str:
    chunks: list[str] = []
    seen_urls: set[str] = set()
    with DDGS() as ddgs:
        for q in queries:
            try:
                for r in ddgs.text(q, max_results=max_per_query):
                    href = (r.get("href") or "").strip()
                    if not href.startswith("http"):
                        continue
                    if href in seen_urls:
                        continue
                    seen_urls.add(href)
                    title = r.get("title") or ""
                    body = str(r.get("body") or "")[:400]
                    chunks.append(f"title: {title}\nurl: {href}\n{body}")
                    if len(chunks) >= MAX_RAW_RESULTS:
                        break
            except Exception as e:
                logger.warning("ddgs query failed %s: %s", q, e)
            if len(chunks) >= MAX_RAW_RESULTS:
                break
    return _format_snippet_chunks(chunks)


async def collect_search_snippets_tavily(queries: list[str], max_per_query: int = 8) -> str:
    if AsyncTavilyClient is None:
        raise RuntimeError(
            "Tavily search requires the tavily-python package. Install dependencies (pip install -r requirements.txt)."
        )
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not set")
    client = AsyncTavilyClient(api_key)
    chunks: list[str] = []
    seen_urls: set[str] = set()
    per_query = min(max(max_per_query, 1), 20)
    for q in queries:
        try:
            resp = await client.search(q, max_results=per_query, search_depth="basic")
        except Exception as e:
            logger.warning("tavily query failed %s: %s", q, e)
            continue
        for r in (resp.get("results", []) if isinstance(resp, dict) else getattr(resp, "results", [])):
            href = (r.get("url", "") if isinstance(r, dict) else getattr(r, "url", "")).strip()
            if not href.startswith("http") or href in seen_urls:
                continue
            seen_urls.add(href)
            title = str(r.get("title", "") if isinstance(r, dict) else getattr(r, "title", ""))
            body = str(r.get("content", "") if isinstance(r, dict) else getattr(r, "content", ""))[:400]
            chunks.append(f"title: {title}\nurl: {href}\n{body}")
            if len(chunks) >= MAX_RAW_RESULTS:
                break
        if len(chunks) >= MAX_RAW_RESULTS:
            break
    return _format_snippet_chunks(chunks)


async def collect_search_snippets(queries: list[str], max_per_query: int = 8) -> str:
    backend = resolve_search_backend()
    if backend == "tavily":
        return await collect_search_snippets_tavily(queries, max_per_query)
    return await asyncio.to_thread(collect_search_snippets_ddgs, queries, max_per_query)


def build_curator_agent(config: Any) -> Agent:
    return Agent(
        "curator",
        prompt=[CURATOR_SYSTEM],
        config=config,
        response_schema=PromptedSchema(DiscoveryResult),
    )


async def run_curator(objective: str, extra_queries: list[str] | None = None) -> DiscoveryResult:
    queries = merged_search_queries(objective, extra_queries)
    snippets = await collect_search_snippets(queries)
    config = build_llm_config()
    agent = build_curator_agent(config)
    user_msg = f"Objective: {objective}\n\nSearch snippets:\n{snippets}"
    reply = await agent.ask(user_msg)
    raw = await reply.content()
    if isinstance(raw, DiscoveryResult):
        return raw
    if isinstance(raw, str):
        return DiscoveryResult.model_validate_json(strip_markdown_json_fence(raw))
    return DiscoveryResult()


async def run_discovery(objective: str, max_forms: int = 8, extra_queries: list[str] | None = None) -> dict:
    result = await run_curator(objective, extra_queries)
    trimmed = result.forms[:max_forms]
    return {
        "summary": result.summary,
        "forms": [f.model_dump() for f in trimmed],
        "total": len(result.forms),
        "returned": len(trimmed),
    }
