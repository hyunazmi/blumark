from __future__ import annotations

import importlib
import os
import sys
import threading

from PySide6.QtCore import qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QMessageBox

from . import icons
from .main_window import MainWindow
from .utils import APP_NAME

QUIET_ENVIRONMENT = {
    "QT_LOGGING_RULES": "*=false",
    "QT_FFMPEG_DEBUG": "0",
    "OPENCV_LOG_LEVEL": "SILENT",
    "OPENCV_FFMPEG_LOGLEVEL": "-8",
    "OPENCV_VIDEOIO_DEBUG": "0",
    "AV_LOG_FORCE_NOCOLOR": "1",
}
DEBUG_VARIABLE = "BLUMARK_DEBUG"
WINDOWS_APP_ID = "Blumark.Blumark"


def configure_environment() -> None:
    for name, value in QUIET_ENVIRONMENT.items():
        os.environ.setdefault(name, value)


def silence_output() -> None:
    for name in ("stdout", "stderr"):
        try:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
        except OSError:
            pass
    try:
        descriptor = os.open(os.devnull, os.O_WRONLY)
        os.dup2(descriptor, 1)
        os.dup2(descriptor, 2)
        os.close(descriptor)
    except OSError:
        pass


def show_unexpected_error(exc_type, exc, _traceback) -> None:
    try:
        QMessageBox.critical(None, "Unexpected error", f"{exc_type.__name__}: {exc}")
    except Exception:
        pass


def set_windows_app_id() -> None:
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
    except (AttributeError, OSError):
        pass


def preload_vision() -> None:
    threading.Thread(target=importlib.import_module, args=("cv2",), daemon=True).start()


def main() -> int:
    configure_environment()
    debug = bool(os.environ.get(DEBUG_VARIABLE))
    if not debug:
        silence_output()
    if sys.platform == "win32":
        set_windows_app_id()

    app = QApplication(sys.argv)
    app.setOrganizationName(APP_NAME)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(icons.app_icon())
    if not debug:
        qInstallMessageHandler(lambda _mode, _context, _message: None)
        sys.excepthook = show_unexpected_error

    initial = next((arg for arg in sys.argv[1:] if os.path.isfile(arg)), None)
    window = MainWindow(initial)
    window.show()
    preload_vision()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
