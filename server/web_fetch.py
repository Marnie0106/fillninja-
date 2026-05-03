"""Fetch public web pages (or direct PDF/DOCX/PPTX links) as plain text for profiling."""

import ipaddress
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from server.document_extract import extract_text_from_bytes

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
TIMEOUT_SEC = 20.0
MAX_TEXT_CHARS = 400_000


def _host_blocked(host: str) -> bool:
    h = host.lower().strip()
    if h in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return True
    if h.endswith(".localhost") or h.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(h)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return True
    except ValueError:
        pass
    return False


def normalize_and_validate_url(raw: str) -> str:
    u = raw.strip()
    if not u:
        raise ValueError("URL is empty")
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http and https URLs are supported")
    if not parsed.netloc:
        raise ValueError("Invalid URL")
    host = parsed.hostname
    if host is None or _host_blocked(host):
        raise ValueError("This URL is not allowed; use a public https:// page or file link")
    return u


def _trim_fetched(text: str) -> str:
    if len(text) <= MAX_TEXT_CHARS:
        return text
    return text[:MAX_TEXT_CHARS] + "\n\n[... truncated ...]"


async def fetch_url_text(url: str) -> str:
    """Download URL and return plain text (HTML stripped, or extract PDF/DOCX/PPTX when applicable)."""
    url = normalize_and_validate_url(url)
    headers = {
        "User-Agent": "FillNinja/1.0 (+https://github.com/Xavierhuang/fillninja; grant discovery)",
    }
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=TIMEOUT_SEC,
        headers=headers,
    ) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise ValueError(f"Could not fetch URL: {e}") from e

        final_path = urlparse(str(resp.url)).path.lower()
        path_suffix = Path(final_path).suffix.lower()

        body = resp.content
        if len(body) > MAX_RESPONSE_BYTES:
            body = body[:MAX_RESPONSE_BYTES]

        ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()

        if path_suffix == ".pdf" or "application/pdf" in ctype:
            return extract_text_from_bytes(body, "fetched.pdf")
        if path_suffix == ".docx" or "wordprocessingml.document" in ctype:
            return extract_text_from_bytes(body, "fetched.docx")
        if path_suffix == ".pptx" or "presentationml.presentation" in ctype or "presentationml.slideshow" in ctype:
            return extract_text_from_bytes(body, "fetched.pptx")

        if ctype.startswith("text/plain"):
            return _trim_fetched(body.decode(resp.encoding or "utf-8", errors="replace"))

        enc = resp.encoding or "utf-8"
        html = body.decode(enc, errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "template", "svg"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [ln for ln in (line.strip() for line in text.splitlines()) if ln]
        return _trim_fetched("\n".join(lines))
