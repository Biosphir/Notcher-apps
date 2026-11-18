"""Windows controls for monitors physically connected to this PC."""
import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QLabel, QListWidget, QPushButton, QVBoxLayout, QWidget,
)


def extend_displays():
    if sys.platform != "win32":
        raise OSError("Extended Display currently supports Windows.")
    user = ctypes.WinDLL("user32")
    apply = user.SetDisplayConfig
    apply.argtypes = [
        wintypes.UINT, ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p, wintypes.UINT
    ]
    apply.restype = wintypes.LONG
    # SDC_APPLY | SDC_TOPOLOGY_EXTEND uses the connected displays' saved modes.
    result = apply(0, None, 0, None, 0x80 | 0x04)
    if result:
        raise OSError(
            result,
            ctypes.FormatError(result).strip()
            + " Check that the additional monitor is connected and detected by Windows.",
        )


class ExtendedDisplay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Extended Display — Notcher")
        self.resize(520, 360)
        self.setMinimumSize(420, 280)
        self.setStyleSheet(
            "QWidget { background: #080808; color: #f5f5f5; font-size: 13px; }"
            "QPushButton { background: #242424; border: 1px solid #383838;"
            " border-radius: 6px; padding: 8px 12px; }"
            "QPushButton:hover { background: #343434; }"
            "QListWidget { background: #111111; border: 1px solid #303030;"
            " border-radius: 6px; padding: 6px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        heading = QLabel("Extended Display")
        heading.setStyleSheet("font-size: 22px; font-weight: 700;")
        layout.addWidget(heading)
        explanation = QLabel("Extend your Windows desktop across the monitors connected to this PC.")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        layout.addWidget(QLabel("Active displays"))
        self.displays = QListWidget()
        layout.addWidget(self.displays, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #a3a3a3;")
        layout.addWidget(self.status)
        self.extend_button = QPushButton("Extend displays")
        self.extend_button.clicked.connect(self.apply_extend)
        self.extend_button.setEnabled(sys.platform == "win32")
        layout.addWidget(self.extend_button)
        settings = QPushButton("Open Windows display settings")
        settings.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("ms-settings:display")))
        layout.addWidget(settings)
        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.refresh_displays)
        self.refresh_displays()

    def refresh_displays(self):
        screens = QGuiApplication.screens()
        labels = [
            f"{screen.name()} · {screen.size().width()} × {screen.size().height()}"
            + (" · Primary" if screen is QGuiApplication.primaryScreen() else "")
            for screen in screens
        ]
        if labels != [self.displays.item(index).text() for index in range(self.displays.count())]:
            self.displays.clear()
            self.displays.addItems(labels)

    def apply_extend(self):
        try:
            extend_displays()
        except OSError as error:
            self.status.setText(str(error))
            return
        self.status.setText("Extend mode applied. Windows display settings lets you arrange your monitors.")
        QTimer.singleShot(500, self.refresh_displays)

    def showEvent(self, event):
        self.refresh_displays()
        self.timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)
