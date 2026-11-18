"""Pick an exact color from a frozen snapshot of any connected display."""
from PySide6.QtCore import QPoint, QRect, QSettings, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from shared.window import NotcherWindow


class ColorOverlay(QWidget):
    picked = Signal(QColor)
    cancelled = Signal()

    def __init__(self, geometry, pixmap):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setGeometry(geometry)
        self.image = pixmap.toImage()
        self.pixmap = pixmap
        self.position = self.mapFromGlobal(QCursor.pos())
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def color_at(self, point):
        x = max(0, min(self.image.width() - 1, int(point.x() * self.image.width() / max(1, self.width()))))
        y = max(0, min(self.image.height() - 1, int(point.y() * self.image.height() / max(1, self.height()))))
        return self.image.pixelColor(x, y)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.pixmap)
        color = self.color_at(self.position)
        label = color.name().upper() + "  ·  Click to pick · Esc to cancel"
        width = self.fontMetrics().horizontalAdvance(label) + 28
        x = max(8, min(self.position.x() + 18, self.width() - width - 8))
        y = max(8, min(self.position.y() + 22, self.height() - 44))
        box = QRect(x, y, width, 34)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#080808"))
        painter.setPen(QColor("#454545"))
        painter.drawRoundedRect(box, 9, 9)
        painter.setPen(QColor("#f5f5f5"))
        painter.drawText(box.adjusted(12, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter, label)
        painter.setPen(QPen(QColor("#000000"), 3))
        painter.drawEllipse(self.position, 7, 7)
        painter.setPen(QPen(QColor("#ffffff"), 1))
        painter.drawEllipse(self.position, 7, 7)

    def mouseMoveEvent(self, event):
        self.position = event.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(self.color_at(event.position().toPoint()))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
        else:
            super().keyPressEvent(event)


class ColorPicker(NotcherWindow):
    def __init__(self):
        super().__init__("Color Picker", (510, 450), (430, 380))
        self.settings = QSettings("MartianMST", "Notcher")
        self.overlays = []
        self.picking = False
        layout = self.body_layout
        layout.setSpacing(12)
        self.swatch = QFrame()
        self.swatch.setMinimumHeight(110)
        self.swatch.setObjectName("colorSwatch")
        layout.addWidget(self.swatch, 1)
        self.hex_value = QLineEdit()
        self.hex_value.setReadOnly(True)
        self.hex_value.setAccessibleName("HEX color")
        self.rgb_value = QLineEdit()
        self.rgb_value.setReadOnly(True)
        self.rgb_value.setAccessibleName("RGB color")
        for field, label in ((self.hex_value, "Copy HEX"), (self.rgb_value, "Copy RGB")):
            row = QHBoxLayout()
            row.addWidget(field, 1)
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, value=field: self.copy_color(value))
            row.addWidget(button)
            layout.addLayout(row)
        self.status = QLabel("Pick a color anywhere on your displays")
        self.status.setStyleSheet("color: #858585;")
        layout.addWidget(self.status)
        pick_button = QPushButton("Pick color from screen")
        pick_button.setProperty("primary", True)
        pick_button.clicked.connect(self.start_pick)
        layout.addWidget(pick_button)
        self.capture_timer = QTimer(self)
        self.capture_timer.setSingleShot(True)
        self.capture_timer.timeout.connect(self.capture_screens)
        color = QColor(self.settings.value("colorPicker/lastColor", "#A73A93"))
        self.set_color(color if color.isValid() else QColor("#A73A93"))

    def set_color(self, color):
        self.hex_value.setText(color.name().upper())
        self.rgb_value.setText(f"rgb({color.red()}, {color.green()}, {color.blue()})")
        self.swatch.setStyleSheet(
            f"QFrame#colorSwatch {{ background: {color.name()}; border: 1px solid #454545; border-radius: 16px; }}"
        )
        self.settings.setValue("colorPicker/lastColor", color.name())

    def copy_color(self, field):
        QApplication.clipboard().setText(field.text())
        self.status.setText("Copied " + field.text())

    def start_pick(self):
        if self.picking:
            return
        self.picking = True
        self.hide()
        self.capture_timer.start(180)

    def capture_screens(self):
        snapshots = [(screen.geometry(), screen.grabWindow(0)) for screen in QGuiApplication.screens()]
        snapshots = [(geometry, pixmap) for geometry, pixmap in snapshots if not pixmap.isNull()]
        if not snapshots:
            self.finish_pick(None)
            self.status.setText("Could not capture the display. Try again from the Windows desktop.")
            return
        for geometry, pixmap in snapshots:
            overlay = ColorOverlay(geometry, pixmap)
            overlay.picked.connect(self.finish_pick)
            overlay.cancelled.connect(lambda: self.finish_pick(None))
            self.overlays.append(overlay)
            overlay.show()
        active = next(
            (overlay for overlay in self.overlays if overlay.geometry().contains(QCursor.pos())),
            self.overlays[0],
        )
        active.activateWindow()
        active.setFocus()

    def finish_pick(self, color):
        if not self.picking:
            return
        self.picking = False
        overlays, self.overlays = self.overlays, []
        for overlay in overlays:
            overlay.close()
        if color is not None:
            self.set_color(color)
            self.status.setText("Color picked")
        else:
            self.status.setText("Selection cancelled")
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        self.capture_timer.stop()
        self.picking = False
        overlays, self.overlays = self.overlays, []
        for overlay in overlays:
            overlay.close()
        super().closeEvent(event)
