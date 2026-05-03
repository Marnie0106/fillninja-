import logging
from typing import Any

from ddgs import DDGS
from pydantic import BaseModel, Field, ValidationError

from autogen.beta import Agent, PromptedSchema

from server.llm import build_llm_config

logger = logging.getLogger(__name__)

CURATOR_SYSTEM = """You are the Search Curator agent in FillNinja's multi-agent pipeline.
You receive the user's goal (scholarships, grants, surveys, job applications, programs, etc.) and noisy web search snippets (titles, URLs, short blurbs).

Pick distinct HTTPS pages where someone would realistically complete an application, registration, survey, or intake form.
Avoid: generic homepages with no form path, pure news, social timelines, obvious junk. Prefer .edu, foundations, company career portals, government forms when relevant.

Each item must include fill_task: a concrete instruction for the Fill agents (e.g. fill visible fields with plausible demo data and the user's stated intent; do not submit if the user asked for dry-run).

Your answer must match the JSON schema exactly."""

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


def collect_search_snippets(objective: str, max_per_query: int = 8) -> str:
    queries = [
        f"{objective} apply online application",
        f"{objective} application form register",
        f"{objective} scholarship grant fellowship apply",
    ]
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
    if not chunks:
        return "No search results returned. Broaden the objective or check network."
    text = "\n\n---\n\n".join(chunks)
    if len(text) > MAX_SNIPPET_CHARS:
        return text[:MAX_SNIPPET_CHARS] + "\n... [truncated]"
    return text


def build_curator_agent(config: Any) -> Agent:
    return Agent(
        "curator",
        prompt=[CURATOR_SYSTEM],
        config=config,
        response_schema=PromptedSchema(DiscoveryResult),
    )


async def run_discovery(objective: str, max_forms: int) -> DiscoveryResult:
    if max_forms < 1:
        max_forms = 1
    max_forms = min(max_forms, 20)

    snippets = collect_search_snippets(objective.strip())
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
        raise
    if parsed is None:
        raise RuntimeError("Curator returned empty content")
    forms = list(parsed.forms)[:max_forms]
    return DiscoveryResult(summary=parsed.summary, forms=forms)
