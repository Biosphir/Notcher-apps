"""Translate selected text in a compact Notcher window."""
from collections import deque
from html import unescape
import json
from pathlib import Path
import sys
from urllib.parse import urlencode

from PySide6.QtCore import QLocale, QPoint, QSettings, QSize, QTimer, QUrl, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QTextDocument, QTextOption
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from shared.window import NotcherWindow
from ._langdetect import DetectorFactory, LangDetectException, detect_langs


LANGUAGES = (("English", "en"), ("Indonesian", "id"), ("Japanese", "ja"),
             ("Korean", "ko"), ("Chinese", "zh-CN"), ("Spanish", "es"),
             ("French", "fr"), ("German", "de"), ("Arabic", "ar"))
LANGUAGE_NAMES = {code: name for name, code in LANGUAGES}
DetectorFactory.seed = 0


def regional_language():
    locale = QLocale.system().name()
    if sys.platform == "win32":
        geo = QSettings(r"HKEY_CURRENT_USER\Control Panel\International\Geo", QSettings.Format.NativeFormat)
        country = geo.value("Name", "", type=str).upper()
        regional = {
            "ID": "id", "JP": "ja", "KR": "ko", "CN": "zh-CN", "TW": "zh-CN",
            "FR": "fr", "DE": "de", "MX": "es", "ES": "es", "SA": "ar",
            "AU": "en", "GB": "en", "US": "en", "NZ": "en",
        }.get(country)
        if regional:
            return regional
    language = locale.split("_", 1)[0]
    if language == "zh":
        return "zh-CN"
    return language if language in LANGUAGE_NAMES else "en"


def resolve_languages(text, source, target, region):
    if source == "auto":
        try:
            guesses = detect_langs(text)
        except LangDetectException:
            guesses = []
        if not guesses or guesses[0].prob < 0.70:
            raise ValueError("Could not detect the source language. Choose it manually and try again.")
        detected = guesses[0].lang
        source = "zh-CN" if detected in ("zh-cn", "zh-tw") else detected
        if source not in LANGUAGE_NAMES:
            raise ValueError("The detected language is not available. Choose a source language if detection was incorrect.")
    if target == "auto":
        target = region if source != region else ("en" if source != "en" else "id")
    if source == target:
        raise ValueError("Choose two different languages.")
    return source, target


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


def translated_segment(data, source_text):
    translation = data["responseData"]["translatedText"]
    matches = data.get("matches", [])
    if matches and matches[0].get("created-by") == "Public Web":
        source_key = source_text.strip().rstrip(".,!?。！？").casefold()
        for match in matches:
            segment = match.get("segment", "").strip().rstrip(".,!?。！？").casefold()
            if (segment == source_key and match.get("created-by") != "Public Web"
                    and isinstance(match.get("match"), (int, float)) and match["match"] >= 0.95
                    and isinstance(match.get("translation"), str) and match["translation"].strip()):
                return match["translation"]
    return translation


class QuickTranslation(NotcherWindow):
    def __init__(self):
        super().__init__("Quick Translation", (400, 300), (320, 160))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.WindowType.Tool)
        self.network = QNetworkAccessManager(self)
        self.settings = QSettings("MartianMST", "Notcher")
        self.delay = QTimer(self)
        self.delay.setSingleShot(True)
        self.delay.setInterval(400)
        self.delay.timeout.connect(self.translate)
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
        self.input.setAccessibleName("Source text")
        field_style = """
            QPlainTextEdit { font-size: 14px; background: #131313; border: none; padding: 0; }
            QScrollBar:vertical { background: transparent; width: 7px; margin: 0; }
            QScrollBar::handle:vertical { background: #505050; border-radius: 3px; min-height: 20px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        """
        self.input.setStyleSheet(field_style)
        actions = QHBoxLayout()
        self.language_actions = actions
        self.source, self.target = QComboBox(), QComboBox()
        self.source.setAccessibleName("Source language")
        self.target.setAccessibleName("Target language")
        self.source.addItem("Auto-detect", "auto")
        self.target.addItem(LANGUAGE_NAMES[regional_language()] + " · Default", "auto")
        self.target.setItemData(0, "Use your region’s language. Switch to the fallback when the source matches it.",
                                Qt.ItemDataRole.ToolTipRole)
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
        for name, combo in (("source", self.source), ("target", self.target)):
            key = f"quickTranslation/{name}"
            saved = self.settings.value(key, "auto", type=str)
            combo.setCurrentIndex(max(0, combo.findData(saved)))
            combo.currentIndexChanged.connect(lambda _index, field=combo, path=key:
                                              self.settings.setValue(path, field.currentData()))
        actions.addWidget(self.source, 1)
        swap = QPushButton(QIcon(str(Path(__file__).with_name("icon-sync.svg"))), "")
        swap.setIconSize(QSize(16, 16))
        swap.setAccessibleName("Swap languages")
        swap.setToolTip("Swap languages")
        swap.clicked.connect(self.swap_languages)
        actions.addWidget(swap)
        actions.addWidget(self.target, 1)
        button_style = """
            QPushButton { background: transparent; border: 1px solid transparent; }
            QPushButton:hover, QPushButton:focus, QPushButton:pressed {
                background: #191919; border-color: #383838;
            }
        """
        swap.setStyleSheet(button_style)
        self.body_layout.addLayout(actions)
        fields = QFrame()
        self.fields = fields
        fields.setObjectName("translationFields")
        fields.setStyleSheet("QFrame#translationFields { background: #131313; border-radius: 8px; }")
        fields_layout = QVBoxLayout(fields)
        fields_layout.setContentsMargins(6, 3, 6, 3)
        fields_layout.setSpacing(0)
        fields_layout.addWidget(self.input)
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: #363636; border: none;")
        fields_layout.addWidget(divider)
        self.direction = QLabel()
        self.direction.setStyleSheet("color: #a1a1a1; font-size: 10px;")
        self.direction.hide()
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Translation")
        self.output.setAccessibleName("Translation result")
        self.output.setStyleSheet(field_style)
        for field in (self.input, self.output):
            field.setFrameShape(QFrame.Shape.NoFrame)
            field.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            field.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            field.document().setDocumentMargin(8)
            field.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        fields_layout.addWidget(self.output)
        self.body_layout.addWidget(fields)
        self.body_layout.addWidget(self.direction)
        provider = QLabel("Selected text is sent to MyMemory for translation.")
        self.provider_label = provider
        provider.setStyleSheet("color: #a1a1a1; font-size: 10px;")
        self.body_layout.addWidget(provider)
        self.show_result("")
        self.input.textChanged.connect(self.queue_translation)
        self.source.currentIndexChanged.connect(self.queue_translation)
        self.target.currentIndexChanged.connect(self.queue_translation)

    def show_selection(self, text, anchor):
        self.anchor = QPoint(anchor)
        self.input.setPlainText(text)
        self.translate()
        self.show()
        self.raise_()

    def open_standalone(self):
        self.anchor = None
        self.input.show()
        self.show_result(self.output.toPlainText())

    def show_result(self, text):
        self.output.setPlainText(text)
        self.resize_fields()

    def resize_fields(self):
        screen = QGuiApplication.screenAt(self.anchor) if self.anchor is not None else self.screen()
        bounds = (screen or QGuiApplication.primaryScreen()).availableGeometry()
        source_text = self.input.toPlainText()
        result_text = self.output.toPlainText()
        width = min(bounds.width(), max(360, min(560, 340 + max(len(result_text), len(source_text)) // 2)))
        field_limit = min(168, max(48, (bounds.height() - 145) // 2))
        for field, content in ((self.input, source_text), (self.output, result_text)):
            document = QTextDocument()
            document.setDefaultFont(field.font())
            document.setDocumentMargin(field.document().documentMargin())
            document.setPlainText(content)
            document.setTextWidth(max(1, width - 65))
            height = round(document.size().height()) + 8
            field.setFixedHeight(max(46, min(field_limit, height)))
        self.fields.setFixedHeight(self.input.height() + self.output.height() + 7)
        chrome = self.surface.layout()
        height = (self.layout().contentsMargins().top() + self.layout().contentsMargins().bottom()
                  + chrome.contentsMargins().top() + chrome.contentsMargins().bottom()
                  + self.title_bar.sizeHint().height() + chrome.spacing()
                  + self.language_actions.sizeHint().height() + self.fields.height()
                  + self.provider_label.sizeHint().height() + 2 * self.body_layout.spacing())
        if not self.direction.isHidden():
            height += self.direction.sizeHint().height() + self.body_layout.spacing()
        self.setMinimumHeight(max(160, height))
        self.resize(width, self.minimumHeight())
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

    def queue_translation(self):
        self.cancel_request()
        self.resize_fields()
        self.delay.start()

    def translate(self):
        self.delay.stop()
        self.cancel_request()
        self.direction.hide()
        text = self.input.toPlainText().strip()
        if not text:
            self.show_result("")
            return
        if len(text.encode("utf-8")) > 2500:
            self.show_result("Select up to 2,500 bytes of text at a time.")
            return
        try:
            source, target = resolve_languages(text, self.source.currentData(), self.target.currentData(), regional_language())
        except ValueError as error:
            self.show_result(str(error))
            return
        self.language_pair = f"{source}|{target}"
        self.target.setItemText(0, LANGUAGE_NAMES[target if self.target.currentData() == "auto" else regional_language()] + " · Default")
        self.direction.setText(f"{LANGUAGE_NAMES[source]} → {LANGUAGE_NAMES[target]}")
        self.direction.show()
        self.parts = deque(split_text(text))
        self.results = []
        if not self.output.toPlainText():
            self.show_result("Translating…")
        else:
            self.resize_fields()
        self.fetch_next()

    def swap_languages(self):
        source, target = self.source.currentData(), self.target.currentData()
        if "auto" in (source, target):
            text = self.input.toPlainText().strip()
            if not text and source == "auto":
                source = "en" if target != "en" else "id"
            try:
                source, target = resolve_languages(text, source, target, regional_language())
            except ValueError as error:
                self.show_result(str(error))
                return
        self.source.setCurrentIndex(self.source.findData(target))
        self.target.setCurrentIndex(self.target.findData(source))

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
        reply.finished.connect(lambda: self.receive(reply, text, separator))

    def receive(self, reply, text, separator):
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
            translated = translated_segment(data, text)
            if not isinstance(translated, str) or not translated.strip():
                raise ValueError
        except (AttributeError, KeyError, TypeError, ValueError):
            self.show_result("Translation unavailable for this text. Check the selected languages and try again.")
            return
        self.results.append(unescape(translated) + separator)
        self.fetch_next()

    def closeEvent(self, event):
        self.delay.stop()
        self.cancel_request()
        super().closeEvent(event)
