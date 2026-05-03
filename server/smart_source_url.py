"""Classify well-known source URLs (GitHub, YouTube) and fetch text suited for project profiling."""

import asyncio
import re
from urllib.parse import parse_qs, urlparse

from server.web_fetch import MAX_TEXT_CHARS, fetch_url_text, normalize_and_validate_url


def _trim(text: str) -> str:
    if len(text) <= MAX_TEXT_CHARS:
        return text
    return text[:MAX_TEXT_CHARS] + "\n\n[... truncated ...]"


def _youtube_video_id(url: str) -> str | None:
    raw = url.strip()
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""

    if host in ("youtu.be", "www.youtu.be"):
        seg = path.strip("/").split("/")[0] if path.strip("/") else ""
        return seg if _valid_youtube_id(seg) else None

    if "youtube.com" not in host and "youtube-nocookie.com" not in host:
        return None

    if path.startswith("/watch") or path.startswith("/watch/"):
        v = (parse_qs(parsed.query).get("v") or [""])[0].strip()
        return v if _valid_youtube_id(v) else None
    for prefix in ("/embed/", "/live/", "/shorts/"):
        if path.startswith(prefix):
            seg = path[len(prefix) :].strip("/").split("/")[0]
            return seg if _valid_youtube_id(seg) else None
    m = re.match(r"^/v/([^/?#]+)", path)
    if m and _valid_youtube_id(m.group(1)):
        return m.group(1)
    return None


def _valid_youtube_id(s: str) -> bool:
    if not s or len(s) < 6 or len(s) > 32:
        return False
    return bool(re.fullmatch(r"[\w-]+", s))


def _github_raw_candidates(url: str) -> list[str]:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if host == "raw.githubusercontent.com":
        return []
    if host not in ("github.com", "www.github.com"):
        return []
    path = (parsed.path or "").rstrip("/")
    parts = [p for p in path.split("/") if p]
    if not parts:
        return []

    owner, repo = parts[0], parts[1]

    if len(parts) >= 5 and parts[2] == "blob":
        ref = parts[3]
        tail = "/".join(parts[4:])
        raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{tail}"
        return [raw]

    readmes = ("README.md", "readme.md", "Readme.md", "README.rst")

    if len(parts) >= 4 and parts[2] == "tree":
        ref = parts[3]
        base = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}"
        return [f"{base}/{name}" for name in readmes]

    if len(parts) == 2:
        out: list[str] = []
        for branch in ("main", "master"):
            base = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}"
            for name in readmes:
                out.append(f"{base}/{name}")
        return out

    return []


def _github_ui_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ("github.com", "www.github.com")


def _fetched_transcript_plain(fetched: object) -> str:
    return " ".join(getattr(s, "text", "") for s in fetched).strip()


def _youtube_transcript_sync(video_id: str) -> str:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import CouldNotRetrieveTranscript, IpBlocked, NoTranscriptFound
    except ImportError as e:
        raise ValueError(
            "YouTube transcript support requires the optional dependency: pip install youtube-transcript-api"
        ) from e

    api = YouTubeTranscriptApi()

    try:
        for langs in (("en", "en-US", "en-GB"), ("en",)):
            try:
                fetched = api.fetch(video_id, languages=langs)
                text = _fetched_transcript_plain(fetched)
                if text:
                    return text
            except NoTranscriptFound:
                continue

        transcript_list = api.list(video_id)
        for tr in transcript_list:
            try:
                fetched = tr.fetch()
                text = _fetched_transcript_plain(fetched)
                if text:
                    return text
            except CouldNotRetrieveTranscript:
                continue
    except IpBlocked as e:
        raise ValueError(
            "YouTube is blocking transcript requests from this network (rate limits or datacenter IP). "
            "Retry from another network, use a proxy per youtube-transcript-api docs, "
            "or upload the video file for Whisper transcription."
        ) from e
    except CouldNotRetrieveTranscript as e:
        raise ValueError(
            "No captions or transcript could be retrieved for this YouTube video. "
            "Try a video with subtitles, another link, or upload the video file."
        ) from e

    raise ValueError(
        "No captions or transcript are available for this YouTube video. "
        "Try a video with subtitles/captions, a different link, or upload a video file."
    )


async def fetch_smart_profile_url(url: str) -> str:
    """Fetch URL text for profiling: YouTube captions, GitHub raw/README when possible, else generic HTML/file fetch."""
    normalized = normalize_and_validate_url(url)

    yt = _youtube_video_id(normalized)
    if yt:
        transcript = await asyncio.to_thread(_youtube_transcript_sync, yt)
        if not transcript:
            raise ValueError("YouTube transcript was empty.")
        return _trim(
            "[Source: YouTube closed captions / auto transcript — spoken words only, not visuals]\n" + transcript
        )

    gh_list = _github_raw_candidates(normalized)
    if gh_list:
        for cand in gh_list:
            try:
                body = await fetch_url_text(cand)
                if body.strip():
                    return _trim(
                        "[Source: GitHub repository text (raw file / README)]\n" + body.strip()
                    )
            except ValueError:
                continue
        # All raw/README guesses failed; fall through to GitHub HTML or generic fetch.

    if _github_ui_host(normalized):
        body = await fetch_url_text(normalized)
        return _trim("[Source: GitHub page (HTML text)]\n" + body)

    body = await fetch_url_text(normalized)
    host = (urlparse(normalized).hostname or "").lower()
    label = (
        "[Source: GitHub raw file]"
        if host == "raw.githubusercontent.com"
        else "[Source: web URL]"
    )
    return _trim(label + "\n" + body)
