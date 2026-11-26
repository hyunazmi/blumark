from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
import threading
import time

from PySide6.QtCore import QThread, Signal

from .codecs import ExportOptions, audio_args, container_args, output_size, video_args
from .ffmpeg_tools import CREATE_NO_WINDOW, source_audio_codec
from .utils import Rect

STALL_SECONDS = 45
WATCHDOG_INTERVAL = 2.0
PROGRESS_EVERY = 5
ERROR_LINES = 12
PARTIAL_SUFFIX = ".part"


def build_command(
    ffmpeg: str,
    source: str,
    destination: str,
    size: tuple[int, int],
    fps: float,
    options: ExportOptions,
) -> list[str]:
    width, height = size
    with_audio = options.audio != "none"
    command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostats",
        "-f", "rawvideo", "-pixel_format", "bgr24", "-video_size", f"{width}x{height}",
        "-framerate", f"{fps:.6f}", "-i", "pipe:0",
    ]
    if with_audio:
        command += ["-i", source]
    command += ["-map", "0:v:0"]
    if with_audio:
        command += ["-map", "1:a:0?"]

    out_width, out_height = output_size(width, height, options.target)
    if 0 < options.target < min(width, height):
        command += ["-vf", f"scale={out_width}:{out_height}:flags=lanczos"]
    elif (out_width, out_height) != (width, height):
        command += ["-vf", f"crop={out_width}:{out_height}"]

    command += video_args(options)
    command += audio_args(options)
    if options.audio == "encode":
        command += ["-shortest"]
    command += container_args(options)
    command.append(destination)
    return command


class ExportWorker(QThread):
    progress = Signal(int)
    done = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        ffmpeg: str,
        source: str,
        destination: str,
        rect: Rect,
        strength: int,
        feather: int,
        options: ExportOptions | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._ffmpeg = ffmpeg
        self._source = source
        self._destination = destination
        self._partial = destination + PARTIAL_SUFFIX
        self._rect = rect
        self._strength = strength
        self._feather = feather
        self._options = (options or ExportOptions()).validated()
        self._cancel = threading.Event()
        self._stalled = threading.Event()
        self._last_activity = time.monotonic()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            finished = self._export()
        except Exception as error:
            self._discard_partial()
            self.failed.emit(str(error))
            return
        if finished:
            self.done.emit(self._destination)
        else:
            self._discard_partial()
            self.cancelled.emit()

    def _export(self) -> bool:
        from .video_info import open_video

        capture, frame, info = open_video(self._source)
        process = None
        log = tempfile.TemporaryFile()
        try:
            self._check_audio_copy()
            command = build_command(
                self._ffmpeg, self._source, self._partial,
                (info.width, info.height), info.fps, self._options,
            )
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=log,
                creationflags=CREATE_NO_WINDOW,
            )
            self._last_activity = time.monotonic()
            stop_watchdog = threading.Event()
            threading.Thread(
                target=self._watch, args=(process, stop_watchdog), daemon=True
            ).start()
            try:
                pipe_closed = self._feed(process, capture, frame, info.frame_count)
            finally:
                stop_watchdog.set()
            if self._cancel.is_set():
                process.kill()
                process.wait()
                return False
            code = self._finish(process)
            if code != 0 or self._stalled.is_set():
                raise RuntimeError(self._error_text(log))
            if pipe_closed:
                raise RuntimeError("ffmpeg stopped reading frames before the video ended.")
            os.replace(self._partial, self._destination)
            self.progress.emit(100)
            return True
        finally:
            capture.release()
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
            log.close()

    def _feed(self, process: subprocess.Popen, capture, frame, total: int) -> bool:
        from .blur import apply_blur

        written = 0
        ok = True
        while ok and not self._cancel.is_set():
            apply_blur(frame, self._rect, self._strength, self._feather)
            try:
                process.stdin.write(frame.data)
            except OSError:
                return True
            self._last_activity = time.monotonic()
            written += 1
            if written % PROGRESS_EVERY == 0:
                self.progress.emit(min(99, written * 100 // total))
            ok, frame = capture.read()
        return False

    def _finish(self, process: subprocess.Popen) -> int:
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            return process.wait(timeout=STALL_SECONDS)
        except subprocess.TimeoutExpired:
            self._stalled.set()
            process.kill()
            return process.wait()

    def _error_text(self, log) -> str:
        log.seek(0)
        lines = log.read().decode(errors="replace").strip().splitlines()
        if lines:
            return "\n".join(lines[-ERROR_LINES:])
        if self._stalled.is_set():
            return (
                "ffmpeg stopped responding and was ended. "
                "Try different export settings (for example re-encode the audio)."
            )
        return "ffmpeg failed (no error message)."

    def _check_audio_copy(self) -> None:
        options = self._options
        if options.audio != "copy":
            return
        allowed = options.container_info.copy_audio
        codec = source_audio_codec(self._ffmpeg, self._source)
        if codec is not None and allowed and codec not in allowed:
            raise RuntimeError(
                f"The original audio is {codec.upper()}, which can't be copied into "
                f"{options.container.upper()}. Set Audio to \"Re-encode\" in Export Settings."
            )

    def _watch(self, process: subprocess.Popen, stop: threading.Event) -> None:
        while not stop.wait(WATCHDOG_INTERVAL):
            if self._cancel.is_set() or process.poll() is not None:
                return
            if time.monotonic() - self._last_activity > STALL_SECONDS:
                self._stalled.set()
                process.kill()
                return

    def _discard_partial(self) -> None:
        with contextlib.suppress(OSError):
            os.remove(self._partial)
