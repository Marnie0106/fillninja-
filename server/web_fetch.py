"""Simple URL fetcher for project profiling. Avoids private IPs."""

import logging
import re
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 60_000
_TIMEOUT = 20


def normalize_and_validate_url(raw: str) -> str:
    url = raw.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("URL has no host")
    # Block private IPs
    if host in ("localhost", "127.0.0.1", "0.0.0.0") or host.startswith("192.168.") or host.startswith("10.") or re.match(r"172\.(1[6-9]|2\d|3[01])\.", host):
        raise ValueError("Private/internal URLs are not allowed")
    return url


async def fetch_url_text(url: str) -> str:
    url = normalize_and_validate_url(url)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "FillNinja/1.0"})
            resp.raise_for_status()
            ct = (resp.headers.get("content-type") or "").lower()
            if "pdf" in ct or "octet-stream" in ct:
                return "[Binary content — use file upload instead]"
            text = resp.text
            if len(text) > MAX_TEXT_CHARS:
                text = text[:MAX_TEXT_CHARS] + "\n\n[... truncated ...]"
            return text
    except Exception as e:
        logger.warning("fetch_url_text failed for %s: %s", url, e)
        raise
