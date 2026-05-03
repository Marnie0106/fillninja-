"""Shared helpers for parsing model output."""

from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

TModel = TypeVar("TModel", bound=BaseModel)


def strip_markdown_json_fence(text: str) -> str:
    s = text.strip()
    start = s.find("```")
    if start < 0:
        return s
    fragment = s[start:]
    lines = fragment.splitlines()
    if not lines:
        return s
    body: list[str] = []
    for line in lines[1:]:
        if line.strip() == "```":
            break
        body.append(line)
    inner = "\n".join(body).strip()
    return inner if inner else s


async def parse_prompted_agent_reply(reply: Any, model: type[TModel]) -> TModel | None:
    """Validate agent reply like ``reply.content()``, stripping markdown JSON fences when present."""
    try:
        parsed = await reply.content()
    except ValidationError:
        raw = reply.body
        if raw is None or not str(raw).strip():
            raise
        text = str(raw)
        try:
            return model.model_validate_json(strip_markdown_json_fence(text))
        except ValidationError:
            return model.model_validate_json(text.strip())
    else:
        return parsed
