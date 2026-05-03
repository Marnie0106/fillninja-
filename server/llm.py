import os

from autogen.beta.config import OpenAIConfig


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


def build_llm_config() -> OpenAIConfig:
    return OpenAIConfig(
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
