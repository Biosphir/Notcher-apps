"""A focus and break timer with monotonic deadlines."""
from math import ceil
from time import monotonic

from PySide6.QtCore import QSettings, QTimer, Signal, Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout

from shared.window import NotcherWindow


class FocusTimer(NotcherWindow):
    notification_requested = Signal(str)

    def __init__(self):
        super().__init__("Focus Timer", (510, 460), (430, 400))
        self.settings = QSettings("MartianMST", "Notcher")
        self.phase = "Focus"
        self.completed = 0
        self.running = False
        self.paused = False
        self.deadline = 0
        layout = self.body_layout
        layout.setSpacing(14)
        durations = QHBoxLayout()
        self.durations = {}
        for name, default in (("Focus", 25), ("Short break", 5), ("Long break", 15)):
            column = QVBoxLayout()
            column.addWidget(QLabel(name))
            value = QSpinBox()
            value.setRange(1, 180)
            value.setSuffix(" min")
            saved = self.settings.value("focusTimer/" + name, default, type=int)
            value.setValue(max(1, min(180, saved)))
            value.valueChanged.connect(self.duration_changed)
            self.durations[name] = value
            column.addWidget(value)
            durations.addLayout(column)
        layout.addLayout(durations)
        self.phase_label = QLabel(self.phase)
        self.phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.phase_label.setStyleSheet("color: #a3a3a3; font-size: 16px;")
        layout.addWidget(self.phase_label)
        self.time_label = QLabel()
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setStyleSheet("font-size: 64px; font-weight: 700;")
        layout.addWidget(self.time_label, 1)
        self.progress = QLabel("0 focus sessions completed")
        self.progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress.setStyleSheet("color: #858585;")
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.start_button.setProperty("primary", True)
        self.reset_button = QPushButton("Reset")
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.reset_button)
        layout.addLayout(buttons)
        self.start_button.clicked.connect(self.toggle_timer)
        self.reset_button.clicked.connect(self.reset_timer)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.tick)
        self.remaining = self.durations[self.phase].value() * 60
        self.render()

    def duration_changed(self):
        for name, field in self.durations.items():
            self.settings.setValue("focusTimer/" + name, field.value())
        self.reset_timer()

    def toggle_timer(self):
        if self.running:
            self.remaining = max(0, self.deadline - monotonic())
            if self.remaining == 0:
                self.finish_phase()
                return
            self.running = False
            self.paused = True
            self.timer.stop()
        else:
            self.running = True
            self.paused = False
            self.deadline = monotonic() + self.remaining
            self.timer.start()
        self.render()

    def tick(self):
        self.remaining = max(0, self.deadline - monotonic())
        if self.remaining == 0:
            self.finish_phase()
        else:
            self.render()

    def finish_phase(self):
        finished = self.phase
        if self.phase == "Focus":
            self.completed += 1
            self.phase = "Long break" if self.completed % 4 == 0 else "Short break"
        else:
            self.phase = "Focus"
        self.running = False
        self.paused = False
        self.timer.stop()
        self.remaining = self.durations[self.phase].value() * 60
        self.render()
        self.notification_requested.emit(f"{finished} finished. {self.phase} is ready.")
        QApplication.alert(self)

    def reset_timer(self):
        self.running = False
        self.paused = False
        self.timer.stop()
        self.remaining = self.durations[self.phase].value() * 60
        self.render()

    def render(self):
        seconds = ceil(self.remaining)
        self.time_label.setText(f"{seconds // 60:02d}:{seconds % 60:02d}")
        self.phase_label.setText(self.phase)
        word = "session" if self.completed == 1 else "sessions"
        self.progress.setText(f"{self.completed} focus {word} completed")
        if self.running:
            self.start_button.setText("Pause")
        elif self.paused:
            self.start_button.setText("Resume")
        else:
            self.start_button.setText("Start")
        for value in self.durations.values():
            value.setEnabled(not self.running)

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)
