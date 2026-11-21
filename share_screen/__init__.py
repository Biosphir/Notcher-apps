"""Peer-to-peer screen sharing between two Notcher clients."""
import json
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QFile, QIODevice, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEnginePermission, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QDialogButtonBox, QLabel, QPushButton
from PySide6.QtGui import QColor
from shared.window import NotcherDialog, NotcherWindow
from .remote_input import RemoteInput, monitors


class SharePage(QWebEnginePage):
    local_message = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.prefix = f"notcher:{uuid4()}:"

    def javaScriptConsoleMessage(self, level, message, line, source_id):
        if message.startswith(self.prefix) and len(message) <= 256000:
            self.local_message.emit(message[len(self.prefix):])

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        return url.scheme() == "data" or url.toString() == "about:blank"


class ShareScreen(NotcherWindow):
    def __init__(self):
        super().__init__("Share Screen", (960, 700), (680, 500))
        layout = self.body_layout
        self.remote_input = RemoteInput(self)
        self.remote_access = QPushButton("Allow remote control…")
        self.remote_access.setVisible(False)
        self.remote_access.clicked.connect(self.toggle_remote_access)
        self.remote_input.availability_changed.connect(self.remote_access.setVisible)
        self.remote_input.permission_changed.connect(self.update_remote_access)
        layout.addWidget(self.remote_access)
        self.web = QWebEngineView()
        self.page = SharePage(self.web)
        self.page.renderProcessTerminated.connect(lambda *_: self.remote_input.peer_ready(False))
        self.web.setPage(self.page)
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
        self.web.setHtml(
            html.replace("<!-- webchannel -->", self.create_local_transport()),
            QUrl("https://notcher.local/"),
        )

    def create_local_transport(self):
        from .account_signaling import AccountSignaling

        self.account_signaling = AccountSignaling(self)
        try:
            from PySide6.QtWebChannel import QWebChannel
        except ImportError:
            pass
        else:
            script = QFile(":/qtwebchannel/qwebchannel.js")
            if script.open(QIODevice.OpenModeFlag.ReadOnly):
                self.account_channel = QWebChannel(self.page)
                self.account_channel.registerObject("signaling", self.account_signaling)
                self.account_channel.registerObject("remoteInput", self.remote_input)
                self.page.setWebChannel(self.account_channel)
                content = bytes(script.readAll()).decode()
                script.close()
                return "<script>" + content + "</script>"

        # Some released hosts lack the Python WebChannel binding. The existing
        # WebEngine page can exchange messages with the trusted local HTML.
        self.page.local_message.connect(self.dispatch_local_message)
        self.account_signaling.reply.connect(
            lambda request, payload: self.deliver_local_message("reply", request, payload)
        )
        self.remote_input.permission_changed.connect(
            lambda grant: self.deliver_local_message("permission_changed", grant)
        )
        return "<script>window.notcherConsolePrefix = " + json.dumps(self.page.prefix) + ";</script>"

    def dispatch_local_message(self, payload):
        methods = {
            "send": self.account_signaling.send,
            "peer_ready": self.remote_input.peer_ready,
            "heartbeat": self.remote_input.heartbeat,
            "release_input": self.remote_input.release_input,
            "keyboard": self.remote_input.keyboard,
            "pointer": self.remote_input.pointer,
        }
        try:
            name, args = json.loads(payload)
            if isinstance(args, list) and name in methods:
                methods[name](*args)
        except (ValueError, TypeError, OverflowError):
            return

    def deliver_local_message(self, event, *args):
        message = json.dumps([event, *args])
        self.page.runJavaScript(f"window.receiveNotcherMessage?.({message});")

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
        self.remote_input.set_display_source(False)
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
            self.remote_input.set_display_source(True)
            request.selectScreen(index)
        else:
            request.selectWindow(index)

    def toggle_remote_access(self):
        controller = self.remote_input
        if controller.target is not None:
            controller.revoke()
            return
        if not controller.available:
            return
        dialog = NotcherDialog("Allow remote control", self)
        explanation = QLabel(
            "Allow the connected device on your account to use your mouse and keyboard. "
            "Select the same display you are sharing. You can stop control here or press Ctrl+Alt+Shift+F12."
        )
        explanation.setWordWrap(True)
        dialog.body_layout.addWidget(explanation)
        displays = QComboBox()
        entries = monitors(controller.api)
        if len(entries) > 1:
            displays.addItem("Select the display being shared", None)
        for name, (left, top, right, bottom) in entries.items():
            short_name = name.split("\\")[-1]
            displays.addItem(f"{short_name} · {right - left} × {bottom - top} · ({left}, {top})", name)
        dialog.body_layout.addWidget(displays)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        allow = buttons.button(QDialogButtonBox.StandardButton.Ok)
        allow.setText("Allow control")
        allow.setEnabled(displays.currentData() is not None)
        displays.currentIndexChanged.connect(lambda: allow.setEnabled(displays.currentData() is not None))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setFocus()
        dialog.body_layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            controller.grant(displays.currentData())

    def update_remote_access(self, grant_id):
        self.remote_access.setText(
            "Stop remote control · Ctrl+Alt+Shift+F12" if grant_id else "Allow remote control…"
        )

    def full_screen_requested(self, request):
        request.accept()
        if request.toggleOn():
            self.showFullScreen()
        else:
            self.showNormal()

    def closeEvent(self, event):
        self.remote_input.peer_ready(False)
        self.page.runJavaScript("window.stopSharing && window.stopSharing();")
        self.page.setHtml("")
        super().closeEvent(event)
