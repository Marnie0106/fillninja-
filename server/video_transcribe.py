"""Transcribe video to plain text via ffmpeg (audio extract) + OpenAI-compatible Whisper API."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

MAX_VIDEO_BYTES = 50 * 1024 * 1024


def _ffmpeg_bin() -> str:
    return os.environ.get("FILLNINJA_FFMPEG_PATH", "ffmpeg")


def video_suffixes() -> set[str]:
    return {
        ".mp4",
        ".webm",
        ".mov",
        ".mkv",
        ".mpeg",
        ".mpg",
        ".m4v",
        ".avi",
    }


def is_video_filename(name: str) -> bool:
    return Path(name).suffix.lower() in video_suffixes()


def _whisper_key() -> str | None:
    return (os.environ.get("FILLNINJA_WHISPER_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()


def _whisper_base_url() -> str:
    return os.environ.get("FILLNINJA_WHISPER_BASE_URL", "https://api.openai.com/v1").rstrip("/")


def _whisper_model() -> str:
    return os.environ.get("FILLNINJA_WHISPER_MODEL", "whisper-1")


def transcribe_video_bytes(data: bytes, filename: str) -> str:
    if len(data) > MAX_VIDEO_BYTES:
        raise ValueError(
            f"Video too large ({len(data)} bytes). Maximum is {MAX_VIDEO_BYTES // (1024 * 1024)} MB."
        )
    key = _whisper_key()
    if not key:
        raise ValueError(
            "Video transcription requires an OpenAI-compatible API key: set "
            "FILLNINJA_WHISPER_API_KEY or OPENAI_API_KEY (not OpenRouter-only keys; use a key that "
            "can call the official Whisper / audio transcriptions endpoint at api.openai.com unless you "
            "override FILLNINJA_WHISPER_BASE_URL)."
        )
    ffmpeg = _ffmpeg_bin()
    if not shutil.which(ffmpeg) and ffmpeg == "ffmpeg":
        raise ValueError(
            "Video upload requires ffmpeg on your PATH (or set FILLNINJA_FFMPEG_PATH). "
            "See https://ffmpeg.org/download.html"
        )

    suffix = Path(filename).suffix.lower() or ".mp4"
    with tempfile.TemporaryDirectory() as tmp:
        vin = Path(tmp) / f"input{suffix}"
        audio = Path(tmp) / "audio_for_whisper.mp3"
        vin.write_bytes(data)
        try:
            proc = subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(vin),
                    "-vn",
                    "-acodec",
                    "libmp3lame",
                    "-q:a",
                    "6",
                    str(audio),
                ],
                capture_output=True,
                timeout=600,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise ValueError("ffmpeg timed out while extracting audio from the video.") from e
        if proc.returncode != 0:
            err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
            raise ValueError(
                "Could not extract audio from the video (ffmpeg). "
                f"Install ffmpeg or try a different format. {err[:500]}"
            )
        if not audio.exists() or audio.stat().st_size == 0:
            raise ValueError("No audio track found or audio export failed (empty file).")

        audio_bytes = audio.read_bytes()
        url = f"{_whisper_base_url()}/audio/transcriptions"
        with httpx.Client(timeout=600.0) as client:
            resp = client.post(
                url,
                headers={"Authorization": f"Bearer {key}"},
                files={"file": ("audio.mp3", audio_bytes, "audio/mpeg")},
                data={"model": _whisper_model()},
            )
        if resp.status_code >= 400:
            detail = resp.text[:800]
            raise ValueError(
                f"Transcription API error HTTP {resp.status_code}: {detail}"
            )
        payload = resp.json()
        text = (payload.get("text") or "").strip()
        if not text:
            raise ValueError("Transcription returned empty text (no speech detected or model error).")
        return text
