from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QStyle, QStyleOptionSlider, QWidget

from . import icons


class JumpSlider(QSlider):
    jumped = Signal(int)

    def __init__(self, parent=None, focus: bool = False):
        super().__init__(Qt.Orientation.Horizontal, parent)
        if not focus:
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _value_at(self, x: int) -> int:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        style = self.style()
        groove = style.subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, self
        )
        handle = style.subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self
        )
        span = max(1, groove.width() - handle.width())
        position = x - groove.x() - handle.width() // 2
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), position, span)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            value = self._value_at(int(event.position().x()))
            self.setValue(value)
            self.jumped.emit(value)
        super().mousePressEvent(event)


class IconLabel(QWidget):
    def __init__(self, icon_name: str, text: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        picture = QLabel()
        picture.setPixmap(icons.pixmap(icon_name, 16))
        picture.setFixedSize(16, 16)
        layout.addWidget(picture)
        self.label = QLabel(text)
        layout.addWidget(self.label)
