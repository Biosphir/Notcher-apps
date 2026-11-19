"""Compact, synchronized lyrics for Notcher's active media session."""
from bisect import bisect_right
from pathlib import Path
import sqlite3
import time

from PySide6.QtCore import QEasingCurve, QEvent, QParallelAnimationGroup, QPropertyAnimation, QRectF, QSize, QStandardPaths, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from shared.window import NotcherWindow
from .provider import Cancelled, LyricsCache, ProviderError, lookup, parse_lrc, select_record, track_key

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


class LyricLine(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event):
        self.press_position = event.position()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and hasattr(self, "press_position")
                and (event.position() - self.press_position).manhattanLength() < 6):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class LiveLyrics(NotcherWindow):
    def __init__(self, cache_path=None):
        super().__init__("Live Lyrics", (504, 304), (444, 264))
        self.layout().setContentsMargins(18, 18, 18, 18)
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setStyleSheet(self.styleSheet() + """
            QFrame#notcherSurface {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #44304f, stop:1 #291f32);
                border: 1px solid #51405b; border-radius: 24px;
            }
            QLabel#notcherWindowTitle { font-size: 13px; font-weight: 700; color: #ddcce4; }
            QPushButton#windowControl { font-size: 12px; color: #ddcce4; }
            QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }
            QScrollBar::handle:vertical { background: #66516f; }
        """)
        for button in self.title_bar.findChildren(QPushButton):
            button.hide()
        self.is_pinned = False
        self.resize_origin = None
        self.resize_edges = Qt.Edge(0)
        self.pinned_geometry = None
        self.attached_height = self.height()
        self.pin_button = QPushButton()
        self.pin_button.setObjectName("windowControl")
        self.pin_button.setIcon(QIcon(str(Path(__file__).with_name("icon-pin.svg"))))
        self.pin_button.setIconSize(QSize(16, 16))
        self.pin_button.setCheckable(True)
        self.pin_button.setToolTip("Pin lyrics as a separate frame")
        self.pin_button.setAccessibleName("Pin lyrics")
        self.pin_button.toggled.connect(self.set_pinned)
        self.title_bar.layout().addWidget(self.pin_button)
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("windowControl")
        self.close_button.setAccessibleName("Close lyrics")
        self.close_button.clicked.connect(self.dismiss)
        self.close_button.hide()
        self.title_bar.layout().addWidget(self.close_button)
        self.title_bar.dialog = True
        self.title_bar.setCursor(Qt.CursorShape.OpenHandCursor)
        self.surface.layout().setContentsMargins(28, 18, 28, 18)
        self.surface.layout().setSpacing(10)
        self.music = None
        self.overview_visible = None
        self.overview_geometry = None
        self.dismiss_pending = False
        self.reveal_animation = QParallelAnimationGroup(self)
        self.reveal_opacity = QPropertyAnimation(self, b"windowOpacity")
        self.reveal_geometry = QPropertyAnimation(self, b"geometry")
        for animation in (self.reveal_opacity, self.reveal_geometry):
            animation.setDuration(220)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.reveal_animation.addAnimation(animation)
        self.reveal_animation.finished.connect(self.finish_reveal)
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
        self.track_title = QLabel("Nothing playing", self)
        self.track_title.setTextFormat(Qt.TextFormat.PlainText)
        self.track_title.setWordWrap(True)
        self.track_title.setMaximumHeight(44)
        self.track_title.setMinimumWidth(0)
        self.track_title.setStyleSheet("font-size: 14px; font-weight: 600; color: #f5ecf8;")
        self.artist = QLabel(self)
        self.artist.setTextFormat(Qt.TextFormat.PlainText)
        self.artist.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.artist.setStyleSheet("color: #c0aaca; font-size: 11px;")
        self.status = QLabel("Play a song to see its lyrics")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #a3a3a3; font-size: 12px;")
        self.track_title.hide()
        self.artist.hide()
        layout.addWidget(self.status)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumHeight(85)
        self.scroll.viewport().setStyleSheet("background: transparent;")
        self.lyrics_widget = QWidget()
        self.lyrics_widget.setStyleSheet("background: transparent;")
        self.lyrics_layout = QVBoxLayout(self.lyrics_widget)
        self.lyrics_layout.setContentsMargins(0, 10, 4, 10)
        self.lyrics_layout.setSpacing(12)
        self.lyrics_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.lyrics_widget)
        self.scroll.viewport().installEventFilter(self)
        self.scroll.verticalScrollBar().installEventFilter(self)
        self.scroll.verticalScrollBar().sliderPressed.connect(self.stop_following)
        self.scroll_animation = QPropertyAnimation(self.scroll.verticalScrollBar(), b"value", self)
        self.scroll_animation.setDuration(650)
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
        self._notcher_grip.setToolTip("Drag to resize lyrics")
        self._notcher_grip.hide()
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

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(self.surface.geometry()).translated(0, 3)
        for spread in range(13, 0, -1):
            painter.setPen(QPen(QColor(0, 0, 0, round(15 * (1 - spread / 14) ** 2)), 2))
            painter.drawRoundedRect(rect.adjusted(-spread, -spread, spread, spread), 24 + spread, 24 + spread)
        painter.end()
        super().paintEvent(event)

    def set_pinned(self, pinned):
        if pinned == self.is_pinned:
            return
        if pinned:
            self.attached_height = self.height()
        else:
            self.pinned_geometry = self.geometry()
        self.is_pinned = pinned
        self.pin_button.setChecked(pinned)
        self.pin_button.setToolTip("Return lyrics to Music Overview" if pinned else "Pin lyrics as a separate frame")
        self.close_button.setVisible(pinned)
        self.reveal_animation.stop()
        self.setWindowOpacity(1.0)
        self.overview_visible = None
        if pinned:
            if self.pinned_geometry is not None:
                self.setGeometry(self.pinned_geometry)
            self._notcher_grip.show()
            self.position_resize_grip()
            for widget in [self, *self.findChildren(QWidget)]:
                widget.setMouseTracking(True)
            QApplication.instance().installEventFilter(self)
            self.show()
            self.raise_()
            self.poll_timer.start()
        else:
            QApplication.instance().removeEventFilter(self)
            self.finish_resize()
            self._notcher_grip.hide()
            self.resize(self.width(), self.attached_height)

    def position_resize_grip(self):
        self._notcher_grip.move(self.width() - 42, self.height() - 42)
        self._notcher_grip.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "is_pinned") and self.is_pinned:
            self.position_resize_grip()

    def resize_edges_at(self, point):
        rect = self.surface.geometry()
        edges = Qt.Edge(0)
        if not rect.adjusted(-8, -8, 8, 8).contains(point):
            return edges
        if abs(point.x() - rect.left()) <= 8:
            edges |= Qt.Edge.LeftEdge
        elif abs(point.x() - rect.right()) <= 8:
            edges |= Qt.Edge.RightEdge
        if abs(point.y() - rect.top()) <= 8:
            edges |= Qt.Edge.TopEdge
        elif abs(point.y() - rect.bottom()) <= 8:
            edges |= Qt.Edge.BottomEdge
        return edges

    def finish_resize(self):
        if self.resize_origin is not None:
            self.releaseMouse()
        self.resize_origin = None
        self.resize_edges = Qt.Edge(0)
        self.unsetCursor()

    def handle_resize_event(self, event):
        point = self.mapFromGlobal(event.globalPosition().toPoint())
        edges = self.resize_edges if self.resize_origin is not None else self.resize_edges_at(point)
        if event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton and edges:
                self.resize_origin = self.geometry()
                self.resize_start = event.globalPosition().toPoint()
                self.resize_edges = edges
                self.grabMouse()
                return True
        elif event.type() == QEvent.Type.MouseMove:
            if self.resize_origin is not None:
                delta = event.globalPosition().toPoint() - self.resize_start
                rect = QRectF(self.resize_origin).toRect()
                if edges & Qt.Edge.LeftEdge:
                    rect.setLeft(min(rect.left() + delta.x(), rect.right() - self.minimumWidth() + 1))
                if edges & Qt.Edge.RightEdge:
                    rect.setRight(max(rect.right() + delta.x(), rect.left() + self.minimumWidth() - 1))
                if edges & Qt.Edge.TopEdge:
                    rect.setTop(min(rect.top() + delta.y(), rect.bottom() - self.minimumHeight() + 1))
                if edges & Qt.Edge.BottomEdge:
                    rect.setBottom(max(rect.bottom() + delta.y(), rect.top() + self.minimumHeight() - 1))
                self.setGeometry(rect)
                return True
            cursor = Qt.CursorShape.ArrowCursor
            if edges in (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.Edge.RightEdge | Qt.Edge.BottomEdge):
                cursor = Qt.CursorShape.SizeFDiagCursor
            elif edges in (Qt.Edge.RightEdge | Qt.Edge.TopEdge, Qt.Edge.LeftEdge | Qt.Edge.BottomEdge):
                cursor = Qt.CursorShape.SizeBDiagCursor
            elif edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
                cursor = Qt.CursorShape.SizeHorCursor
            elif edges:
                cursor = Qt.CursorShape.SizeVerCursor
            if edges:
                self.setCursor(cursor)
            else:
                self.unsetCursor()
        elif event.type() == QEvent.Type.MouseButtonRelease and self.resize_origin is not None:
            self.finish_resize()
            return True
        return False

    def set_overview_visible(self, visible, geometry=None):
        if self.closing or self.dismiss_pending or self.is_pinned:
            return
        if self.overview_visible == visible and (not visible or self.overview_geometry == geometry):
            return
        self.overview_visible = visible
        if geometry is not None:
            self.overview_geometry = geometry
        self.reveal_animation.stop()
        if visible and not self.isVisible():
            self.setGeometry(geometry.translated(0, 8))
            self.setWindowOpacity(0)
            self.show()
            self.raise_()
        if not self.isVisible():
            return
        target = self.overview_geometry or self.geometry()
        self.reveal_opacity.setStartValue(self.windowOpacity())
        self.reveal_opacity.setEndValue(1.0 if visible else 0.0)
        self.reveal_geometry.setStartValue(self.geometry())
        self.reveal_geometry.setEndValue(target if visible else target.translated(0, -6))
        self.reveal_animation.start()

    def finish_reveal(self):
        if self.dismiss_pending:
            self.close()
        elif not self.overview_visible:
            self.hide()

    def dismiss(self):
        self.is_pinned = False
        self.set_overview_visible(False)
        self.dismiss_pending = True
        if not self.isVisible():
            self.close()

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
            self.track_title.setText(track["title"] if key else "Nothing playing")
            self.artist.setText(track["artist"] if key else "")
            if key is None:
                self.status.show()
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
        self.status.show()
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
        self.status.show()
        kind = payload.get("kind")
        if kind == "candidates":
            # Resolve cached results produced by older app versions as well.
            record = select_record(self.track, payload.get("records", []))
            payload = {"kind": "lyrics", "record": record} if record else {"kind": "missing"}
            kind = payload["kind"]
        if kind == "error":
            self.retry_at = payload.get("retry_at", 0)
            self.status.setText(payload.get("message", "Could not load lyrics."))
            return
        if kind == "missing":
            self.status.setText("Lyrics are not available for this song yet")
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
        self.status.setVisible(not bool(self.lines))
        for index, text in enumerate(texts):
            label = LyricLine(text)
            if self.lines and self.music is not None and hasattr(self.music, "seek_to"):
                stamp = self.lines[index][0]
                label.setCursor(Qt.CursorShape.PointingHandCursor)
                label.setToolTip("Play from this line")
                label.clicked.connect(lambda key=self.key, seconds=stamp: self.seek_line(key, seconds))
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setMinimumHeight(36)
            label.lyric_color = "#8e749b" if self.lines else "#f5ecf8"
            label.setStyleSheet(self.line_style(label.lyric_color))
            self.lyrics_layout.addWidget(label)
            self.labels.append(label)

    def seek_line(self, key, seconds):
        self.poll_music()
        if self.key == key and self.music is not None and hasattr(self.music, "seek_to"):
            if self.music.seek_to(seconds):
                self.resume_following()
                self.poll_music()

    @staticmethod
    def line_style(color):
        return f"color: {color}; font-size: 28px; font-weight: 750; background: transparent;"

    def highlight(self, index):
        if index == self.active_index:
            return
        self.active_index = index
        for number, label in enumerate(self.labels):
            color = "#ffffff" if number == index else ("#c7afcf" if number < index else "#8e749b")
            if label.lyric_color != color:
                label.lyric_color = color
                label.setStyleSheet(self.line_style(color))
        if self.following and index >= 0:
            self.lyrics_layout.activate()
            QTimer.singleShot(0, self.center_current_line)

    def center_current_line(self):
        if self.closing or not self.following or not 0 <= self.active_index < len(self.labels):
            return
        label = self.labels[self.active_index]
        bar = self.scroll.verticalScrollBar()
        target = label.y() + label.height() // 2 - self.scroll.viewport().height() // 2
        target = max(bar.minimum(), min(bar.maximum(), target))
        if self.scroll_animation.state() == QPropertyAnimation.State.Running and self.scroll_animation.endValue() == target:
            return
        self.scroll_animation.stop()
        self.scroll_animation.setStartValue(bar.value())
        self.scroll_animation.setEndValue(target)
        self.scroll_animation.setDuration(650)
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
        if (self.is_pinned and isinstance(watched, QWidget) and watched.window() == self
                and event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove, QEvent.Type.MouseButtonRelease)):
            if self.handle_resize_event(event):
                return True
        if watched == self.scroll.viewport() and event.type() == QEvent.Type.Resize:
            padding = max(16, self.scroll.viewport().height() // 2 - 22)
            self.lyrics_layout.setContentsMargins(0, padding, 8, padding)
            if self.following:
                QTimer.singleShot(0, self.center_current_line)
        if watched in (self.scroll.viewport(), self.scroll.verticalScrollBar()) and event.type() == QEvent.Type.Wheel:
            bar = self.scroll.verticalScrollBar()
            old_target = self.scroll_animation.endValue() if self.scroll_animation.state() == QPropertyAnimation.State.Running else bar.value()
            self.stop_following()
            pixels, angle = event.pixelDelta().y(), event.angleDelta().y()
            if pixels:
                bar.setValue(bar.value() - pixels)
                return True
            if angle:
                base = old_target if (old_target - bar.value()) * (-angle) >= 0 else bar.value()
                target = max(bar.minimum(), min(bar.maximum(), round(base - angle / 120 * 100)))
                self.scroll_animation.setStartValue(bar.value())
                self.scroll_animation.setEndValue(target)
                self.scroll_animation.setDuration(360)
                self.scroll_animation.start()
                return True
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        self.poll_timer.start()
        self.poll_music()
        super().showEvent(event)
        QTimer.singleShot(0, self.center_current_line)

    def hideEvent(self, event):
        self.poll_timer.stop()
        self.scroll_animation.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.closing = True
        QApplication.instance().removeEventFilter(self)
        self.finish_resize()
        self.reveal_animation.stop()
        self.poll_timer.stop()
        self.lookup_timer.stop()
        self.scroll_animation.stop()
        if self.worker is not None:
            self.worker.requestInterruption()
        super().closeEvent(event)
