"""Compact, synchronized lyrics for Notcher's active media session."""
from bisect import bisect_right
from pathlib import Path
import sqlite3
import time

from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, QStandardPaths, QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import QApplication, QComboBox, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from shared.window import NotcherWindow
from .provider import Cancelled, LyricsCache, ProviderError, lookup, parse_lrc, track_key

_workers = set()
_shutdown_connected = False


def _release_worker(worker):
    _workers.discard(worker)
    worker.deleteLater()


def _stop_workers():
    for worker in list(_workers):
        worker.requestInterruption()
    for worker in list(_workers):
        worker.wait()


class FetchWorker(QThread):
    result_ready = Signal(int, object)

    def __init__(self, token, track):
        super().__init__()
        self.token = token
        self.track = dict(track)

    def run(self):
        try:
            payload = lookup(self.track, self.isInterruptionRequested)
        except Cancelled:
            return
        except ProviderError as error:
            payload = {"kind": "error", "message": str(error), "retry_at": time.time() + error.retry_after}
        except Exception:
            payload = {"kind": "error", "message": "Could not load lyrics. Please retry."}
        if not self.isInterruptionRequested():
            self.result_ready.emit(self.token, payload)


class LiveLyrics(NotcherWindow):
    def __init__(self, cache_path=None):
        super().__init__("Live Lyrics", (480, 360), (420, 320))
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.music = None
        self.track = {}
        self.key = None
        self.token = 0
        self.pending = None
        self.worker = None
        self.closing = False
        self.lines = []
        self.labels = []
        self.active_index = -1
        self.following = True
        self.retry_at = 0
        directory = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        self.cache = LyricsCache(Path(cache_path) if cache_path else directory / "live-lyrics" / "cache.sqlite")
        layout = self.body_layout
        layout.setSpacing(7)
        self.track_title = QLabel("Nothing playing")
        self.track_title.setTextFormat(Qt.TextFormat.PlainText)
        self.track_title.setWordWrap(True)
        self.track_title.setMaximumHeight(44)
        self.track_title.setMinimumWidth(0)
        self.track_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.artist = QLabel()
        self.artist.setTextFormat(Qt.TextFormat.PlainText)
        self.artist.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.artist.setStyleSheet("color: #858585; font-size: 12px;")
        self.status = QLabel("Play a song to see its lyrics")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #a3a3a3; font-size: 12px;")
        layout.addWidget(self.track_title)
        layout.addWidget(self.artist)
        layout.addWidget(self.status)
        self.versions_widget = QWidget()
        versions = QHBoxLayout(self.versions_widget)
        versions.setContentsMargins(0, 0, 0, 0)
        self.versions = QComboBox()
        self.versions.setAccessibleName("Choose a matching song version")
        self.versions.setMinimumContentsLength(10)
        self.versions.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        versions.addWidget(self.versions, 1)
        use = QPushButton("Use version")
        use.clicked.connect(self.choose_version)
        versions.addWidget(use)
        layout.addWidget(self.versions_widget)
        self.versions_widget.hide()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumHeight(85)
        self.lyrics_widget = QWidget()
        self.lyrics_widget.setStyleSheet("background: transparent;")
        self.lyrics_layout = QVBoxLayout(self.lyrics_widget)
        self.lyrics_layout.setContentsMargins(0, 10, 4, 10)
        self.lyrics_layout.setSpacing(10)
        self.lyrics_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.lyrics_widget)
        self.scroll.viewport().installEventFilter(self)
        self.scroll.verticalScrollBar().installEventFilter(self)
        self.scroll.verticalScrollBar().sliderPressed.connect(self.stop_following)
        self.scroll_animation = QPropertyAnimation(self.scroll.verticalScrollBar(), b"value", self)
        self.scroll_animation.setDuration(180)
        self.scroll_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        layout.addWidget(self.scroll, 1)
        footer = QHBoxLayout()
        attribution = QLabel('<a href="https://lrclib.net/" style="color:#858585;text-decoration:none;">Lyrics by LRCLIB</a>')
        attribution.setOpenExternalLinks(True)
        attribution.setStyleSheet("font-size: 11px;")
        footer.addWidget(attribution)
        footer.addStretch()
        self.follow_button = QPushButton("Follow song")
        self.follow_button.clicked.connect(self.resume_following)
        self.follow_button.hide()
        footer.addWidget(self.follow_button)
        self.retry_button = QPushButton("Refresh")
        self.retry_button.clicked.connect(self.retry)
        self.retry_button.setEnabled(False)
        footer.addWidget(self.retry_button)
        layout.addLayout(footer)
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(100)
        self.poll_timer.timeout.connect(self.poll_music)
        self.lookup_timer = QTimer(self)
        self.lookup_timer.setSingleShot(True)
        self.lookup_timer.setInterval(300)
        self.lookup_timer.timeout.connect(self.start_pending)
        global _shutdown_connected
        if not _shutdown_connected:
            QApplication.instance().aboutToQuit.connect(_stop_workers)
            _shutdown_connected = True

    def bind_music(self, music):
        self.music = music

    def clear_lines(self):
        self.scroll_animation.stop()
        self.lines = []
        self.labels = []
        self.active_index = -1
        while self.lyrics_layout.count():
            item = self.lyrics_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        self.following = True
        self.follow_button.hide()

    def poll_music(self):
        if self.closing or self.music is None:
            return
        state = self.music.media_snapshot()
        track = {name: state.get(name, "") for name in ("title", "artist", "album", "duration")}
        key = track_key(track) if state.get("available") and track["title"] else None
        if key != self.key:
            self.key = key
            self.track = track
            self.token += 1
            self.pending = None
            self.lookup_timer.stop()
            if self.worker is not None:
                self.worker.requestInterruption()
            self.clear_lines()
            self.versions.clear()
            self.versions_widget.hide()
            self.track_title.setText(track["title"] if key else "Nothing playing")
            self.artist.setText(track["artist"] if key else "")
            if key is None:
                self.status.setText("Play a song to see its lyrics")
            else:
                cached = self.cache.get(key)
                if cached:
                    self.apply_payload(cached)
                else:
                    self.queue_lookup()
        if self.lines:
            index = bisect_right([stamp for stamp, _ in self.lines], float(state.get("position") or 0)) - 1
            self.highlight(index)
        self.retry_button.setEnabled(bool(self.key) and self.worker is None and self.pending is None and time.time() >= self.retry_at)

    def queue_lookup(self):
        if time.time() < self.retry_at:
            self.status.setText("LRCLIB is busy. Please try again later.")
            return
        self.token += 1
        self.pending = self.token, dict(self.track)
        if self.worker is not None:
            self.worker.requestInterruption()
        self.status.setText("Searching LRCLIB…")
        self.lookup_timer.start()

    def start_pending(self):
        if self.closing or self.pending is None or self.worker is not None:
            return
        token, track = self.pending
        self.pending = None
        worker = FetchWorker(token, track)
        self.worker = worker
        _workers.add(worker)
        worker.result_ready.connect(self.receive_result)
        worker.finished.connect(self.fetch_finished)
        worker.finished.connect(lambda item=worker: _release_worker(item))
        worker.start()

    def fetch_finished(self):
        self.worker = None
        if self.pending is not None and not self.closing:
            self.lookup_timer.start(0)

    def receive_result(self, token, payload):
        self.poll_music()
        if self.closing or token != self.token or self.key is None:
            return
        if payload.get("kind") != "error":
            self.store(payload)
        self.apply_payload(payload)
        self.poll_music()

    def store(self, payload):
        try:
            self.cache.put(self.key, payload)
        except (OSError, sqlite3.Error, ValueError):
            pass

    def apply_payload(self, payload):
        self.clear_lines()
        self.versions_widget.hide()
        kind = payload.get("kind")
        if kind == "error":
            self.retry_at = payload.get("retry_at", 0)
            self.status.setText(payload.get("message", "Could not load lyrics."))
            return
        if kind == "missing":
            self.status.setText("Lyrics are not available for this song yet")
            return
        if kind == "candidates":
            self.versions.clear()
            for record in payload.get("records", []):
                seconds = round(float(record.get("duration") or 0))
                text = f'{record.get("trackName", "")} · {record.get("artistName", "")} · {seconds // 60}:{seconds % 60:02d}'
                self.versions.addItem(text, record)
            self.versions_widget.show()
            self.status.setText("Choose the version that matches your song")
            return
        record = payload.get("record", {})
        if record.get("instrumental"):
            self.status.setText("Instrumental track")
            return
        self.lines = parse_lrc(record.get("syncedLyrics"))
        texts = [text for _, text in self.lines] or (record.get("plainLyrics") or "").splitlines()
        if not texts:
            self.status.setText("Lyrics are not available for this song yet")
            return
        self.status.setText("Synced lyrics" if self.lines else "Unsynced lyrics")
        for text in texts:
            label = QLabel(text)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setMinimumHeight(24)
            label.setStyleSheet("color: #858585; font-size: 15px;" if self.lines else "color: #eeeeee; font-size: 16px;")
            self.lyrics_layout.addWidget(label)
            self.labels.append(label)

    def choose_version(self):
        self.poll_music()
        record = self.versions.currentData()
        if not isinstance(record, dict):
            return
        self.token += 1
        self.pending = None
        if self.worker is not None:
            self.worker.requestInterruption()
        payload = {"kind": "lyrics", "record": record}
        self.store(payload)
        self.apply_payload(payload)
        self.poll_music()

    def highlight(self, index):
        if index == self.active_index:
            return
        self.active_index = index
        for number, label in enumerate(self.labels):
            label.setStyleSheet(
                "color: #f5f5f5; font-size: 20px; font-weight: 700;"
                if number == index else "color: #777777; font-size: 15px;"
            )
        if self.following and index >= 0:
            self.lyrics_layout.activate()
            QTimer.singleShot(0, self.center_current_line)

    def center_current_line(self):
        if self.closing or not self.following or not 0 <= self.active_index < len(self.labels):
            return
        label = self.labels[self.active_index]
        bar = self.scroll.verticalScrollBar()
        target = label.y() + label.height() // 2 - self.scroll.viewport().height() // 2
        self.scroll_animation.stop()
        self.scroll_animation.setStartValue(bar.value())
        self.scroll_animation.setEndValue(max(bar.minimum(), min(bar.maximum(), target)))
        self.scroll_animation.start()

    def stop_following(self):
        self.following = False
        self.scroll_animation.stop()
        self.follow_button.setVisible(bool(self.lines))

    def resume_following(self):
        self.following = True
        self.follow_button.hide()
        self.center_current_line()

    def retry(self):
        if self.key and self.worker is None and time.time() >= self.retry_at:
            self.queue_lookup()

    def eventFilter(self, watched, event):
        if watched in (self.scroll.viewport(), self.scroll.verticalScrollBar()) and event.type() == QEvent.Type.Wheel:
            self.stop_following()
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        self.poll_timer.start()
        self.poll_music()
        super().showEvent(event)

    def closeEvent(self, event):
        self.closing = True
        self.poll_timer.stop()
        self.lookup_timer.stop()
        self.scroll_animation.stop()
        if self.worker is not None:
            self.worker.requestInterruption()
        super().closeEvent(event)
