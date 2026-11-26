from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QSpinBox,
    QVBoxLayout,
)

from . import hardware, icons
from .codecs import (
    CODECS,
    CONTAINERS,
    DEFAULT_AUDIO,
    DEFAULT_CODEC,
    DEFAULT_CONTAINER,
    compatible_codecs,
    resolution_choices,
)
from .ffmpeg_tools import available_encoders, resolve_ffmpeg
from .settings import AppSettings
from .widgets import IconLabel, JumpSlider

REFRESH_RETRY_MS = 300
STATUS_ICONS = {
    True: ("circle-check", "#2e9d5b"),
    False: ("circle-alert", "#d64545"),
    None: ("clock", "#8a8f98"),
}


class ExportSettingsDialog(QDialog):
    def __init__(
        self,
        settings: AppSettings,
        parent=None,
        video_size: tuple[int, int] | None = None,
    ):
        super().__init__(parent)
        self._settings = settings
        self._video_size = video_size
        self._resolution_touched = False
        self._loading = False
        self.setWindowTitle("Export Settings")
        self.setWindowIcon(icons.icon("film"))
        self.setMinimumWidth(500)

        self._ffmpeg = resolve_ffmpeg(settings.ffmpeg_path)
        self._available = available_encoders(self._ffmpeg) if self._ffmpeg else None
        self._pending = {
            key: (settings.speed_for(key), settings.quality_for(key)) for key in CODECS
        }
        self._audio = settings.audio_mode

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._container = QComboBox()
        for container in CONTAINERS.values():
            self._container.addItem(container.label, container.key)
        self._container.setCurrentIndex(max(0, self._container.findData(settings.container)))
        form.addRow(IconLabel("file", "Container"), self._container)

        self._codec = QComboBox()
        form.addRow(IconLabel("film", "Video codec"), self._codec)

        self._resolution = QComboBox()
        form.addRow(IconLabel("monitor", "Resolution"), self._resolution)

        self._speed = QComboBox()
        self._speed_title = IconLabel("gauge", "Speed")
        form.addRow(self._speed_title, self._speed)

        self._quality_slider = JumpSlider(focus=True)
        self._quality_spin = QSpinBox()
        quality_row = QHBoxLayout()
        quality_row.addWidget(self._quality_slider, 1)
        quality_row.addWidget(self._quality_spin)
        self._quality_title = IconLabel("sliders-horizontal", "Quality")
        form.addRow(self._quality_title, quality_row)

        self._audio_mode = QComboBox()
        form.addRow(IconLabel("volume-2", "Audio"), self._audio_mode)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setIcon(icons.icon("check"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setIcon(icons.icon("x"))
        restore = buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        restore.setIcon(icons.icon("rotate-ccw"))
        restore.clicked.connect(self._reset)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._container.currentIndexChanged.connect(self._on_container)
        self._codec.currentIndexChanged.connect(self._on_codec)
        self._speed.currentIndexChanged.connect(self._on_speed)
        self._quality_slider.valueChanged.connect(self._quality_spin.setValue)
        self._quality_spin.valueChanged.connect(self._quality_slider.setValue)
        self._quality_slider.valueChanged.connect(self._on_quality)
        self._audio_mode.currentIndexChanged.connect(self._on_audio)
        self._resolution.currentIndexChanged.connect(self._on_resolution)
        self._fill_resolution()

        if self._ffmpeg:
            probe = hardware.ensure_probe(self._ffmpeg)
            if probe is not None:
                probe.probed.connect(self._on_probed)

        self._fill_codecs(settings.codec)

    def _container_key(self) -> str:
        return self._container.currentData() or DEFAULT_CONTAINER

    def _codec_key(self) -> str | None:
        return self._codec.currentData()

    def _fill_resolution(self) -> None:
        self._loading = True
        self._resolution.clear()
        if self._video_size is None:
            self._resolution.addItem("Original size", 0)
            self._resolution.setEnabled(False)
        else:
            for target, label in resolution_choices(*self._video_size):
                self._resolution.addItem(label, target)
            index = self._resolution.findData(self._settings.target)
            self._resolution.setCurrentIndex(max(0, index))
            self._resolution.setEnabled(self._resolution.count() > 1)
        self._loading = False

    def _disable_item(self, index: int, tooltip: str) -> None:
        item = self._codec.model().item(index)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        item.setToolTip(tooltip)

    @staticmethod
    def _status_icon(works: bool | None) -> QIcon:
        name, color = STATUS_ICONS[works]
        pixmap = icons.pixmap(name, 16, color)
        icon = QIcon()
        icon.addPixmap(pixmap, QIcon.Mode.Normal)
        icon.addPixmap(pixmap, QIcon.Mode.Disabled)
        return icon

    def _fill_codecs(self, preferred: str | None) -> None:
        self._loading = True
        self._codec.clear()
        usable: list[int] = []
        for codec in compatible_codecs(self._container_key()):
            if not self._ffmpeg:
                self._codec.addItem(codec.label, codec.key)
                usable.append(self._codec.count() - 1)
                continue
            result = hardware.lookup(self._ffmpeg, codec.key, self._available)
            if result is None:
                self._codec.addItem(
                    self._status_icon(None), f"{codec.label} - Checking...", codec.key
                )
                self._disable_item(self._codec.count() - 1, "Testing your hardware...")
                continue
            works, reason = result
            verdict = "Supported" if works else "Not supported"
            self._codec.addItem(self._status_icon(works), f"{codec.label} - {verdict}", codec.key)
            index = self._codec.count() - 1
            if works:
                usable.append(index)
            else:
                self._disable_item(index, reason)
        index = self._codec.findData(preferred) if preferred else -1
        if index not in usable:
            index = usable[0] if usable else -1
        self._codec.setCurrentIndex(index)
        self._loading = False
        self._load_codec()
        self._fill_audio()

    def _load_codec(self) -> None:
        key = self._codec_key()
        for widget in (self._speed, self._quality_slider, self._quality_spin):
            widget.setEnabled(key is not None)
        self._loading = True
        self._speed.clear()
        if key is not None:
            codec = CODECS[key]
            speed, quality = self._pending[key]
            for value in codec.speeds:
                self._speed.addItem(value, value)
            self._speed.setCurrentIndex(max(0, self._speed.findData(speed)))
            self._quality_slider.setRange(codec.q_min, codec.q_max)
            self._quality_spin.setRange(codec.q_min, codec.q_max)
            self._quality_slider.setValue(quality)
            self._quality_spin.setValue(quality)
            self._speed_title.label.setText("Preset" if codec.speed_flag == "-preset" else "Speed")
            self._quality_title.label.setText(f"Quality ({codec.q_name})")
        self._loading = False

    def _fill_audio(self) -> None:
        container = CONTAINERS[self._container_key()]
        self._loading = True
        self._audio_mode.clear()
        self._audio_mode.addItem(f"Re-encode ({container.audio_label})", "encode")
        self._audio_mode.addItem("Copy original", "copy")
        self._audio_mode.addItem("No audio", "none")
        self._audio_mode.setCurrentIndex(max(0, self._audio_mode.findData(self._audio)))
        self._loading = False

    def _on_probed(self, *_) -> None:
        if self._loading:
            return
        if self._codec.view().isVisible():
            QTimer.singleShot(REFRESH_RETRY_MS, self._on_probed)
            return
        self._fill_codecs(self._codec_key() or self._settings.codec)

    def _on_container(self, *_) -> None:
        if not self._loading:
            self._fill_codecs(self._codec_key() or self._settings.codec)

    def _on_codec(self, *_) -> None:
        if not self._loading:
            self._load_codec()

    def _on_speed(self, *_) -> None:
        key = self._codec_key()
        if not self._loading and key is not None:
            self._pending[key] = (self._speed.currentData(), self._pending[key][1])

    def _on_quality(self, value: int) -> None:
        key = self._codec_key()
        if not self._loading and key is not None:
            self._pending[key] = (self._pending[key][0], int(value))

    def _on_audio(self, *_) -> None:
        if not self._loading:
            self._audio = self._audio_mode.currentData() or DEFAULT_AUDIO

    def _on_resolution(self, *_) -> None:
        if not self._loading:
            self._resolution_touched = True

    def _reset(self) -> None:
        self._pending = {
            key: (codec.default_speed, codec.q_default) for key, codec in CODECS.items()
        }
        self._audio = DEFAULT_AUDIO
        if self._video_size is not None and self._resolution.count():
            self._resolution.setCurrentIndex(0)
        self._loading = True
        self._container.setCurrentIndex(self._container.findData(DEFAULT_CONTAINER))
        self._loading = False
        self._fill_codecs(DEFAULT_CODEC)

    def accept(self) -> None:
        settings = self._settings
        settings.container = self._container_key()
        key = self._codec_key()
        if key is not None:
            settings.codec = key
        for codec_key, (speed, quality) in self._pending.items():
            settings.set_speed(codec_key, speed)
            settings.set_quality(codec_key, quality)
        settings.audio_mode = self._audio
        if self._video_size is not None and self._resolution_touched:
            settings.target = self._resolution.currentData() or 0
        super().accept()
