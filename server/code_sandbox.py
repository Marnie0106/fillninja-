"""Optional remote/local code execution for FillNinja (Daytona or Docker via AG2 beta)."""

import os
from typing import Any, cast

_MAX_CODE_CHARS = 200_000

_DAYTONA_HTML_HINT = (
    "Daytona returned HTML instead of JSON — check DAYTONA_API_URL. "
    "Use https://app.daytona.io/api or remove DAYTONA_API_URL so the SDK uses its default."
)


def sandbox_http_detail(exc: BaseException) -> str:
    """Turn huge HTML error bodies into a short API message."""
    msg = str(exc)
    lower = msg.lower()
    if "<!doctype html>" in lower or "<html" in lower:
        return _DAYTONA_HTML_HINT
    if len(msg) > 4000:
        return msg[:4000] + "…"
    return msg


def sandbox_backend() -> str:
    v = (os.environ.get("FILLNINJA_CODE_BACKEND") or "").strip().lower()
    if v in ("daytona", "docker"):
        return v
    return ""


def sandbox_configured() -> bool:
    return bool(sandbox_backend())


def sandbox_health_detail() -> dict[str, Any]:
    b = sandbox_backend()
    if not b:
        return {"enabled": False, "backend": None}
    out: dict[str, Any] = {"enabled": True, "backend": b}
    if b == "daytona":
        try:
            import daytona  # noqa: F401

            from autogen.beta.extensions.daytona import DaytonaCodeEnvironment  # noqa: F401

            out["import_ok"] = True
        except ImportError as e:
            out["import_ok"] = False
            out["hint"] = (
                'Install: pip install "ag2[daytona]". Put DAYTONA_API_KEY in .env (see .env.example).'
            )
            out["detail"] = str(e)
    else:
        try:
            import docker  # noqa: F401

            from autogen.beta.extensions.docker import DockerCodeEnvironment  # noqa: F401

            out["import_ok"] = True
        except ImportError as e:
            out["import_ok"] = False
            out["hint"] = 'Install: pip install "ag2[docker]" and ensure Docker is running. Optional env vars in .env — see .env.example.'
            out["detail"] = str(e)
    return out


def _normalize_language(raw: str) -> str:
    s = (raw or "python").strip().lower()
    if s in ("py", "python3"):
        s = "python"
    if s in ("sh", "shell"):
        s = "bash"
    if s in ("js",):
        s = "javascript"
    if s in ("ts",):
        s = "typescript"
    if s not in ("python", "bash", "javascript", "typescript"):
        raise ValueError(
            f"Unsupported language {raw!r}. Use python, bash, javascript, or typescript."
        )
    return s


def _code_timeout_sec() -> int:
    try:
        n = int(os.environ.get("FILLNINJA_CODE_TIMEOUT", "120"))
    except ValueError:
        return 120
    return max(1, min(n, 3600))


def _build_environment():
    b = sandbox_backend()
    if b == "daytona":
        from autogen.beta.extensions.daytona import DaytonaCodeEnvironment

        timeout = _code_timeout_sec()
        snap = (os.environ.get("FILLNINJA_DAYTONA_SNAPSHOT") or "").strip()
        image = (os.environ.get("FILLNINJA_DAYTONA_IMAGE") or "python:3.12-slim").strip()
        if snap:
            return DaytonaCodeEnvironment(snapshot=snap, timeout=timeout)
        return DaytonaCodeEnvironment(image=image, timeout=timeout)
    if b == "docker":
        from autogen.beta.extensions.docker import DockerCodeEnvironment

        image = (os.environ.get("FILLNINJA_DOCKER_IMAGE") or "python:3.12-slim").strip()
        network = (os.environ.get("FILLNINJA_DOCKER_NETWORK") or "none").strip()
        return DockerCodeEnvironment(
            image=image,
            timeout=_code_timeout_sec(),
            network_mode=network,
        )
    raise RuntimeError("FILLNINJA_CODE_BACKEND is not daytona or docker")


async def run_sandbox_code(code: str, language: str) -> Any:
    from autogen.beta.tools.code import CodeLanguage

    if not sandbox_configured():
        raise RuntimeError(
            "Code sandbox is disabled. Set FILLNINJA_CODE_BACKEND=daytona or docker."
        )
    if not (code or "").strip():
        raise ValueError("code must not be empty")
    if len(code) > _MAX_CODE_CHARS:
        raise ValueError(f"code exceeds maximum length ({_MAX_CODE_CHARS} characters)")
    lang = cast(CodeLanguage, _normalize_language(language))
    env = _build_environment()
    async with env:
        return await env.run(code, lang, context=None)
