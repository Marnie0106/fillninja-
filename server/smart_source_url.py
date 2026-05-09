"""Classify well-known source URLs (GitHub, YouTube) and fetch text suited for project profiling."""

import re
from urllib.parse import parse_qs, urlparse

from server.web_fetch import MAX_TEXT_CHARS, fetch_url_text, normalize_and_validate_url


def _trim(text: str) -> str:
    if len(text) <= MAX_TEXT_CHARS:
        return text
    return text[:MAX_TEXT_CHARS] + "\n\n[... truncated ...]"


def _youtube_video_id(url: str) -> str | None:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    if host in ("youtu.be", "www.youtu.be"):
        seg = path.strip("/").split("/")[0] if path.strip("/") else ""
        return seg if _valid_youtube_id(seg) else None
    if "youtube.com" not in host and "youtube-nocookie.com" not in host:
        return None
    if path.startswith("/watch"):
        v = (parse_qs(parsed.query).get("v") or [""])[0].strip()
        return v if _valid_youtube_id(v) else None
    for prefix in ("/embed/", "/live/", "/shorts/"):
        if path.startswith(prefix):
            seg = path[len(prefix):].strip("/").split("/")[0]
            return seg if _valid_youtube_id(seg) else None
    return None


def _valid_youtube_id(s: str) -> bool:
    return bool(s and 6 <= len(s) <= 32 and re.fullmatch(r"[\w-]+", s))


async def fetch_smart_profile_url(url: str) -> str | None:
    """Fetch text from a public URL, with special handling for GitHub/YouTube."""
    try:
        normalized = normalize_and_validate_url(url)
    except ValueError:
        return None

    parsed = urlparse(normalized)
    host = (parsed.hostname or "").lower()

    # GitHub: try raw README
    if host in ("github.com", "www.github.com"):
        path = (parsed.path or "").rstrip("/")
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2:
            owner, repo = parts[0], parts[1]
            for branch in ("main", "master"):
                try:
                    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md"
                    text = await fetch_url_text(raw_url)
                    if text and len(text) > 50:
                        return _trim(text)
                except Exception:
                    continue

    # For all URLs, just fetch
    try:
        text = await fetch_url_text(normalized)
        return _trim(text) if text else None
    except Exception:
        return None
