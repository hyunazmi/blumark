from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

RES_DIR = Path(__file__).parent / "resources"
ICON_DIR = RES_DIR / "icons"
LOGO_SVG = RES_DIR / "logo.svg"
LOGO_SIZES = (16, 24, 32, 48, 64, 128, 256)


@lru_cache(maxsize=None)
def _svg(name: str) -> str:
    return (ICON_DIR / f"{name}.svg").read_text(encoding="utf-8")


def _render(name: str, color: str, size: int) -> QPixmap:
    screen = QApplication.primaryScreen()
    ratio = screen.devicePixelRatio() if screen else 1.0
    renderer = QSvgRenderer(QByteArray(_svg(name).replace("currentColor", color).encode("utf-8")))
    pixmap = QPixmap(round(size * ratio), round(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap


def pixmap(name: str, size: int = 20, color: str | None = None) -> QPixmap:
    if color is None:
        palette = QApplication.palette()
        color = palette.color(QPalette.ColorGroup.Normal, QPalette.ColorRole.WindowText).name()
    return _render(name, color, size)


def icon(name: str, size: int = 20, color: str | None = None) -> QIcon:
    palette = QApplication.palette()
    role = QPalette.ColorRole.ButtonText
    normal = color or palette.color(QPalette.ColorGroup.Normal, role).name()
    disabled = palette.color(QPalette.ColorGroup.Disabled, role).name()
    result = QIcon()
    result.addPixmap(_render(name, normal, size), QIcon.Mode.Normal)
    result.addPixmap(_render(name, disabled, size), QIcon.Mode.Disabled)
    return result


def app_icon() -> QIcon:
    result = QIcon()
    renderer = QSvgRenderer(str(LOGO_SVG))
    for size in LOGO_SIZES:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        result.addPixmap(pixmap)
    return result
