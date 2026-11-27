from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QFontDatabase,
    QGuiApplication,
    QKeySequence,
    QShortcut,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer, QVideoSink
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QSizePolicy,
    QSpinBox,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from . import hardware, icons
from .codecs import ExportOptions
from .export_dialog import ExportSettingsDialog
from .exporter import ExportWorker
from .ffmpeg_dialog import FFmpegDialog
from .ffmpeg_tools import available_encoders, ffmpeg_version, resolve_ffmpeg
from .settings import AppSettings
from .utils import APP_TITLE, VIDEO_EXTS, format_time, video_file_filter
from .video_canvas import VideoCanvas
from .video_info import VideoInfo, probe
from .widgets import IconLabel, JumpSlider

PLAYING = QMediaPlayer.PlaybackState.PlayingState
END_TOLERANCE_MS = 50
PLAYER_WARMUP_MS = 100
HARDWARE_CHECK_DELAY_MS = 800
WORKER_STOP_TIMEOUT_MS = 15000
STATUS_MESSAGE_MS = 8000
TIME_TEMPLATE = "00:00.00 / 00:00.00"
CROP_PRESETS = tuple(
    sorted(((1, 1), (9, 16), (4, 5), (3, 4), (4, 3), (16, 9)), key=lambda ratio: ratio[0] / ratio[1])
)
CUSTOM_RATIO_MAX = 100


class MainWindow(QMainWindow):
    def __init__(self, initial_path: str | None = None):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(820, 560)
        self.resize(1100, 720)
        self.setAcceptDrops(True)

        self._settings = AppSettings()
        self._info: VideoInfo | None = None
        self._position = 0
        self._duration = 0
        self._at_end = False
        self._worker: ExportWorker | None = None
        self._player: QMediaPlayer | None = None
        self._audio: QAudioOutput | None = None
        self._sink: QVideoSink | None = None

        self._build_ui()
        self._build_menu()
        self._build_corner()
        self._build_shortcuts()
        self._set_loaded(False)

        QTimer.singleShot(PLAYER_WARMUP_MS, self._create_player)
        QTimer.singleShot(HARDWARE_CHECK_DELAY_MS, self._start_hardware_check)
        if initial_path:
            self.load_video(initial_path)

    @property
    def player(self) -> QMediaPlayer:
        self._create_player()
        return self._player

    def _create_player(self) -> None:
        if self._player is not None:
            return
        self._sink = QVideoSink(self)
        self._player = QMediaPlayer(self)
        if not QMediaDevices.defaultAudioOutput().isNull():
            self._audio = QAudioOutput(self)
            self._audio.setVolume(self._volume_slider.value() / 100)
            self._audio.setMuted(self._mute_button.isChecked())
            self._player.setAudioOutput(self._audio)
        else:
            self._mute_button.setEnabled(False)
            self._volume_slider.setEnabled(False)
            self._mute_button.setToolTip("No audio device detected")
        self._player.setVideoSink(self._sink)

        self._sink.videoFrameChanged.connect(self._canvas.set_frame)
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_player_error)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 4)

        self._canvas = VideoCanvas()
        layout.addWidget(self._canvas, 1)

        self._slider = JumpSlider()
        self._slider.sliderMoved.connect(self._seek)
        self._slider.jumped.connect(self._seek)
        layout.addWidget(self._slider)

        bar = QHBoxLayout()
        self._prev_button = self._tool_button("chevron-left", "Previous frame (Left)")
        self._play_button = self._tool_button("play", "Play / Pause (Space)", size=24)
        self._next_button = self._tool_button("chevron-right", "Next frame (Right)")
        self._prev_button.clicked.connect(lambda: self._step(-1))
        self._next_button.clicked.connect(lambda: self._step(1))
        self._play_button.clicked.connect(self._toggle_play)
        bar.addWidget(self._prev_button)
        bar.addWidget(self._play_button)
        bar.addWidget(self._next_button)
        bar.addSpacing(12)

        self._time_label = QLabel(TIME_TEMPLATE)
        self._time_label.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self._time_label.setMinimumWidth(
            self._time_label.fontMetrics().horizontalAdvance(TIME_TEMPLATE)
        )
        bar.addWidget(self._time_label)
        bar.addStretch(1)

        self._mute_button = self._tool_button("volume-2", "Mute")
        self._mute_button.setCheckable(True)
        self._mute_button.setFixedSize(24, 24)
        self._mute_button.toggled.connect(self._on_mute)
        self._volume_slider = JumpSlider()
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(self._settings.volume)
        self._volume_slider.setFixedWidth(100)
        self._volume_slider.valueChanged.connect(self._on_volume)
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setFixedWidth(180)
        self._progress.setTextVisible(True)
        bar.addWidget(self._mute_button)
        bar.addWidget(self._volume_slider)
        bar.addSpacing(10)
        bar.addWidget(self._progress)
        layout.addLayout(bar)
        self._keep_space_when_hidden(self._progress)
        self._progress.setVisible(False)

        status_bar = self.statusBar()
        status_bar.messageChanged.connect(lambda message: status_bar.setVisible(bool(message)))
        status_bar.hide()

    def _build_menu(self) -> None:
        self._toolbar = QToolBar("Main")
        self._toolbar.setMovable(False)
        self._toolbar.setFloatable(False)
        self._toolbar.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self._toolbar.setIconSize(QSize(18, 18))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._toolbar)

        file_menu = QMenu(self)
        self._open_action = QAction(icons.icon("folder-open"), "Open video...", self)
        self._open_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Open))
        self._open_action.triggered.connect(self.open_dialog)
        self._export_action = QAction(icons.icon("download"), "Export video...", self)
        self._export_action.setShortcut(QKeySequence("Ctrl+E"))
        self._export_action.triggered.connect(self.export_video)
        quit_action = QAction(icons.icon("log-out"), "Quit", self)
        quit_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Quit))
        quit_action.triggered.connect(self.close)
        file_menu.addAction(self._open_action)
        file_menu.addAction(self._export_action)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)
        self._menu_button("&File", "file", file_menu)
        self.addActions([self._open_action, self._export_action, quit_action])

        blur_menu = QMenu(self)
        self._blur_button = self._menu_button("&Blur", "blend", blur_menu)
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(14, 10, 14, 10)
        panel_layout.setSpacing(8)
        form = QFormLayout()
        self._strength_slider, strength_label = self._labeled_slider(1, 100, 25)
        self._feather_slider, feather_label = self._labeled_slider(0, 50, 8)
        for slider in (self._strength_slider, self._feather_slider):
            slider.setMinimumWidth(170)
        form.addRow(
            IconLabel("droplet", "Strength"), self._row(self._strength_slider, strength_label)
        )
        form.addRow(
            IconLabel("scan", "Edge softness"), self._row(self._feather_slider, feather_label)
        )
        panel_layout.addLayout(form)
        self._preview_check = QCheckBox("Live preview")
        self._preview_check.setIcon(icons.icon("eye"))
        self._preview_check.setChecked(True)
        panel_layout.addWidget(self._preview_check)
        panel_action = QWidgetAction(self)
        panel_action.setDefaultWidget(panel)
        blur_menu.addAction(panel_action)
        for slider in (self._strength_slider, self._feather_slider):
            slider.valueChanged.connect(self._push_blur_settings)
        self._preview_check.toggled.connect(self._push_blur_settings)

        self._add_button = QToolButton()
        self._add_button.setText("&Add")
        self._add_button.setIcon(icons.icon("plus", 18))
        self._add_button.setIconSize(QSize(18, 18))
        self._add_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._add_button.setToolTip("Add a watermark area")
        self._add_button.setAutoRaise(True)
        self._add_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._add_button.clicked.connect(lambda: self._canvas.add_area())
        self._toolbar.addWidget(self._add_button)

        self._build_crop_menu()

        settings_menu = QMenu(self)
        self._settings_button = self._menu_button(
            "&Settings", "sliders-horizontal", settings_menu
        )
        ffmpeg_action = QAction(icons.icon("terminal"), "FFmpeg...", self)
        ffmpeg_action.triggered.connect(self.open_ffmpeg_settings)
        settings_menu.addAction(ffmpeg_action)
        export_action = QAction(icons.icon("film"), "Export settings...", self)
        export_action.triggered.connect(self.open_export_settings)
        settings_menu.addAction(export_action)

    def _build_crop_menu(self) -> None:
        crop_menu = QMenu(self)
        self._crop_button = self._menu_button("&Crop", "crop", crop_menu)
        self._crop_group = QActionGroup(self)
        self._crop_group.setExclusive(True)
        self._crop_choices: dict[QAction, tuple[bool, float | None]] = {}
        self._custom_ratio = (5, 7)

        def add(text: str, enabled: bool, ratio: float | None) -> QAction:
            action = QAction(text, self)
            action.setCheckable(True)
            self._crop_group.addAction(action)
            crop_menu.addAction(action)
            self._crop_choices[action] = (enabled, ratio)
            return action

        self._crop_off_action = add("No crop", False, None)
        self._crop_off_action.setChecked(True)
        self._crop_current = self._crop_off_action
        add("Free", True, None)
        crop_menu.addSeparator()
        for width, height in CROP_PRESETS:
            add(f"{width}:{height}", True, width / height)
        crop_menu.addSeparator()
        self._crop_custom_action = add("Custom ratio...", True, None)
        self._crop_group.triggered.connect(self._on_crop_action)

    def _on_crop_action(self, action: QAction) -> None:
        if action is self._crop_custom_action:
            ratio = self._ask_custom_ratio()
            if ratio is None:
                self._crop_current.setChecked(True)
                return
            width, height = ratio
            self._custom_ratio = ratio
            action.setText(f"Custom ({width}:{height})...")
            self._crop_choices[action] = (True, width / height)
        self._apply_crop_choice(action)

    def _apply_crop_choice(self, action: QAction) -> None:
        enabled, ratio = self._crop_choices[action]
        self._crop_current = action
        self._canvas.set_crop(enabled, ratio)

    def _ask_custom_ratio(self) -> tuple[int, int] | None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Custom crop ratio")
        layout = QVBoxLayout(dialog)
        row = QHBoxLayout()
        boxes = []
        for index, value in enumerate(self._custom_ratio):
            box = QSpinBox()
            box.setRange(1, CUSTOM_RATIO_MAX)
            box.setValue(value)
            boxes.append(box)
            row.addWidget(box)
            if index == 0:
                row.addWidget(QLabel(":"))
        layout.addLayout(row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        result = (boxes[0].value(), boxes[1].value()) if accepted else None
        dialog.deleteLater()
        return result

    def _build_corner(self) -> None:
        self._corner = QWidget()
        layout = QHBoxLayout(self._corner)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(2)

        self._cancel_button = self._tool_button("x", "Cancel export")
        self._cancel_button.clicked.connect(self._cancel_export)
        self._export_button = self._tool_button("download", "Export video (Ctrl+E)")
        self._export_button.clicked.connect(self.export_video)
        for button in (self._cancel_button, self._export_button):
            button.setFixedSize(28, 28)
            layout.addWidget(button)
        self._keep_space_when_hidden(self._cancel_button)
        self._cancel_button.setVisible(False)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._toolbar.addWidget(spacer)
        self._toolbar.addWidget(self._corner)

    def _build_shortcuts(self) -> None:
        QShortcut(QKeySequence("Space"), self, activated=self._toggle_play)
        QShortcut(QKeySequence("Left"), self, activated=lambda: self._step(-1))
        QShortcut(QKeySequence("Right"), self, activated=lambda: self._step(1))

    @staticmethod
    def _keep_space_when_hidden(widget: QWidget) -> None:
        policy = widget.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        widget.setSizePolicy(policy)

    def _menu_button(self, text: str, icon_name: str, menu: QMenu) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setIcon(icons.icon(icon_name, 18))
        button.setIconSize(QSize(18, 18))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setMenu(menu)
        button.setStyleSheet("QToolButton::menu-indicator { image: none; }")
        self._toolbar.addWidget(button)
        return button

    @staticmethod
    def _tool_button(icon_name: str, tooltip: str, size: int = 20) -> QToolButton:
        button = QToolButton()
        button.setIcon(icons.icon(icon_name, size))
        button.setIconSize(QSize(size, size))
        button.setToolTip(tooltip)
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return button

    @staticmethod
    def _labeled_slider(minimum: int, maximum: int, value: int) -> tuple[JumpSlider, QLabel]:
        slider = JumpSlider()
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        label = QLabel(str(value))
        label.setMinimumWidth(24)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        slider.valueChanged.connect(lambda current: label.setText(str(current)))
        return slider, label

    @staticmethod
    def _row(*widgets: QWidget) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        for widget in widgets:
            layout.addWidget(widget)
        return container

    def _set_loaded(self, loaded: bool) -> None:
        for widget in (
            self._slider, self._prev_button, self._play_button, self._next_button,
            self._export_button, self._export_action, self._add_button,
            self._crop_button,
        ):
            widget.setEnabled(loaded)

    def _set_busy(self, busy: bool) -> None:
        loaded = self._info is not None
        self._canvas.setEnabled(not busy)
        for widget in (self._slider, self._prev_button, self._play_button, self._next_button):
            widget.setEnabled(not busy and loaded)
        self._blur_button.setEnabled(not busy)
        self._add_button.setEnabled(not busy and loaded)
        self._crop_button.setEnabled(not busy and loaded)
        self._settings_button.setEnabled(not busy)
        self._open_action.setEnabled(not busy)
        self._export_action.setEnabled(not busy and loaded)
        self._export_button.setEnabled(not busy and loaded)
        self._cancel_button.setVisible(busy)
        self._progress.setVisible(busy)

    def open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open video", self._settings.last_dir, video_file_filter()
        )
        if path:
            self.load_video(path)

    def load_video(self, path: str) -> None:
        try:
            info = probe(path)
        except Exception as error:
            QMessageBox.critical(self, "Error", str(error))
            return

        player = self.player
        player.stop()
        self._settings.last_dir = str(Path(path).parent)
        self._info = info
        self._at_end = False
        self._position = 0

        self._canvas.set_video(info.width, info.height)
        self._push_blur_settings()
        self.setWindowTitle(f"{os.path.basename(path)} - {APP_TITLE}")
        self._progress.setValue(0)

        self._on_duration(info.duration_ms)
        self._slider.setValue(0)
        self._set_loaded(True)

        player.setSource(QUrl.fromLocalFile(path))
        player.pause()
        self._update_time()
        self.statusBar().showMessage(
            "Click Add to mark a watermark area, or use Crop to pick a frame ratio.",
            STATUS_MESSAGE_MS,
        )

    @staticmethod
    def _video_from_mime(mime) -> str | None:
        if not mime.hasUrls():
            return None
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if os.path.isfile(path) and Path(path).suffix.lower() in VIDEO_EXTS:
                return path
        return None

    def dragEnterEvent(self, event) -> None:
        if self._worker is None and self._video_from_mime(event.mimeData()):
            event.acceptProposedAction()
            self._canvas.set_drag_over(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._canvas.set_drag_over(False)

    def dropEvent(self, event) -> None:
        self._canvas.set_drag_over(False)
        path = self._video_from_mime(event.mimeData())
        if path and self._worker is None:
            event.acceptProposedAction()
            self.load_video(path)

    def _toggle_play(self) -> None:
        if self._info is None or self._worker is not None:
            return
        player = self.player
        if player.playbackState() == PLAYING:
            player.pause()
            return
        if self._at_end or self._position >= self._duration - END_TOLERANCE_MS:
            player.setPosition(0)
        self._at_end = False
        player.play()

    def _seek(self, milliseconds: int) -> None:
        self._at_end = False
        self._position = int(milliseconds)
        self.player.setPosition(self._position)
        self._update_time()

    def _step(self, direction: int) -> None:
        if self._info is None or self._worker is not None:
            return
        self.player.pause()
        frame_ms = 1000.0 / self._info.fps
        index = round(self._position / frame_ms) + direction
        target = index * frame_ms + frame_ms / 4
        self._seek(int(max(0, min(self._duration, target))))

    def _on_position(self, milliseconds: int) -> None:
        self._position = milliseconds
        if not self._slider.isSliderDown():
            self._slider.blockSignals(True)
            self._slider.setValue(milliseconds)
            self._slider.blockSignals(False)
        self._update_time()

    def _on_duration(self, milliseconds: int) -> None:
        if milliseconds <= 0:
            return
        self._duration = milliseconds
        self._slider.setRange(0, milliseconds)

    def _on_state(self, state) -> None:
        playing = state == PLAYING
        self._canvas.set_playing(playing)
        self._play_button.setIcon(icons.icon("pause" if playing else "play", 24))

    def _on_media_status(self, status) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._at_end = True

    def _on_player_error(self, _error, message: str) -> None:
        self.statusBar().showMessage(
            f"Preview failed: {message} (export can still work through ffmpeg)",
            STATUS_MESSAGE_MS,
        )

    def _update_time(self) -> None:
        self._time_label.setText(
            f"{format_time(self._position / 1000)} / {format_time(self._duration / 1000)}"
        )

    def _on_volume(self, value: int) -> None:
        if self._audio is not None:
            self._audio.setVolume(value / 100)
        self._settings.volume = value
        if value > 0 and self._mute_button.isChecked():
            self._mute_button.setChecked(False)

    def _on_mute(self, muted: bool) -> None:
        if self._audio is not None:
            self._audio.setMuted(muted)
        self._mute_button.setIcon(icons.icon("volume-x" if muted else "volume-2"))

    def _push_blur_settings(self, *_) -> None:
        self._canvas.set_blur(
            self._preview_check.isChecked(),
            self._strength_slider.value(),
            self._feather_slider.value(),
        )

    def open_ffmpeg_settings(self) -> None:
        dialog = FFmpegDialog(self._settings, self)
        dialog.exec()
        dialog.deleteLater()
        self._start_hardware_check()

    def _start_hardware_check(self) -> None:
        path = resolve_ffmpeg(self._settings.ffmpeg_path)
        if path:
            hardware.ensure_probe(path)

    def open_export_settings(self) -> None:
        size = None
        if self._info is not None:
            crop = self._canvas.crop_rect()
            size = (crop.width(), crop.height()) if crop else (self._info.width, self._info.height)
        dialog = ExportSettingsDialog(self._settings, self, size)
        dialog.exec()
        dialog.deleteLater()

    def export_video(self) -> None:
        if self._info is None or self._worker is not None:
            return
        if not self._canvas.has_areas() and self._canvas.crop_rect() is None:
            QMessageBox.information(
                self,
                "Nothing to export",
                "Click Add to mark a watermark area, or pick a ratio in Crop, first.",
            )
            return
        ffmpeg = self._usable_ffmpeg()
        if ffmpeg is None:
            return
        options = self._settings.export_options()
        if not self._encoders_ready(ffmpeg, options):
            return
        destination = self._ask_destination(options)
        if destination is None:
            return
        self._start_export(ffmpeg, destination, options)

    def _usable_ffmpeg(self) -> str | None:
        ffmpeg = resolve_ffmpeg(self._settings.ffmpeg_path)
        if ffmpeg and ffmpeg_version(ffmpeg):
            return ffmpeg
        QMessageBox.warning(
            self,
            "FFmpeg not ready",
            "ffmpeg was not found or is not valid.\nSet its location in Settings > FFmpeg.",
        )
        self.open_ffmpeg_settings()
        return None

    def _encoders_ready(self, ffmpeg: str, options: ExportOptions) -> bool:
        available = available_encoders(ffmpeg)
        if available is not None:
            missing = [name for name in options.required_encoders() if name not in available]
            if missing:
                QMessageBox.warning(
                    self,
                    "Encoder not available",
                    f"Your ffmpeg doesn't include: {', '.join(missing)}.\n"
                    "Pick another codec or container in Settings > Export settings.",
                )
                self.open_export_settings()
                return False
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            works, reason = hardware.check(ffmpeg, options.codec, available)
        finally:
            QGuiApplication.restoreOverrideCursor()
        if works:
            return True
        QMessageBox.warning(
            self,
            "Codec not supported",
            f"{options.codec_info.label} can't be used on this computer.\n{reason}\n"
            "Pick another codec in Settings > Export settings.",
        )
        self.open_export_settings()
        return False

    def _ask_destination(self, options: ExportOptions) -> str | None:
        source = self._info.path
        container = options.container_info
        suggestion = f"{os.path.splitext(source)[0]}_blumark{container.ext}"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save result",
            suggestion,
            f"{container.key.upper()} (*{container.ext})",
        )
        if not path:
            return None
        extension_added = not path.lower().endswith(container.ext)
        if extension_added:
            path += container.ext
        if self._is_same_file(path, source):
            QMessageBox.warning(
                self, "Warning", "The output file must not be the same as the source file."
            )
            return None
        if extension_added and os.path.exists(path) and not self._confirm_replace(path):
            return None
        return path

    @staticmethod
    def _is_same_file(first: str, second: str) -> bool:
        if os.path.exists(first) and os.path.exists(second):
            return os.path.samefile(first, second)
        return os.path.abspath(first) == os.path.abspath(second)

    def _confirm_replace(self, path: str) -> bool:
        answer = QMessageBox.question(
            self,
            "Replace file?",
            f"{os.path.basename(path)} already exists.\nReplace it?",
        )
        return answer == QMessageBox.StandardButton.Yes

    def _start_export(self, ffmpeg: str, destination: str, options: ExportOptions) -> None:
        self.player.pause()
        rects = [(r.x(), r.y(), r.width(), r.height()) for r in self._canvas.rois()]
        crop = self._canvas.crop_rect()
        crop_rect = (crop.x(), crop.y(), crop.width(), crop.height()) if crop else None
        self._progress.setValue(0)
        self._set_busy(True)

        worker = ExportWorker(
            ffmpeg,
            self._info.path,
            destination,
            rects,
            self._strength_slider.value(),
            self._feather_slider.value(),
            options,
            crop_rect,
            self,
        )
        worker.progress.connect(self._progress.setValue)
        worker.done.connect(self._on_export_done)
        worker.failed.connect(self._on_export_failed)
        worker.cancelled.connect(self._on_export_cancelled)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        worker.start()

    def _cancel_export(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def _on_worker_finished(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        self._set_busy(False)

    def _on_export_done(self, path: str) -> None:
        self._progress.setValue(100)
        QMessageBox.information(self, "Done", f"Video saved to:\n{path}")

    def _on_export_failed(self, message: str) -> None:
        self._progress.setValue(0)
        QMessageBox.critical(self, "Export failed", message or "Export failed.")

    def _on_export_cancelled(self) -> None:
        self._progress.setValue(0)

    def closeEvent(self, event) -> None:
        if self._player is not None:
            self._player.stop()
        hardware.shutdown()
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(WORKER_STOP_TIMEOUT_MS)
        super().closeEvent(event)
