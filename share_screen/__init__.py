"""Peer-to-peer screen sharing between two Notcher clients."""
import json
from pathlib import Path

from PySide6.QtCore import QFile, QIODevice, QUrl
try:
    from PySide6.QtWebChannel import QWebChannel
except ImportError:
    QWebChannel = None  # Older packaged Notcher builds can still use manual pairing.
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEnginePermission, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QDialogButtonBox, QLabel
from PySide6.QtGui import QColor
from shared.window import NotcherDialog, NotcherWindow

from .account_signaling import AccountSignaling


class SharePage(QWebEnginePage):
    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        return url.scheme() == "data" or url.toString() == "about:blank" or url.host() == "notcher.local"


class ShareScreen(NotcherWindow):
    def __init__(self):
        super().__init__("Share Screen", (960, 700), (680, 500))
        layout = self.body_layout
        self.web = QWebEngineView()
        self.page = SharePage(self.web)
        self.web.setPage(self.page)
        self.signaling = AccountSignaling(self)
        if QWebChannel is not None:
            self.channel = QWebChannel(self.page)
            self.channel.registerObject("accountSignaling", self.signaling)
            self.page.setWebChannel(self.channel)
        self.page.setBackgroundColor(QColor('#080808'))
        self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.ScreenCaptureEnabled, True)
        self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
        self.capture_authorized = False
        self.page.desktopMediaRequested.connect(self.select_source)
        self.page.permissionRequested.connect(self.permission_requested)
        self.page.fullScreenRequested.connect(self.full_screen_requested)
        self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
        layout.addWidget(self.web)
        html = (Path(__file__).parent / "screen.html").read_text(encoding="utf-8-sig")
        html = html.replace('font: 14px "Segoe UI", sans-serif', 'font: 14px ' + json.dumps(QApplication.font().family()) + ', sans-serif')
        channel_script = QFile(":/qtwebchannel/qwebchannel.js")
        if channel_script.open(QIODevice.OpenModeFlag.ReadOnly):
            html = html.replace("<!-- QWebChannel -->", "<script>" +
                                bytes(channel_script.readAll()).decode("utf-8") + "</script>")
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
        dialog = NotcherDialog("Choose what to share", self)
        layout = dialog.body_layout
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
        if request.toggleOn():
            self.showFullScreen()
        else:
            self.showNormal()

    def closeEvent(self, event):
        self.page.setWebChannel(None)
        self.signaling.close()
        self.page.setHtml("")
        super().closeEvent(event)
