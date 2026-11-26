from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

VERSION_TIMEOUT = 8
ENCODERS_TIMEOUT = 15
STREAMS_TIMEOUT = 20

_VERSION_PATTERN = re.compile(r"ffmpeg version (\S+)")
_ENCODER_PATTERN = re.compile(r"^\s*[VAS][.A-Z]{5}\s+(\w[\w.-]*)")
_AUDIO_STREAM_PATTERN = re.compile(r"Stream #\S+: Audio: (\w+)")

_encoder_cache: dict[str, frozenset[str]] = {}


def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def resolve_ffmpeg(configured: str = "") -> str | None:
    configured = configured.strip()
    if not configured:
        return shutil.which("ffmpeg")
    path = Path(configured).expanduser()
    if path.is_dir():
        path /= "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    return str(path) if path.is_file() else None


def ffmpeg_version(path: str) -> str | None:
    result = _run([path, "-version"], VERSION_TIMEOUT)
    if result is None or result.returncode != 0 or not result.stdout:
        return None
    match = _VERSION_PATTERN.match(result.stdout.splitlines()[0])
    return match.group(1) if match else None


def available_encoders(path: str) -> frozenset[str] | None:
    if path in _encoder_cache:
        return _encoder_cache[path]
    result = _run([path, "-hide_banner", "-encoders"], ENCODERS_TIMEOUT)
    if result is None or result.returncode != 0:
        return None
    names = frozenset(
        match.group(1)
        for line in result.stdout.splitlines()
        if (match := _ENCODER_PATTERN.match(line))
    )
    if not names:
        return None
    _encoder_cache[path] = names
    return names


def source_audio_codec(ffmpeg: str, source: str) -> str | None:
    result = _run([ffmpeg, "-hide_banner", "-i", source], STREAMS_TIMEOUT)
    if result is None:
        return None
    match = _AUDIO_STREAM_PATTERN.search(result.stderr)
    return match.group(1).lower() if match else None
