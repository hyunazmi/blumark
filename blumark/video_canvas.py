from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPen
from PySide6.QtMultimedia import QVideoFrame
from PySide6.QtWidgets import QWidget

from . import icons

HANDLE = 6
MIN_SIZE = 4
CONFIRM_SIZE = 28
ACCENT = QColor(0, 200, 255)
GREEN = QColor(46, 157, 91)
BACKGROUND = QColor(20, 20, 22)

CURSORS = {
    "tl": Qt.CursorShape.SizeFDiagCursor,
    "br": Qt.CursorShape.SizeFDiagCursor,
    "tr": Qt.CursorShape.SizeBDiagCursor,
    "bl": Qt.CursorShape.SizeBDiagCursor,
    "t": Qt.CursorShape.SizeVerCursor,
    "b": Qt.CursorShape.SizeVerCursor,
    "l": Qt.CursorShape.SizeHorCursor,
    "r": Qt.CursorShape.SizeHorCursor,
    "move": Qt.CursorShape.SizeAllCursor,
    "create": Qt.CursorShape.CrossCursor,
    "confirm": Qt.CursorShape.PointingHandCursor,
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class VideoCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(480, 270)

        self._video_width = 0
        self._video_height = 0
        self._frame: QVideoFrame | None = None
        self._base: QImage | None = None
        self._dirty = False
        self._playing = False
        self._drag_over = False

        self._blur_on = True
        self._strength = 25
        self._feather = 8

        self._area_visible = True
        self._roi = QRectF()
        self._mode: str | None = None
        self._press_point = QPointF()
        self._press_roi = QRectF()

    def set_video(self, width: int, height: int) -> None:
        self._video_width, self._video_height = width, height
        self._frame = self._base = None
        self._dirty = False
        self._mode = None
        self._area_visible = True
        roi_width, roi_height = max(8, int(width * 0.2)), max(8, int(height * 0.08))
        x = max(0, width - roi_width - int(width * 0.03))
        y = max(0, height - roi_height - int(height * 0.03))
        self._roi = QRectF(x, y, roi_width, roi_height)
        self.update()

    def set_frame(self, frame: QVideoFrame) -> None:
        if not frame.isValid():
            return
        self._frame = frame
        self._dirty = True
        self.update()

    def set_blur(self, enabled: bool, strength: int, feather: int) -> None:
        self._blur_on, self._strength, self._feather = enabled, strength, feather
        self.update()

    def set_playing(self, playing: bool) -> None:
        self._playing = playing

    def set_drag_over(self, active: bool) -> None:
        self._drag_over = active
        self.update()

    def set_area_visible(self, visible: bool) -> None:
        self._area_visible = visible
        self._mode = None
        self.unsetCursor()
        self.setToolTip("")
        self.update()

    def roi(self) -> QRect:
        roi = self._roi
        return QRect(round(roi.x()), round(roi.y()), round(roi.width()), round(roi.height()))

    def _transform(self) -> tuple[float, float, float]:
        scale = min(self.width() / self._video_width, self.height() / self._video_height)
        offset_x = (self.width() - self._video_width * scale) / 2
        offset_y = (self.height() - self._video_height * scale) / 2
        return scale, offset_x, offset_y

    def _to_widget(self, point: QPointF) -> QPointF:
        scale, offset_x, offset_y = self._transform()
        return QPointF(point.x() * scale + offset_x, point.y() * scale + offset_y)

    def _to_video(self, point: QPointF) -> QPointF:
        scale, offset_x, offset_y = self._transform()
        return QPointF((point.x() - offset_x) / scale, (point.y() - offset_y) / scale)

    def _roi_widget_rect(self) -> QRectF:
        return QRectF(
            self._to_widget(self._roi.topLeft()), self._to_widget(self._roi.bottomRight())
        )

    @staticmethod
    def _handle_points(rect: QRectF) -> dict[str, QPointF]:
        center = rect.center()
        return {
            "tl": rect.topLeft(),
            "t": QPointF(center.x(), rect.top()),
            "tr": rect.topRight(),
            "r": QPointF(rect.right(), center.y()),
            "br": rect.bottomRight(),
            "b": QPointF(center.x(), rect.bottom()),
            "bl": rect.bottomLeft(),
            "l": QPointF(rect.left(), center.y()),
        }

    def _confirm_rect(self) -> QRectF:
        rect = self._roi_widget_rect()
        size, gap = CONFIRM_SIZE, HANDLE + 6
        bounds = QRectF(self.rect())
        candidates = (
            QRectF(rect.right() + gap, rect.top() - size - gap, size, size),
            QRectF(rect.right() - size, rect.top() - size - gap, size, size),
            QRectF(rect.right() + gap, rect.top(), size, size),
            QRectF(rect.right() - size, rect.bottom() + gap, size, size),
        )
        for candidate in candidates:
            if bounds.contains(candidate):
                return candidate
        first = candidates[0]
        return QRectF(
            _clamp(first.x(), 0, max(0, self.width() - size)),
            _clamp(first.y(), 0, max(0, self.height() - size)),
            size,
            size,
        )

    def _hit(self, position: QPointF) -> str | None:
        if self._video_width == 0 or not self._area_visible:
            return None
        rect = self._roi_widget_rect()
        reach = HANDLE + 3
        for name, point in self._handle_points(rect).items():
            if abs(position.x() - point.x()) <= reach and abs(position.y() - point.y()) <= reach:
                return name
        if self._confirm_rect().contains(position):
            return "confirm"
        if rect.contains(position):
            return "move"
        scale, offset_x, offset_y = self._transform()
        frame_rect = QRectF(
            offset_x, offset_y, self._video_width * scale, self._video_height * scale
        )
        return "create" if frame_rect.contains(position) else None

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), BACKGROUND)

        if self._video_width == 0:
            self._paint_placeholder(painter)
        else:
            scale, offset_x, offset_y = self._transform()
            target = QRectF(
                offset_x, offset_y, self._video_width * scale, self._video_height * scale
            )
            if self._dirty:
                self._refresh_base()
            if self._base is not None:
                painter.setRenderHint(
                    QPainter.RenderHint.SmoothPixmapTransform, not self._playing
                )
                painter.drawImage(target, self._base)
                self._paint_blur(painter, scale, offset_x, offset_y)
            else:
                painter.fillRect(target, QColor(0, 0, 0))
            if self._area_visible:
                self._paint_roi(painter)

        if self._drag_over:
            self._paint_drop_hint(painter)
        painter.end()

    def _paint_placeholder(self, painter: QPainter) -> None:
        pixmap = icons.pixmap("film", 64, "#6b6f76")
        center_x, center_y = self.width() / 2, self.height() / 2
        painter.drawPixmap(int(center_x - 32), int(center_y - 70), pixmap)
        painter.setPen(QColor(160, 164, 170))
        painter.drawText(
            QRectF(0, center_y + 10, self.width(), 24),
            Qt.AlignmentFlag.AlignHCenter,
            "Drag & drop a video here",
        )
        painter.setPen(QColor(110, 114, 120))
        painter.drawText(
            QRectF(0, center_y + 34, self.width(), 24),
            Qt.AlignmentFlag.AlignHCenter,
            "or press Ctrl+O",
        )

    def _paint_drop_hint(self, painter: QPainter) -> None:
        painter.setPen(QPen(ACCENT, 3, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(0, 200, 255, 30))
        painter.drawRect(self.rect().adjusted(6, 6, -6, -6))
        painter.setPen(Qt.GlobalColor.white)
        font = painter.font()
        font.setPointSize(font.pointSize() + 3)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Release to open the video")

    def _refresh_base(self) -> None:
        image = self._frame.toImage() if self._frame is not None else QImage()
        self._base = None if image.isNull() else image.convertToFormat(QImage.Format.Format_RGB32)
        self._dirty = False

    def _paint_blur(
        self, painter: QPainter, scale: float, offset_x: float, offset_y: float
    ) -> None:
        if not self._blur_on or self._roi.isNull():
            return
        import numpy as np

        from .blur import blur_patch

        image = self._base
        image_width, image_height = image.width(), image.height()
        ratio_x, ratio_y = image_width / self._video_width, image_height / self._video_height
        roi = self._roi
        rect = (
            int(roi.x() * ratio_x),
            int(roi.y() * ratio_y),
            int(roi.width() * ratio_x),
            int(roi.height() * ratio_y),
        )

        pixels = np.frombuffer(image.constBits(), dtype=np.uint8)
        pixels = pixels.reshape(image_height, image.bytesPerLine() // 4, 4)[:, :image_width]

        result = blur_patch(pixels, rect, self._strength, self._feather)
        if result is None:
            return
        patch, patch_x, patch_y = result
        patch = np.ascontiguousarray(patch)
        patch_height, patch_width = patch.shape[:2]
        patch_image = QImage(
            patch.data, patch_width, patch_height, patch_width * 4, QImage.Format.Format_RGB32
        )
        target = QRectF(
            offset_x + patch_x / ratio_x * scale,
            offset_y + patch_y / ratio_y * scale,
            patch_width / ratio_x * scale,
            patch_height / ratio_y * scale,
        )
        painter.drawImage(target, patch_image)

    def _paint_roi(self, painter: QPainter) -> None:
        rect = self._roi_widget_rect()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(ACCENT, 2, Qt.PenStyle.DashLine))
        painter.drawRect(rect)
        painter.setPen(QPen(Qt.GlobalColor.white, 1))
        painter.setBrush(ACCENT)
        for point in self._handle_points(rect).values():
            painter.drawRect(QRectF(point.x() - HANDLE, point.y() - HANDLE, HANDLE * 2, HANDLE * 2))

        button = self._confirm_rect()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(Qt.GlobalColor.white, 1.5))
        painter.setBrush(GREEN)
        painter.drawEllipse(button)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        icon_size = int(button.width() * 0.6)
        inset = (button.width() - icon_size) / 2
        painter.drawPixmap(
            QPointF(button.x() + inset, button.y() + inset),
            icons.pixmap("check", icon_size, "#ffffff"),
        )

    def leaveEvent(self, event) -> None:
        if self._mode is None:
            self.unsetCursor()
            self.setToolTip("")
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._video_width == 0:
            return
        if not self._area_visible:
            if self._roi_widget_rect().contains(event.position()):
                self.set_area_visible(True)
            return
        mode = self._hit(event.position())
        if mode is None:
            return
        self._mode = mode
        self._press_point = self._to_video(event.position())
        self._press_roi = QRectF(self._roi)
        if mode == "create":
            self._roi = QRectF(self._press_point, self._press_point)

    def mouseMoveEvent(self, event) -> None:
        if self._video_width == 0:
            return
        if not self._area_visible:
            inside = self._roi_widget_rect().contains(event.position())
            if inside:
                self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            else:
                self.unsetCursor()
            self.setToolTip("Click to edit the area" if inside else "")
            return
        dragging = bool(event.buttons() & Qt.MouseButton.LeftButton)
        if not dragging or self._mode is None:
            mode = self._hit(event.position())
            self.setCursor(QCursor(CURSORS.get(mode, Qt.CursorShape.ArrowCursor)))
            self.setToolTip("Confirm area" if mode == "confirm" else "")
            return
        if self._mode == "confirm":
            return
        self._roi = self._dragged_roi(self._to_video(event.position()))
        self.update()

    def _dragged_roi(self, point: QPointF) -> QRectF:
        width, height = self._video_width, self._video_height
        delta_x = point.x() - self._press_point.x()
        delta_y = point.y() - self._press_point.y()
        origin = self._press_roi
        mode = self._mode

        if mode == "move":
            x = _clamp(origin.x() + delta_x, 0, width - origin.width())
            y = _clamp(origin.y() + delta_y, 0, height - origin.height())
            return QRectF(x, y, origin.width(), origin.height())

        if mode == "create":
            end = QPointF(_clamp(point.x(), 0, width), _clamp(point.y(), 0, height))
            start = QPointF(
                _clamp(self._press_point.x(), 0, width), _clamp(self._press_point.y(), 0, height)
            )
            return QRectF(start, end).normalized()

        left, top, right, bottom = origin.left(), origin.top(), origin.right(), origin.bottom()
        if "l" in mode:
            left = _clamp(left + delta_x, 0, right - MIN_SIZE)
        if "r" in mode:
            right = _clamp(right + delta_x, left + MIN_SIZE, width)
        if "t" in mode:
            top = _clamp(top + delta_y, 0, bottom - MIN_SIZE)
        if "b" in mode:
            bottom = _clamp(bottom + delta_y, top + MIN_SIZE, height)
        return QRectF(QPointF(left, top), QPointF(right, bottom))

    def mouseReleaseEvent(self, event) -> None:
        if self._mode == "confirm":
            if self._confirm_rect().contains(event.position()):
                self.set_area_visible(False)
            self._mode = None
            return
        if self._mode == "create" and (
            self._roi.width() < MIN_SIZE or self._roi.height() < MIN_SIZE
        ):
            self._roi = self._press_roi
            self.update()
        self._mode = None
