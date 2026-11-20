"""Translate selected text in a compact Notcher window."""
from collections import deque
from html import unescape
import json
from urllib.parse import urlencode

from PySide6.QtCore import QPoint, QUrl, Qt
from PySide6.QtGui import QGuiApplication, QTextDocument
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton

from shared.window import NotcherWindow


LANGUAGES = (("English", "en"), ("Indonesian", "id"), ("Japanese", "ja"),
             ("Korean", "ko"), ("Chinese", "zh-CN"), ("Spanish", "es"),
             ("French", "fr"), ("German", "de"), ("Arabic", "ar"))


def split_text(text):
    """Keep sentence/word boundaries where possible within the API byte cap."""
    while text:
        if len(text.encode("utf-8")) <= 500:
            yield text, ""
            return
        prefix = text.encode("utf-8")[:500].decode("utf-8", errors="ignore")
        boundary = max(prefix.rfind("\n"), prefix.rfind(" "))
        if boundary > len(prefix) // 2:
            yield prefix[:boundary], text[boundary]
            text = text[boundary + 1:]
        else:
            yield prefix, ""
            text = text[len(prefix):]


class QuickTranslation(NotcherWindow):
    def __init__(self):
        super().__init__("Quick Translation", (400, 300), (320, 160))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.WindowType.Tool)
        self.network = QNetworkAccessManager(self)
        self.reply = None
        self.anchor = None
        self.parts = deque()
        self.results = []
        self.surface.layout().setContentsMargins(16, 12, 16, 12)
        self.surface.layout().setSpacing(8)
        self.title_bar.findChild(QLabel).setStyleSheet("font-size: 14px; font-weight: 700;")
        for button in self.title_bar.findChildren(QPushButton):
            if button.accessibleName() != "Close":
                button.hide()
        self.title_bar.dialog = True
        self.body_layout.setSpacing(7)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Type or paste text to translate")
        self.input.setFixedHeight(70)
        self.body_layout.addWidget(self.input)
        actions = QHBoxLayout()
        self.source, self.target = QComboBox(), QComboBox()
        self.source.setAccessibleName("Source language")
        self.target.setAccessibleName("Target language")
        for combo in (self.source, self.target):
            combo.setStyleSheet("""
                QComboBox { background: transparent; border: 1px solid transparent; }
                QComboBox::drop-down { background: transparent; border: none; }
                QComboBox:hover, QComboBox:focus, QComboBox:on {
                    background: #191919; border-color: #383838;
                }
            """)
            for name, code in LANGUAGES:
                combo.addItem(name, code)
        self.target.setCurrentIndex(1)
        actions.addWidget(self.source, 1)
        actions.addWidget(QLabel("→"))
        actions.addWidget(self.target, 1)
        translate = QPushButton("Translate")
        translate.setStyleSheet("""
            QPushButton { background: transparent; border: 1px solid transparent; }
            QPushButton:hover, QPushButton:focus, QPushButton:pressed {
                background: #191919; border-color: #383838;
            }
        """)
        translate.clicked.connect(self.translate)
        actions.addWidget(translate)
        self.body_layout.addLayout(actions)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setAccessibleName("Translation result")
        self.output.setStyleSheet("font-size: 12px; background: #101010; border: none; padding: 4px;")
        self.body_layout.addWidget(self.output)
        provider = QLabel("Selected text is sent to MyMemory for translation.")
        provider.setStyleSheet("color: #a1a1a1; font-size: 10px;")
        self.body_layout.addWidget(provider)
        self.show_result("Enter text and choose the languages.")

    def show_selection(self, text, anchor):
        self.anchor = QPoint(anchor)
        self.input.setPlainText(text)
        self.input.hide()
        self.translate()
        self.show()
        self.raise_()

    def open_standalone(self):
        self.anchor = None
        self.input.show()
        self.show_result(self.output.toPlainText())

    def show_result(self, text):
        self.output.setPlainText(text)
        screen = QGuiApplication.screenAt(self.anchor) if self.anchor is not None else self.screen()
        bounds = (screen or QGuiApplication.primaryScreen()).availableGeometry()
        width = min(bounds.width(), max(350, min(460, 320 + len(text) // 3)))
        document = QTextDocument()
        document.setDefaultFont(self.output.font())
        document.setPlainText(text)
        document.setTextWidth(width - 64)
        height = round(document.size().height()) + 12
        self.output.setFixedHeight(max(42, min(200, height)))
        self.resize(width, max(self.minimumHeight(), self.sizeHint().height()))
        if self.anchor is not None:
            x = max(bounds.left(), min(self.anchor.x(), bounds.right() - self.width() + 1))
            y = self.anchor.y() - self.height() - 8
            if y < bounds.top():
                y = min(self.anchor.y() + 24, bounds.bottom() - self.height() + 1)
            self.move(x, max(bounds.top(), y))

    def cancel_request(self):
        reply, self.reply = self.reply, None
        if reply is not None:
            reply.abort()

    def translate(self):
        self.cancel_request()
        text = self.input.toPlainText().strip()
        if not text:
            self.show_result("Enter text to translate.")
            return
        if len(text.encode("utf-8")) > 2500:
            self.show_result("Select up to 2,500 bytes of text at a time.")
            return
        self.language_pair = f"{self.source.currentData()}|{self.target.currentData()}"
        if self.source.currentData() == self.target.currentData():
            self.show_result("Choose two different languages.")
            return
        self.parts = deque(split_text(text))
        self.results = []
        self.show_result("Translating…")
        self.fetch_next()

    def fetch_next(self):
        if not self.parts:
            self.show_result("".join(self.results))
            return
        text, separator = self.parts.popleft()
        query = urlencode({"q": text, "langpair": self.language_pair})
        request = QNetworkRequest(QUrl("https://api.mymemory.translated.net/get?" + query))
        request.setTransferTimeout(12000)
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        reply = self.network.get(request)
        self.reply = reply
        reply.finished.connect(lambda: self.receive(reply, separator))

    def receive(self, reply, separator):
        reply.deleteLater()
        if reply is not self.reply:
            return
        self.reply = None
        if reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) == 429:
            self.show_result("The translation service has reached its usage limit. Try again later.")
            return
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self.show_result("Translation service unavailable. Check your connection and try again.")
            return
        try:
            data = json.loads(bytes(reply.readAll()))
            if data.get("quotaFinished") or str(data.get("responseStatus")) == "429":
                self.show_result("The translation service has reached its usage limit. Try again later.")
                return
            if str(data.get("responseStatus")) != "200":
                raise ValueError
            translated = data["responseData"]["translatedText"]
            if not isinstance(translated, str) or not translated.strip():
                raise ValueError
        except (AttributeError, KeyError, TypeError, ValueError):
            self.show_result("Translation unavailable for this text. Check the selected languages and try again.")
            return
        self.results.append(unescape(translated) + separator)
        self.fetch_next()

    def closeEvent(self, event):
        self.cancel_request()
        super().closeEvent(event)
