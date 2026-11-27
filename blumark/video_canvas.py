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
RED = QColor(210, 62, 62)
BUTTON_SPACING = 6
BACKGROUND = QColor(20, 20, 22)
CROP_COLOR = QColor(255, 176, 32)
CROP_DIM = QColor(0, 0, 0, 150)
CROP_MIN = 16
CROP_FIT = 0.9
CROP_WHEEL_STEP = 0.95

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
    "delete": Qt.CursorShape.PointingHandCursor,
    "reveal": Qt.CursorShape.PointingHandCursor,
}

for _key in ("tl", "t", "tr", "r", "br", "b", "bl", "l", "move"):
    CURSORS["crop-" + _key] = CURSORS[_key]

TOOLTIPS = {
    "crop-move": "Drag to move the crop area (scroll to zoom)",
    "confirm": "Confirm area",
    "delete": "Delete area",
    "reveal": "Click to edit the area",
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class _Area:
    """One watermark area. `editing` shows its handles and the confirm/delete buttons."""

    def __init__(self, rect: QRectF, editing: bool = True):
        self.rect = rect
        self.editing = editing


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

        self._areas: list[_Area] = []
        self._active: _Area | None = None
        self._target: _Area | None = None
        self._mode: str | None = None
        self._press_point = QPointF()
        self._press_roi = QRectF()

        self._crop_enabled = False
        self._crop_ratio: float | None = None
        self._crop: QRectF | None = None
        self._crop_mode: str | None = None
        self._press_crop = QRectF()

    def set_video(self, width: int, height: int) -> None:
        self._video_width, self._video_height = width, height
        self._frame = self._base = None
        self._dirty = False
        self._mode = None
        self._target = None
        self._areas = []
        self._active = None
        self._crop_mode = None
        self._crop = self._fit_crop(self._crop_ratio, None) if self._crop_enabled else None
        self.unsetCursor()
        self.setToolTip("")
        self.update()

    def set_crop(self, enabled: bool, ratio: float | None = None) -> None:
        self._crop_enabled = enabled
        self._crop_ratio = ratio if enabled else None
        self._crop_mode = None
        if not enabled or self._video_width == 0:
            self._crop = None
        else:
            self._crop = self._fit_crop(ratio, self._crop)
        self.update()

    def crop_rect(self) -> QRect | None:
        if self._crop is None:
            return None
        width, height = self._video_width, self._video_height
        crop_width = max(2, min(width, round(self._crop.width())) // 2 * 2)
        crop_height = max(2, min(height, round(self._crop.height())) // 2 * 2)
        x = int(_clamp(round(self._crop.x()), 0, width - crop_width))
        y = int(_clamp(round(self._crop.y()), 0, height - crop_height))
        return QRect(x, y, crop_width, crop_height)

    def _clamp_crop(self, rect: QRectF) -> QRectF:
        width, height = self._video_width, self._video_height
        crop_width = _clamp(rect.width(), 1, width)
        crop_height = _clamp(rect.height(), 1, height)
        x = _clamp(rect.x(), 0, width - crop_width)
        y = _clamp(rect.y(), 0, height - crop_height)
        return QRectF(x, y, crop_width, crop_height)

    def _fit_crop(self, ratio: float | None, previous: QRectF | None) -> QRectF:
        width, height = self._video_width, self._video_height
        if ratio is None:
            if previous is not None:
                return QRectF(previous)
            return QRectF(
                width * (1 - CROP_FIT) / 2,
                height * (1 - CROP_FIT) / 2,
                width * CROP_FIT,
                height * CROP_FIT,
            )
        crop_width = width * CROP_FIT
        crop_height = crop_width / ratio
        if crop_height > height * CROP_FIT:
            crop_height = height * CROP_FIT
            crop_width = crop_height * ratio
        center = previous.center() if previous is not None else QPointF(width / 2, height / 2)
        return self._clamp_crop(
            QRectF(
                center.x() - crop_width / 2,
                center.y() - crop_height / 2,
                crop_width,
                crop_height,
            )
        )

    def _crop_widget_rect(self) -> QRectF:
        return QRectF(
            self._to_widget(self._crop.topLeft()), self._to_widget(self._crop.bottomRight())
        )

    def _hit_crop(self, position: QPointF) -> str | None:
        if self._crop is None:
            return None
        rect = self._crop_widget_rect()
        reach = HANDLE + 3
        for name, point in self._handle_points(rect).items():
            if abs(position.x() - point.x()) <= reach and abs(position.y() - point.y()) <= reach:
                return name
        return "move" if rect.contains(position) else None

    def _crop_dragged(self, point: QPointF) -> QRectF:
        width, height = self._video_width, self._video_height
        delta_x = point.x() - self._press_point.x()
        delta_y = point.y() - self._press_point.y()
        origin = self._press_crop
        mode = self._crop_mode

        if mode == "move":
            x = _clamp(origin.x() + delta_x, 0, width - origin.width())
            y = _clamp(origin.y() + delta_y, 0, height - origin.height())
            return QRectF(x, y, origin.width(), origin.height())

        if self._crop_ratio is None:
            left, top, right, bottom = origin.left(), origin.top(), origin.right(), origin.bottom()
            if "l" in mode:
                left = _clamp(left + delta_x, 0, right - CROP_MIN)
            if "r" in mode:
                right = _clamp(right + delta_x, left + CROP_MIN, width)
            if "t" in mode:
                top = _clamp(top + delta_y, 0, bottom - CROP_MIN)
            if "b" in mode:
                bottom = _clamp(bottom + delta_y, top + CROP_MIN, height)
            return QRectF(QPointF(left, top), QPointF(right, bottom))
        return self._clamp_crop(self._crop_locked(origin, mode, delta_x, delta_y))

    def _crop_locked(self, origin: QRectF, mode: str, delta_x: float, delta_y: float) -> QRectF:
        width, height = self._video_width, self._video_height
        ratio = self._crop_ratio
        min_width = max(CROP_MIN, CROP_MIN * ratio)

        if len(mode) == 2:
            sign_x = -1 if "l" in mode else 1
            sign_y = -1 if "t" in mode else 1
            anchor_x = origin.right() if "l" in mode else origin.left()
            anchor_y = origin.bottom() if "t" in mode else origin.top()
            moving_x = (origin.left() if "l" in mode else origin.right()) + delta_x
            moving_y = (origin.top() if "t" in mode else origin.bottom()) + delta_y
            new_width = max((moving_x - anchor_x) * sign_x, (moving_y - anchor_y) * sign_y * ratio)
            available_x = anchor_x if sign_x < 0 else width - anchor_x
            available_y = anchor_y if sign_y < 0 else height - anchor_y
            new_width = max(min_width, min(new_width, available_x, available_y * ratio))
            new_height = new_width / ratio
            x = anchor_x - new_width if sign_x < 0 else anchor_x
            y = anchor_y - new_height if sign_y < 0 else anchor_y
            return QRectF(x, y, new_width, new_height)

        center = origin.center()
        if mode in ("l", "r"):
            edge_width = (
                origin.width() + delta_x if mode == "r" else origin.width() - delta_x
            )
            available = width - origin.left() if mode == "r" else origin.right()
            limit = min(available, 2 * min(center.y(), height - center.y()) * ratio)
            new_width = _clamp(edge_width, min_width, max(min_width, limit))
            new_height = new_width / ratio
            x = origin.left() if mode == "r" else origin.right() - new_width
            return QRectF(x, center.y() - new_height / 2, new_width, new_height)

        edge_height = origin.height() + delta_y if mode == "b" else origin.height() - delta_y
        available = height - origin.top() if mode == "b" else origin.bottom()
        limit = min(available, 2 * min(center.x(), width - center.x()) / ratio)
        min_height = min_width / ratio
        new_height = _clamp(edge_height, min_height, max(min_height, limit))
        new_width = new_height * ratio
        y = origin.top() if mode == "b" else origin.bottom() - new_height
        return QRectF(center.x() - new_width / 2, y, new_width, new_height)

    def wheelEvent(self, event) -> None:
        if self._crop is None or self._video_width == 0:
            super().wheelEvent(event)
            return
        steps = event.angleDelta().y() / 120
        if steps == 0:
            return
        factor = CROP_WHEEL_STEP**steps
        crop = self._crop
        factor = min(
            factor,
            self._video_width / crop.width(),
            self._video_height / crop.height(),
        )
        factor = max(factor, CROP_MIN / crop.width(), CROP_MIN / crop.height())
        center = crop.center()
        new_width, new_height = crop.width() * factor, crop.height() * factor
        self._crop = self._clamp_crop(
            QRectF(
                center.x() - new_width / 2, center.y() - new_height / 2, new_width, new_height
            )
        )
        event.accept()
        self.update()

    def add_area(self) -> None:
        if self._video_width == 0:
            return
        area = _Area(self._new_rect())
        self._areas.append(area)
        self._active = area
        self.update()

    def _new_rect(self) -> QRectF:
        width, height = self._video_width, self._video_height
        roi_width, roi_height = max(8, int(width * 0.2)), max(8, int(height * 0.08))
        x = max(0, width - roi_width - int(width * 0.03))
        y = max(0, height - roi_height - int(height * 0.03))
        step = roi_height + max(4, int(height * 0.01))
        fallback = QRectF(x, y, roi_width, roi_height)
        while y >= 0:
            candidate = QRectF(x, y, roi_width, roi_height)
            if not any(candidate.intersects(area.rect) for area in self._areas):
                return candidate
            y -= step
        return fallback

    def has_areas(self) -> bool:
        return bool(self._areas)

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

    def rois(self) -> list[QRect]:
        return [
            QRect(
                round(area.rect.x()),
                round(area.rect.y()),
                round(area.rect.width()),
                round(area.rect.height()),
            )
            for area in self._areas
        ]

    def _set_editing(self, area: _Area, editing: bool) -> None:
        area.editing = editing
        if editing:
            self._active = area
        elif self._active is area:
            self._active = next((a for a in reversed(self._areas) if a.editing), None)
        self.update()

    def _delete_area(self, area: _Area) -> None:
        if area in self._areas:
            self._areas.remove(area)
        if self._active is area:
            self._active = next((a for a in reversed(self._areas) if a.editing), None)
        self.unsetCursor()
        self.setToolTip("")
        self.update()

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

    def _widget_rect(self, area: _Area) -> QRectF:
        return QRectF(
            self._to_widget(area.rect.topLeft()), self._to_widget(area.rect.bottomRight())
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

    def _button_rects(self, area: _Area) -> tuple[QRectF, QRectF]:
        rect = self._widget_rect(area)
        size, gap = CONFIRM_SIZE, HANDLE + 6
        group_width = size * 2 + BUTTON_SPACING
        bounds = QRectF(self.rect())
        candidates = (
            (rect.right() + gap, rect.top() - size - gap),
            (rect.right() - group_width, rect.top() - size - gap),
            (rect.left(), rect.top() - size - gap),
            (rect.right() + gap, rect.top()),
            (rect.right() - group_width, rect.bottom() + gap),
            (rect.left(), rect.bottom() + gap),
        )
        x, y = candidates[0]
        for cx, cy in candidates:
            if bounds.contains(QRectF(cx, cy, group_width, size)):
                x, y = cx, cy
                break
        else:
            x = _clamp(x, 0, max(0, self.width() - group_width))
            y = _clamp(y, 0, max(0, self.height() - size))
        confirm = QRectF(x, y, size, size)
        delete = QRectF(x + size + BUTTON_SPACING, y, size, size)
        return confirm, delete

    def _editing_areas(self) -> list[_Area]:
        areas = [area for area in reversed(self._areas) if area.editing]
        if self._active in areas:
            areas.remove(self._active)
            areas.insert(0, self._active)
        return areas

    def _hit(self, position: QPointF) -> tuple[_Area | None, str | None]:
        if self._video_width == 0:
            return None, None
        editing = self._editing_areas()
        for area in editing:
            confirm, delete = self._button_rects(area)
            if confirm.contains(position):
                return area, "confirm"
            if delete.contains(position):
                return area, "delete"
        reach = HANDLE + 3
        for area in editing:
            rect = self._widget_rect(area)
            for name, point in self._handle_points(rect).items():
                if abs(position.x() - point.x()) <= reach and abs(position.y() - point.y()) <= reach:
                    return area, name
        for area in editing:
            if self._widget_rect(area).contains(position):
                return area, "move"
        for area in reversed(self._areas):
            if not area.editing and self._widget_rect(area).contains(position):
                return area, "reveal"
        crop_mode = self._hit_crop(position)
        if crop_mode is not None:
            return None, "crop-" + crop_mode
        scale, offset_x, offset_y = self._transform()
        frame_rect = QRectF(
            offset_x, offset_y, self._video_width * scale, self._video_height * scale
        )
        if self._active is not None and frame_rect.contains(position):
            return self._active, "create"
        return None, None

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
            if self._crop is not None:
                self._paint_crop(painter, target)
            editing = [area for area in self._areas if area.editing]
            for area in editing:
                self._paint_roi(painter, area)
            for area in editing:
                self._paint_buttons(painter, area)

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
        if not self._blur_on or not self._areas:
            return
        import numpy as np

        from .blur import blur_patch

        image = self._base
        image_width, image_height = image.width(), image.height()
        ratio_x, ratio_y = image_width / self._video_width, image_height / self._video_height

        pixels = np.frombuffer(image.constBits(), dtype=np.uint8)
        pixels = pixels.reshape(image_height, image.bytesPerLine() // 4, 4)[:, :image_width]

        for area in self._areas:
            roi = area.rect
            rect = (
                int(roi.x() * ratio_x),
                int(roi.y() * ratio_y),
                int(roi.width() * ratio_x),
                int(roi.height() * ratio_y),
            )
            result = blur_patch(pixels, rect, self._strength, self._feather)
            if result is None:
                continue
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

    def _paint_crop(self, painter: QPainter, target: QRectF) -> None:
        rect = self._crop_widget_rect()
        painter.fillRect(
            QRectF(target.left(), target.top(), target.width(), rect.top() - target.top()),
            CROP_DIM,
        )
        painter.fillRect(
            QRectF(target.left(), rect.bottom(), target.width(), target.bottom() - rect.bottom()),
            CROP_DIM,
        )
        painter.fillRect(
            QRectF(target.left(), rect.top(), rect.left() - target.left(), rect.height()),
            CROP_DIM,
        )
        painter.fillRect(
            QRectF(rect.right(), rect.top(), target.right() - rect.right(), rect.height()),
            CROP_DIM,
        )

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 70), 1))
        for fraction in (1 / 3, 2 / 3):
            x = rect.left() + rect.width() * fraction
            y = rect.top() + rect.height() * fraction
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        painter.setPen(QPen(CROP_COLOR, 2))
        painter.drawRect(rect)
        painter.setPen(QPen(Qt.GlobalColor.white, 1))
        painter.setBrush(CROP_COLOR)
        for point in self._handle_points(rect).values():
            painter.drawRect(QRectF(point.x() - HANDLE, point.y() - HANDLE, HANDLE * 2, HANDLE * 2))

        crop = self.crop_rect()
        text = f"{crop.width()} x {crop.height()}"
        label_width = painter.fontMetrics().horizontalAdvance(text) + 12
        label = QRectF(rect.left() + 6, rect.top() + 6, label_width, 20)
        painter.fillRect(label, QColor(0, 0, 0, 170))
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(label, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_roi(self, painter: QPainter, area: _Area) -> None:
        rect = self._widget_rect(area)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(ACCENT, 2, Qt.PenStyle.DashLine))
        painter.drawRect(rect)
        painter.setPen(QPen(Qt.GlobalColor.white, 1))
        painter.setBrush(ACCENT)
        for point in self._handle_points(rect).values():
            painter.drawRect(QRectF(point.x() - HANDLE, point.y() - HANDLE, HANDLE * 2, HANDLE * 2))

    def _paint_buttons(self, painter: QPainter, area: _Area) -> None:
        confirm, delete = self._button_rects(area)
        for button, color, name in ((confirm, GREEN, "check"), (delete, RED, "x")):
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(QPen(Qt.GlobalColor.white, 1.5))
            painter.setBrush(color)
            painter.drawEllipse(button)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            icon_size = int(button.width() * 0.6)
            inset = (button.width() - icon_size) / 2
            painter.drawPixmap(
                QPointF(button.x() + inset, button.y() + inset),
                icons.pixmap(name, icon_size, "#ffffff"),
            )

    def leaveEvent(self, event) -> None:
        if self._mode is None:
            self.unsetCursor()
            self.setToolTip("")
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._video_width == 0:
            return
        area, mode = self._hit(event.position())
        if mode is not None and mode.startswith("crop-"):
            self._crop_mode = mode[len("crop-"):]
            self._press_point = self._to_video(event.position())
            self._press_crop = QRectF(self._crop)
            return
        if area is None or mode is None:
            return
        if mode == "reveal":
            self._set_editing(area, True)
            return
        self._active = area
        self._mode = mode
        self._target = area
        self._press_point = self._to_video(event.position())
        self._press_roi = QRectF(area.rect)
        if mode == "create":
            area.rect = QRectF(self._press_point, self._press_point)

    def mouseMoveEvent(self, event) -> None:
        if self._video_width == 0:
            return
        dragging = bool(event.buttons() & Qt.MouseButton.LeftButton)
        if dragging and self._crop_mode is not None and self._crop is not None:
            self._crop = self._crop_dragged(self._to_video(event.position()))
            self.update()
            return
        if not dragging or self._mode is None:
            _, mode = self._hit(event.position())
            if mode is None:
                self.unsetCursor()
            else:
                self.setCursor(QCursor(CURSORS.get(mode, Qt.CursorShape.ArrowCursor)))
            self.setToolTip(TOOLTIPS.get(mode, ""))
            return
        if self._mode in ("confirm", "delete") or self._target is None:
            return
        self._target.rect = self._dragged_roi(self._to_video(event.position()))
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
        area, mode = self._target, self._mode
        self._mode = None
        self._target = None
        self._crop_mode = None
        if area is None:
            return
        if mode == "confirm":
            if self._button_rects(area)[0].contains(event.position()):
                self._set_editing(area, False)
                self.unsetCursor()
                self.setToolTip("")
            return
        if mode == "delete":
            if self._button_rects(area)[1].contains(event.position()):
                self._delete_area(area)
            return
        if mode == "create" and (
            area.rect.width() < MIN_SIZE or area.rect.height() < MIN_SIZE
        ):
            area.rect = self._press_roi
            self.update()
