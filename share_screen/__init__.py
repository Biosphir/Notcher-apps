"""Peer-to-peer screen sharing between two Notcher clients."""
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEnginePermission, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget


class SharePage(QWebEnginePage):
    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        return url.scheme() == "data" or url.toString() == "about:blank" or url.host() == "notcher.local"


class ShareScreen(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Share Screen — Notcher")
        self.resize(960, 700)
        self.setMinimumSize(640, 480)
        self.setStyleSheet("background: #080808;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.web = QWebEngineView()
        self.page = SharePage(self.web)
        self.web.setPage(self.page)
        self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.ScreenCaptureEnabled, True)
        self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
        self.capture_authorized = False
        self.page.desktopMediaRequested.connect(self.select_source)
        self.page.permissionRequested.connect(self.permission_requested)
        self.page.fullScreenRequested.connect(self.full_screen_requested)
        self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
        layout.addWidget(self.web)
        html = (Path(__file__).parent / "screen.html").read_text(encoding="utf-8-sig")
        self.web.setHtml(html, QUrl("https://notcher.local/"))

    def permission_requested(self, permission):
        if (permission.permissionType() == QWebEnginePermission.PermissionType.DesktopVideoCapture
                and permission.origin().host() == "notcher.local"
                and self.capture_authorized):
            self.capture_authorized = False
            permission.grant()
        else:
            permission.deny()

    def select_source(self, request):
        self.capture_authorized = False
        dialog = QDialog(self)
        dialog.setWindowTitle("Choose what to share")
        dialog.setStyleSheet(
            "QWidget { background: #171717; color: #f5f5f5; font-size: 13px; }"
            "QComboBox, QPushButton { padding: 8px; }"
        )
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Select a display or window to share with the other user."))
        sources = QComboBox()
        models = (("Display", request.screensModel()), ("Window", request.windowsModel()))
        for kind, model in models:
            for row in range(model.rowCount()):
                index = model.index(row, 0)
                sources.addItem(f"{kind} · {model.data(index)}", (kind, index))
        layout.addWidget(sources)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(sources.count() > 0)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            request.cancel()
            return
        kind, index = sources.currentData()
        if not index.isValid():
            request.cancel()
            return
        self.capture_authorized = True
        if kind == "Display":
            request.selectScreen(index)
        else:
            request.selectWindow(index)

    def full_screen_requested(self, request):
        request.accept()
        self.showFullScreen() if request.toggleOn() else self.showNormal()

    def closeEvent(self, event):
        self.page.runJavaScript("window.stopSharing && window.stopSharing();")
        self.page.setHtml("")
        super().closeEvent(event)
