from __future__ import annotations

from . import __version__

APP_NAME = "Blumark"
APP_TITLE = f"{APP_NAME} v{__version__}"

Rect = tuple[int, int, int, int]

VIDEO_EXTS = frozenset({
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv",
    ".wmv", ".mpg", ".mpeg", ".ts", ".3gp",
})


def video_file_filter() -> str:
    patterns = " ".join(f"*{ext}" for ext in sorted(VIDEO_EXTS))
    return f"Video files ({patterns});;All files (*)"


def format_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes = int(seconds // 60)
    return f"{minutes:02d}:{seconds - minutes * 60:05.2f}"
