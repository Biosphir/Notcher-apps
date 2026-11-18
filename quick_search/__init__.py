"""Tabbed browser for the Quick Search popup."""
import re
from urllib.parse import urlencode

from PySide6.QtCore import QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QPainterPath, QRegion, QShortcut
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QStackedWidget, QTabBar, QVBoxLayout, QWidget


from notcher_widgets import asset_icon

BROWSER_BUTTON_STYLE = (
    "QPushButton { background: #171717; color: #e5e5e5; border: 1px solid #303030;"
    " border-radius: 7px; padding: 0 10px; }"
    " QPushButton:hover:enabled { background: #282828; }"
    " QPushButton:disabled { color: #707070; }"
)


class QuickSearchPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        return url.scheme() in ("http", "https") or url.toString() == "about:blank"

    def createWindow(self, window_type):
        return None


class RoundedWebView(QWebEngineView):
    def resizeEvent(self, event):
        super().resizeEvent(event)
        shape = QPainterPath()
        shape.addRoundedRect(QRectF(self.rect()), 10, 10)
        self.setMask(QRegion(shape.toFillPolygon().toPolygon()))


class BrowserAddressField(QLineEdit):
    def keyPressEvent(self, event):
        super().keyPressEvent(event)
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # The line edit submits the address; do not also activate a dialog button.
            event.accept()


class BrowserTab(QWidget):
    opened_externally = Signal()

    def __init__(self, profile):
        super().__init__()
        self.requested_url = QUrl()
        self.web = RoundedWebView(self)
        self.web.setPage(QuickSearchPage(profile, self.web))
        self.web.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        self.web.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False)

        self.address = self._address_field()
        self.address.returnPressed.connect(lambda: self.navigate(self.address.text()))
        self.back = QPushButton(asset_icon("icon-back.svg"), "")
        self.back.setAccessibleName("Back")
        self.back.setToolTip("Back")
        self.back.clicked.connect(self.web.back)
        self.forward = QPushButton(asset_icon("icon-forward.svg"), "")
        self.forward.setAccessibleName("Forward")
        self.forward.setToolTip("Forward")
        self.forward.clicked.connect(self.web.forward)
        self.refresh = self.address.addAction(
            asset_icon("icon-refresh.svg"), QLineEdit.ActionPosition.LeadingPosition
        )
        self.refresh.setText("Refresh")
        self.refresh.setToolTip("Refresh")
        self.refresh.triggered.connect(self.web.reload)
        self.external = QPushButton(asset_icon("icon-open-browser.svg"), "Open in browser")
        self.external.clicked.connect(self.open_external)
        for button in (self.back, self.forward, self.external):
            button.setFixedHeight(32)
            button.setIconSize(QSize(18, 18))
            button.setStyleSheet(BROWSER_BUTTON_STYLE)
        for button in (self.back, self.forward):
            button.setFixedWidth(36)
            button.setStyleSheet(BROWSER_BUTTON_STYLE + " QPushButton { padding: 0; }")
        self.address.setFixedHeight(32)
        self.status = QLabel()
        self.status.setStyleSheet("color: #a0a0a0; font-size: 12px;")
        self.status.hide()

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        toolbar.addWidget(self.back)
        toolbar.addWidget(self.forward)
        toolbar.addWidget(self.address, 1)
        toolbar.addWidget(self.external)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(6)
        layout.addLayout(toolbar)
        layout.addWidget(self.status)
        layout.addWidget(self.web, 1)

        self.web.page().setBackgroundColor(QColor("#080808"))
        self.web.urlChanged.connect(self._update_address)
        self.web.loadStarted.connect(lambda: self._set_status("Loading…"))
        self.web.loadFinished.connect(self._finished)
        self._update_address(QUrl())

    @staticmethod
    def _address_field():
        field = BrowserAddressField()
        field.setPlaceholderText("Search the web or enter a URL")
        field.setAccessibleName("Web address or search query")
        field.setStyleSheet(
            "QLineEdit { background: #171717; color: #f5f5f5; border: 1px solid #383838;"
            " border-radius: 7px; padding: 0 10px; }"
            " QLineEdit:focus { border-color: #A73A93; }"
        )
        return field

    def focus_address(self):
        self.address.setFocus()
        self.address.selectAll()

    def navigate(self, text):
        text = text.strip()
        if not text:
            return
        url = QUrl(text)
        if not url.scheme() and re.match(r"^[^\s/]+\.[^\s/]+(?:/\S*)?$", text):
            url = QUrl("https://" + text)
        if url.scheme() not in ("http", "https") or not url.host():
            url = QUrl("https://www.google.com/search?" + urlencode({"q": text}))
        self.requested_url = url
        self.address.setText(url.toDisplayString())
        self.web.setUrl(url)

    def _update_address(self, url):
        is_web = url.scheme() in ("http", "https")
        if is_web:
            self.address.setText(url.toDisplayString())
        self.external.setEnabled(is_web)
        self.back.setEnabled(self.web.history().canGoBack())
        self.forward.setEnabled(self.web.history().canGoForward())
        self.refresh.setEnabled(is_web)

    def _set_status(self, message):
        self.status.setText(message)
        self.status.setVisible(bool(message))

    def _finished(self, success):
        self._update_address(self.web.url())
        if not success and self.requested_url.isValid():
            self.external.setEnabled(True)
        url = self.web.url()
        if url.host().endswith(".google.com") and url.path().startswith("/sorry/"):
            self._set_status("Google is asking for verification. You can continue in your browser.")
        else:
            self._set_status("" if success else "Page could not load. Try Open in browser.")

    def open_external(self):
        url = self.web.url()
        if url.scheme() not in ("http", "https") or url.path().startswith("/sorry/"):
            url = self.requested_url
        if url.scheme() in ("http", "https") and QDesktopServices.openUrl(url):
            self.opened_externally.emit()


class QuickSearch(QWidget):
    opened_externally = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pages = QStackedWidget()
        self.profile = QWebEngineProfile("NotcherQuickSearch")
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies
        )
        self.tabs = QTabBar()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.setExpanding(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.currentChanged.connect(self._select_tab)
        self.tabs.setStyleSheet(
            "QTabBar { background: transparent; border: none; } QTabBar::tab { background: #141414; color: #a0a0a0;"
            " min-width: 150px; min-height: 30px; padding: 0 12px;"
            " border: 1px solid #242424; border-radius: 7px; margin-right: 4px; }"
            " QTabBar::tab:hover { background: #202020; }"
            " QTabBar::tab:selected { background: #252525; color: #f5f5f5;"
            " border-color: #A73A93; }"
        )
        new_tab = QPushButton("+")
        new_tab.setAccessibleName("New tab")
        new_tab.setToolTip("New tab (Ctrl+T)")
        new_tab.clicked.connect(self.add_tab)
        new_tab.setFixedSize(32, 32)
        new_tab.setStyleSheet(BROWSER_BUTTON_STYLE + " QPushButton { padding: 0; font-size: 18px; }")

        tab_row = QHBoxLayout()
        tab_row.setSpacing(4)
        tab_row.addWidget(self.tabs, 0, Qt.AlignmentFlag.AlignVCenter)
        tab_row.addWidget(new_tab, 0, Qt.AlignmentFlag.AlignVCenter)
        tab_row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.addLayout(tab_row)
        layout.addWidget(self.pages, 1)
        self.profile.setParent(self)  # Destroy browser pages before their profile.
        for keys, callback in (
            ("Ctrl+T", self.add_tab),
            ("Ctrl+W", lambda: self.close_tab(self.tabs.currentIndex())),
            ("Ctrl+L", self.focus_address),
        ):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
        self.add_tab()

    def add_tab(self):
        tab = BrowserTab(self.profile)
        tab.opened_externally.connect(self.opened_externally.emit)
        self.pages.addWidget(tab)
        index = self.tabs.addTab("New tab")
        self.tabs.setTabData(index, tab)
        close = QPushButton("×")
        close.setAccessibleName("Close tab")
        close.setToolTip("Close tab")
        close.setFixedSize(20, 20)
        close.setStyleSheet(
            "QPushButton { background: transparent; color: #bdbdbd; border: none;"
            " border-radius: 5px; padding: 0; font-size: 16px; }"
            " QPushButton:hover { background: #383838; color: #fff; }"
        )
        close.clicked.connect(lambda: self.close_tab(self._index_of_tab(tab)))
        slot = QWidget()
        slot_layout = QHBoxLayout(slot)
        slot_layout.setContentsMargins(4, 0, 8, 0)
        slot_layout.addWidget(close)
        self.tabs.setTabButton(index, QTabBar.ButtonPosition.RightSide, slot)
        tab.web.titleChanged.connect(lambda title: self._update_tab_title(tab, title))
        self.tabs.setCurrentIndex(index)
        self._select_tab(index)
        tab.focus_address()

    def _select_tab(self, index):
        if index >= 0:
            tab = self.tabs.tabData(index)
            if tab is not None:
                self.pages.setCurrentWidget(tab)

    def _index_of_tab(self, tab):
        return next(
            (index for index in range(self.tabs.count()) if self.tabs.tabData(index) is tab),
            -1,
        )

    def _update_tab_title(self, tab, title):
        index = self._index_of_tab(tab)
        if index >= 0:
            self.tabs.setTabText(index, title[:32] or "New tab")
            self.tabs.setTabToolTip(index, title)

    def close_tab(self, index):
        if index < 0:
            return
        tab = self.tabs.tabData(index)
        self.tabs.removeTab(index)
        self.pages.removeWidget(tab)
        tab.web.stop()
        tab.deleteLater()
        if not self.tabs.count():
            self.add_tab()
        else:
            self._select_tab(self.tabs.currentIndex())

    def focus_address(self):
        self.pages.currentWidget().focus_address()

    def stop(self):
        for index in range(self.pages.count()):
            self.pages.widget(index).web.stop()
