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

Each item must include fill_task: a short high-level instruction for the Fill agents (what to accomplish on this page). Concrete personal field values are appended automatically when the user supplied a document or project URL. Prefer: complete the application using user-provided facts; do not submit if the user asked for dry-run.

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
    """Combine templated objective queries with optional model-suggested phrases (deduplicated)."""
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


def _tavily_results_list(resp: Any) -> list[dict[str, Any]]:
    if isinstance(resp, dict):
        raw = resp.get("results") or []
    else:
        raw = getattr(resp, "results", None) or []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
        else:
            out.append(
                {
                    "url": getattr(item, "url", "") or "",
                    "title": getattr(item, "title", "") or "",
                    "content": getattr(item, "content", "") or "",
                }
            )
    return out


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
            resp = await client.search(
                q,
                max_results=per_query,
                search_depth="basic",
            )
        except Exception as e:
            logger.warning("tavily query failed %s: %s", q, e)
            continue
        for r in _tavily_results_list(resp):
            href = (r.get("url") or "").strip()
            if not href.startswith("http"):
                continue
            if href in seen_urls:
                continue
            seen_urls.add(href)
            title = str(r.get("title") or "")
            body = str(r.get("content") or "")[:400]
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


async def run_discovery(
    objective: str,
    max_forms: int,
    extra_search_queries: list[str] | None = None,
) -> DiscoveryResult:
    if max_forms < 1:
        max_forms = 1
    max_forms = min(max_forms, 20)

    backend = resolve_search_backend()
    if backend == "tavily":
        if not os.environ.get("TAVILY_API_KEY", "").strip():
            raise RuntimeError("TAVILY_API_KEY is required for Tavily search (or set FILLNINJA_SEARCH=ddgs).")
        if AsyncTavilyClient is None:
            raise RuntimeError(
                "Tavily search requires tavily-python. Install dependencies (pip install -r requirements.txt)."
            )

    queries = merged_search_queries(objective.strip(), extra_search_queries)
    snippets = await collect_search_snippets(queries)
    config = build_llm_config()
    curator = build_curator_agent(config)
    user_msg = (
        f"User objective:\n{objective.strip()}\n\n"
        f"Return at most {max_forms} forms.\n\n"
        f"Search snippets:\n{snippets}"
    )
    reply = await curator.ask(user_msg)
    try:
        parsed = await reply.content()
    except ValidationError:
        raw = reply.body
        if raw is None or not raw.strip():
            raise
        try:
            parsed = DiscoveryResult.model_validate_json(strip_markdown_json_fence(raw))
        except ValidationError:
            parsed = DiscoveryResult.model_validate_json(raw.strip())
    if parsed is None:
        raise RuntimeError("Curator returned empty content")
    forms = list(parsed.forms)[:max_forms]
    return DiscoveryResult(summary=parsed.summary, forms=forms)
