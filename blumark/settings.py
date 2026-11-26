from __future__ import annotations

from PySide6.QtCore import QSettings

from .codecs import (
    AUDIO_MODES,
    CODECS,
    CONTAINERS,
    DEFAULT_AUDIO,
    DEFAULT_CODEC,
    DEFAULT_CONTAINER,
    ExportOptions,
)
from .utils import APP_NAME

DEFAULT_VOLUME = 80


class AppSettings:
    def __init__(self):
        self._store = QSettings(APP_NAME, APP_NAME)

    def _text(self, key: str, default: str = "") -> str:
        return str(self._store.value(key, default) or default)

    def _number(self, key: str, default: int) -> int:
        try:
            return int(self._store.value(key, default))
        except (TypeError, ValueError):
            return default

    def _choice(self, key: str, allowed, default: str) -> str:
        value = self._text(key, default)
        return value if value in allowed else default

    @property
    def ffmpeg_path(self) -> str:
        return self._text("ffmpeg/path")

    @ffmpeg_path.setter
    def ffmpeg_path(self, value: str) -> None:
        self._store.setValue("ffmpeg/path", value)

    @property
    def last_dir(self) -> str:
        return self._text("last_dir")

    @last_dir.setter
    def last_dir(self, value: str) -> None:
        self._store.setValue("last_dir", value)

    @property
    def volume(self) -> int:
        return max(0, min(100, self._number("volume", DEFAULT_VOLUME)))

    @volume.setter
    def volume(self, value: int) -> None:
        self._store.setValue("volume", int(value))

    @property
    def container(self) -> str:
        return self._choice("export/container", CONTAINERS, DEFAULT_CONTAINER)

    @container.setter
    def container(self, value: str) -> None:
        if value in CONTAINERS:
            self._store.setValue("export/container", value)

    @property
    def codec(self) -> str:
        return self._choice("export/codec", CODECS, DEFAULT_CODEC)

    @codec.setter
    def codec(self, value: str) -> None:
        if value in CODECS:
            self._store.setValue("export/codec", value)

    @property
    def audio_mode(self) -> str:
        return self._choice("export/audio", AUDIO_MODES, DEFAULT_AUDIO)

    @audio_mode.setter
    def audio_mode(self, value: str) -> None:
        if value in AUDIO_MODES:
            self._store.setValue("export/audio", value)

    @property
    def target(self) -> int:
        return max(0, self._number("export/target", 0))

    @target.setter
    def target(self, value: int) -> None:
        self._store.setValue("export/target", max(0, int(value)))

    def speed_for(self, codec_key: str) -> str:
        codec = CODECS[codec_key]
        return self._choice(f"export/{codec_key}/speed", codec.speeds, codec.default_speed)

    def set_speed(self, codec_key: str, value: str) -> None:
        if value in CODECS[codec_key].speeds:
            self._store.setValue(f"export/{codec_key}/speed", value)

    def quality_for(self, codec_key: str) -> int:
        codec = CODECS[codec_key]
        quality = self._number(f"export/{codec_key}/quality", codec.q_default)
        return max(codec.q_min, min(codec.q_max, quality))

    def set_quality(self, codec_key: str, value: int) -> None:
        codec = CODECS[codec_key]
        self._store.setValue(
            f"export/{codec_key}/quality", max(codec.q_min, min(codec.q_max, int(value)))
        )

    def export_options(self) -> ExportOptions:
        codec = self.codec
        return ExportOptions(
            self.container,
            codec,
            self.speed_for(codec),
            self.quality_for(codec),
            self.audio_mode,
            self.target,
        ).validated()
