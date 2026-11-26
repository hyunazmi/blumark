from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from . import icons
from .ffmpeg_tools import ffmpeg_version, resolve_ffmpeg
from .settings import AppSettings

OK_COLOR = "#2e9d5b"
ERROR_COLOR = "#d64545"


class FFmpegDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("FFmpeg Settings")
        self.setWindowIcon(icons.icon("terminal"))
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self._status = QLabel()
        self._status.setFixedSize(20, 20)
        self._path = QLineEdit(settings.ffmpeg_path)
        self._path.setClearButtonEnabled(True)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self._status)
        top.addWidget(self._path, 1)
        top.addWidget(self._button("folder-open", "Browse...", self._browse))
        layout.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        bottom.addWidget(self._button("search", "Auto-detect", self._auto_detect))
        bottom.addWidget(self._button("circle-check", "Test", self._test))
        bottom.addStretch(1)
        bottom.addWidget(self._button("check", "OK", self.accept, default=True))
        bottom.addWidget(self._button("x", "Cancel", self.reject))
        layout.addLayout(bottom)

        self._test()

    @staticmethod
    def _button(icon_name: str, text: str, slot, default: bool = False) -> QPushButton:
        button = QPushButton(icons.icon(icon_name), text)
        button.setAutoDefault(False)
        button.setDefault(default)
        button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        button.clicked.connect(slot)
        return button

    def _show_status(self, ok: bool, text: str) -> None:
        color = OK_COLOR if ok else ERROR_COLOR
        self._status.setPixmap(icons.pixmap("circle-check" if ok else "circle-alert", 18, color))
        self._status.setToolTip(text)

    def _browse(self) -> None:
        current = self._path.text().strip()
        start = current if current and Path(current).expanduser().exists() else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Select the ffmpeg executable", start)
        if path:
            self._path.setText(path)
            self._test()

    def _auto_detect(self) -> None:
        found = shutil.which("ffmpeg")
        if found:
            self._path.setText(found)
        else:
            self._path.clear()
        self._test()

    def _test(self) -> None:
        text = self._path.text()
        path = resolve_ffmpeg(text)
        if path is None:
            self._show_status(
                False,
                "ffmpeg file not found."
                if text.strip()
                else "ffmpeg was not found on PATH. Enter its location manually.",
            )
            return
        version = ffmpeg_version(path)
        if version is None:
            self._show_status(False, f"{path}\nNot a valid ffmpeg executable, or it can't be run.")
        else:
            self._show_status(True, f"ffmpeg {version}\n{path}")

    def accept(self) -> None:
        self._settings.ffmpeg_path = self._path.text().strip()
        super().accept()
