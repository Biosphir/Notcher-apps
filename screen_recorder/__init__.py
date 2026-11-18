"""Record a selected monitor using Qt's native media capture backend."""
from datetime import datetime
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QStandardPaths, QUrl, Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtMultimedia import QMediaCaptureSession, QMediaFormat, QMediaRecorder, QScreenCapture, QVideoSink
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton

from shared.window import NotcherFileDialog as QFileDialog, NotcherWindow


class ScreenRecorder(NotcherWindow):
    def __init__(self):
        super().__init__("Screen Recorder", (660, 540), (500, 440))
        layout = self.body_layout
        layout.setSpacing(12)
        layout.addWidget(QLabel("Display to record"))
        self.screens = QComboBox()
        layout.addWidget(self.screens)
        self.preview = QLabel("Choose a display, then start recording")
        self.preview.setMinimumHeight(180)
        self.preview.setStyleSheet("background: #111111; border: 1px solid #303030; border-radius: 12px; color: #858585;")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.preview, 1)
        self.elapsed = QLabel("00:00")
        self.elapsed.setStyleSheet("font-size: 28px; font-weight: 700;")
        layout.addWidget(self.elapsed)
        self.status = QLabel("Ready")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #a3a3a3;")
        layout.addWidget(self.status)
        controls = QHBoxLayout()
        self.start_button = QPushButton("Start recording")
        self.start_button.setProperty("primary", True)
        self.pause_button = QPushButton("Pause")
        self.stop_button = QPushButton("Stop and save")
        controls.addWidget(self.start_button)
        controls.addWidget(self.pause_button)
        controls.addWidget(self.stop_button)
        layout.addLayout(controls)
        self.capture = QScreenCapture(self)
        if hasattr(self.capture, "setMaximumFrameRate"):
            self.capture.setMaximumFrameRate(30)
        self.session = QMediaCaptureSession(self)
        self.recorder = QMediaRecorder(self)
        self.sink = QVideoSink(self)
        self.session.setScreenCapture(self.capture)
        self.session.setRecorder(self.recorder)
        self.session.setVideoSink(self.sink)
        self.recorder.setQuality(QMediaRecorder.Quality.HighQuality)
        self.last_preview = 0
        self.output_path = None
        self.last_error = ""
        self.recorder.durationChanged.connect(self.update_elapsed)
        self.recorder.recorderStateChanged.connect(self.update_state)
        self.recorder.errorOccurred.connect(self.recording_error)
        self.capture.errorOccurred.connect(self.recording_error)
        self.sink.videoFrameChanged.connect(self.update_preview)
        self.start_button.clicked.connect(self.start_recording)
        self.pause_button.clicked.connect(self.pause_recording)
        self.stop_button.clicked.connect(self.stop_recording)
        QGuiApplication.instance().screenAdded.connect(self.refresh_screens)
        QGuiApplication.instance().screenRemoved.connect(self.screen_removed)
        self.refresh_screens()
        self.update_state(self.recorder.recorderState())

    def refresh_screens(self, *args):
        if self.recorder.recorderState() != QMediaRecorder.RecorderState.StoppedState:
            return
        previous = self.screens.currentData()
        self.screens.clear()
        for screen in QGuiApplication.screens():
            self.screens.addItem(
                f"{screen.name()} · {screen.size().width()} × {screen.size().height()}", screen
            )
        index = self.screens.findData(previous)
        if index >= 0:
            self.screens.setCurrentIndex(index)
        self.start_button.setEnabled(self.screens.count() > 0)

    def screen_removed(self, screen):
        if self.capture.screen() is screen and self.capture.isActive():
            self.stop_recording()
            self.status.setText("Recording stopped because the selected display was disconnected.")
        self.refresh_screens()

    def start_recording(self):
        if self.recorder.recorderState() != QMediaRecorder.RecorderState.StoppedState:
            return
        screen = self.screens.currentData()
        if screen is None:
            self.status.setText("Connect a display before recording.")
            return
        media_format = QMediaFormat(QMediaFormat.FileFormat.MPEG4)
        media_format.setVideoCodec(QMediaFormat.VideoCodec.H264)
        if not media_format.isSupported(QMediaFormat.ConversionMode.Encode):
            self.status.setText("An MP4/H.264 encoder is unavailable on this PC.")
            return
        dialog = QFileDialog(self)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog)
        dialog.setNameFilter("MP4 video (*.mp4)")
        dialog.setDefaultSuffix("mp4")
        directory = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MoviesLocation)
        dialog.setDirectory(directory)
        dialog.selectFile("Screen Recording " + datetime.now().strftime("%Y-%m-%d %H%M%S") + ".mp4")
        dialog.setWindowTitle("Save recording — Notcher")
        dialog.resize(760, 520)
        if dialog.exec() != QFileDialog.DialogCode.Accepted:
            return
        self.begin_recording(screen, Path(dialog.selectedFiles()[0]), media_format)

    def begin_recording(self, screen, path, media_format):
        self.output_path = path
        self.last_error = ""
        self.update_elapsed(0)
        self.recorder.setMediaFormat(media_format)
        self.recorder.setOutputLocation(QUrl.fromLocalFile(str(path)))
        self.capture.setScreen(screen)
        self.capture.start()
        if self.capture.isActive():
            self.recorder.record()

    def pause_recording(self):
        if self.recorder.recorderState() == QMediaRecorder.RecorderState.PausedState:
            self.recorder.record()
        else:
            self.recorder.pause()

    def stop_recording(self):
        self.recorder.stop()
        self.capture.stop()

    def update_elapsed(self, milliseconds):
        seconds = milliseconds // 1000
        self.elapsed.setText(f"{seconds // 60:02d}:{seconds % 60:02d}")

    def update_state(self, state):
        stopped = state == QMediaRecorder.RecorderState.StoppedState
        paused = state == QMediaRecorder.RecorderState.PausedState
        self.screens.setEnabled(stopped)
        self.start_button.setEnabled(stopped and self.screens.count() > 0)
        self.pause_button.setEnabled(not stopped)
        self.stop_button.setEnabled(not stopped)
        self.pause_button.setText("Resume" if paused else "Pause")
        if stopped:
            self.capture.stop()
            if self.last_error:
                self.status.setText(self.last_error)
            elif self.output_path:
                self.status.setText("Saved to " + str(self.output_path))
        else:
            self.status.setText("Paused" if paused else "Recording")

    def recording_error(self, error, message):
        self.last_error = message or str(error)
        self.stop_recording()
        self.status.setText(self.last_error)

    def update_preview(self, frame):
        now = monotonic()
        if now - self.last_preview < 0.2:
            return
        self.last_preview = now
        image = frame.toImage()
        if not image.isNull():
            self.preview.setPixmap(QPixmap.fromImage(image).scaled(
                self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def closeEvent(self, event):
        self.stop_recording()
        super().closeEvent(event)
