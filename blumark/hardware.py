from __future__ import annotations

import re
import subprocess

from PySide6.QtCore import QThread, Signal

from .codecs import CODECS, ExportOptions, video_args
from .ffmpeg_tools import CREATE_NO_WINDOW, available_encoders

PROBE_TIMEOUT = 25

MSG_NO_ENCODER = "This ffmpeg build doesn't include the encoder."
MSG_NO_GPU = "No compatible NVIDIA graphics card or driver was found."
MSG_NO_HARDWARE = "This computer can't run this encoder."
MSG_TOO_SLOW = "The test encode took too long."

_GPU_ERROR = re.compile(r"nvenc|cuda|NVIDIA", re.IGNORECASE)

_results: dict[tuple[str, str], tuple[bool, str]] = {}
_current: CodecProbe | None = None


def probe_codec(
    ffmpeg: str, key: str, running: list[subprocess.Popen] | None = None
) -> tuple[bool, str]:
    codec = CODECS[key]
    options = ExportOptions(
        codec.containers[0], key, codec.default_speed, codec.q_default, "none"
    ).validated()
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10",
        "-frames:v", "3", *video_args(options), "-f", "null", "-",
    ]
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW,
        )
    except OSError:
        return False, MSG_NO_HARDWARE
    if running is not None:
        running[:] = [process]
    try:
        _, error = process.communicate(timeout=PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        return False, MSG_TOO_SLOW
    if process.returncode == 0:
        return True, ""
    if "nvenc" in key or _GPU_ERROR.search(error.decode(errors="replace")):
        return False, MSG_NO_GPU
    return False, MSG_NO_HARDWARE


def lookup(ffmpeg: str, key: str, available: frozenset[str] | None) -> tuple[bool, str] | None:
    if available is not None and key not in available:
        return False, MSG_NO_ENCODER
    return _results.get((ffmpeg, key))


def check(ffmpeg: str, key: str, available: frozenset[str] | None) -> tuple[bool, str]:
    known = lookup(ffmpeg, key, available)
    if known is None:
        known = probe_codec(ffmpeg, key)
        _results[(ffmpeg, key)] = known
    return known


class CodecProbe(QThread):
    probed = Signal(str, bool, str)

    def __init__(self, ffmpeg: str, parent=None):
        super().__init__(parent)
        self.ffmpeg = ffmpeg
        self._running: list[subprocess.Popen] = []
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True
        for process in list(self._running):
            try:
                process.kill()
            except OSError:
                pass

    def run(self) -> None:
        available = available_encoders(self.ffmpeg)
        for key in CODECS:
            if self._stopped:
                return
            if (available is not None and key not in available) or (self.ffmpeg, key) in _results:
                continue
            works, reason = probe_codec(self.ffmpeg, key, self._running)
            if self._stopped:
                return
            _results[(self.ffmpeg, key)] = (works, reason)
            self.probed.emit(key, works, reason)


def ensure_probe(ffmpeg: str) -> CodecProbe | None:
    global _current
    if _current is not None and _current.isRunning():
        if _current.ffmpeg == ffmpeg:
            return _current
        _current.stop()
        _current.wait(3000)
    pending = [key for key in CODECS if (ffmpeg, key) not in _results]
    if not pending:
        return None
    _current = CodecProbe(ffmpeg)
    _current.start()
    return _current


def shutdown() -> None:
    if _current is not None and _current.isRunning():
        _current.stop()
        _current.wait(5000)
