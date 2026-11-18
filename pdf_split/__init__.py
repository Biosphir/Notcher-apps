from notcher_widgets import asset_icon
from pathlib import Path
from shared.widgets import UploadDropArea
from PySide6.QtCore import Qt

from PySide6.QtGui import QPixmap



from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget, QStackedWidget, QFileDialog, QProgressBar

from .worker import PDFSplitWorker


class PDFSplitApp:
    def _build_pdf_split_view(self):
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.setContentsMargins(0, 12, 0, 20)
        layout.setSpacing(8)
        self.pdf_split_input_path = None

        self.pdf_split_files_stack = QStackedWidget()
        self.pdf_split_files_stack.setMaximumHeight(170)

        self.pdf_split_drop_area = UploadDropArea()
        self.pdf_split_drop_area.setObjectName("pdfSplitDropArea")
        self.pdf_split_drop_area.setStyleSheet("""
            QFrame#pdfSplitDropArea { background: transparent; border: 2px dashed #444444;
                border-radius: 12px; }
        """)
        self.pdf_split_drop_area.clicked.connect(self._choose_pdf_split_file)
        self.pdf_split_drop_area.files_dropped.connect(self._accept_pdf_split_files)
        drop_layout = QVBoxLayout(self.pdf_split_drop_area)
        drop_layout.setContentsMargins(12, 12, 12, 12)
        drop_layout.setSpacing(6)
        drop_layout.addStretch(1)
        icon = QLabel()
        upload_icon = asset_icon("bg-icon-upload.png").pixmap(64, 64)
        if not upload_icon.isNull():
            icon.setPixmap(upload_icon.scaled(
                48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("border: none;")
        drop_layout.addWidget(icon)
        prompt = QLabel("Drag one PDF here or click to choose")
        prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prompt.setStyleSheet("color: #a3a3a3; border: none; font-size: 14px;")
        drop_layout.addWidget(prompt)
        drop_layout.addStretch(1)
        self.pdf_split_files_stack.addWidget(self.pdf_split_drop_area)

        selected_page = QWidget()
        selected_layout = QHBoxLayout(selected_page)
        selected_layout.setContentsMargins(10, 0, 4, 0)
        selected_layout.setSpacing(8)
        selected_page.setStyleSheet(
            "QWidget { background: transparent; border-bottom: 1px solid #303030; }"
        )
        self.pdf_split_file_label = QLabel("")
        self.pdf_split_file_label.setMinimumWidth(0)
        self.pdf_split_file_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.pdf_split_file_label.setStyleSheet(
            "color: #f0f0f0; border: none; font-size: 14px;"
        )
        selected_layout.addWidget(self.pdf_split_file_label, 1)
        remove_button = QPushButton("Ã—")
        remove_button.setAccessibleName("Remove selected PDF")
        remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_button.setFixedSize(28, 28)
        remove_button.setStyleSheet("""
            QPushButton { background: transparent; color: #f0f0f0; border: none;
                font-size: 24px; padding: 0; }
            QPushButton:hover { color: #ff7777; }
        """)
        remove_button.clicked.connect(lambda: self._clear_pdf_split())
        selected_layout.addWidget(remove_button, 0, Qt.AlignmentFlag.AlignRight)
        self.pdf_split_files_stack.addWidget(selected_page)
        layout.addWidget(self.pdf_split_files_stack, 1)

        self.pdf_split_status = QLabel("Each page will be saved as a separate PDF.")
        self.pdf_split_status.setWordWrap(True)
        self.pdf_split_status.setStyleSheet(
            "color: #b3b3b3; border: none; font-size: 11px;"
        )
        layout.addWidget(self.pdf_split_status)

        self.pdf_split_progress = QProgressBar()
        self.pdf_split_progress.setRange(0, 0)
        self.pdf_split_progress.setTextVisible(False)
        self.pdf_split_progress.setFixedHeight(5)
        self.pdf_split_progress.setStyleSheet("""
            QProgressBar { background: #222222; border: none; border-radius: 2px; }
            QProgressBar::chunk { background: #7b9b8e; border-radius: 2px; }
        """)
        self.pdf_split_progress.hide()
        layout.addWidget(self.pdf_split_progress)

        self.pdf_split_button = QPushButton("Split PDF")
        self.pdf_split_button.setFixedHeight(30)
        self.pdf_split_button.setEnabled(False)
        self.pdf_split_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pdf_split_button.setStyleSheet("""
            QPushButton { background: #242424; color: #f5f5f5; border: none;
                border-radius: 6px; padding: 4px 14px; }
            QPushButton:disabled { color: #a3a3a3; background: #151515; }
            QPushButton:hover:!disabled { background: #353535; }
        """)
        self.pdf_split_button.clicked.connect(self._start_pdf_split)
        layout.addWidget(self.pdf_split_button, 0, Qt.AlignmentFlag.AlignRight)
        return view

    def _choose_pdf_split_file(self):
        path, _ = self._run_converter_dialog(
            lambda: QFileDialog.getOpenFileName(
                self, "Choose a PDF file", "", "PDF files (*.pdf)"
            )
        )
        if path:
            self._accept_pdf_split_files([path])

    def _accept_pdf_split_files(self, paths):
        valid = [str(Path(path)) for path in paths
                 if Path(path).suffix.lower() == ".pdf"]
        if not valid:
            self.pdf_split_status.setText("Choose a PDF file only.")
            return
        self.pdf_split_input_path = valid[0]
        self.pdf_split_file_label.setText(Path(valid[0]).name)
        self.pdf_split_file_label.setToolTip(valid[0])
        self.pdf_split_files_stack.setCurrentIndex(1)
        self.pdf_split_button.setEnabled(True)
        self.pdf_split_status.setText("Ready to split every page into a separate PDF.")

    def _clear_pdf_split(self, status="Each page will be saved as a separate PDF."):
        self.pdf_split_input_path = None
        self.pdf_split_file_label.clear()
        self.pdf_split_file_label.setToolTip("")
        self.pdf_split_files_stack.setCurrentIndex(0)
        self.pdf_split_files_stack.setEnabled(True)
        self.pdf_split_progress.hide()
        self.pdf_split_button.setEnabled(False)
        self.pdf_split_status.setText(status)

    def _start_pdf_split(self):
        if not self.pdf_split_input_path:
            return
        source_path = Path(self.pdf_split_input_path)
        output_dir = self._run_converter_dialog(
            lambda: QFileDialog.getExistingDirectory(
                self, "Choose output folder", str(source_path.parent)
            )
        )
        if not output_dir:
            return
        self.pdf_split_button.setEnabled(False)
        self.pdf_split_files_stack.setEnabled(False)
        self.pdf_split_status.setText(f"Splitting pages from {source_path.name}...")
        self.pdf_split_progress.show()
        self.pdf_split_worker = PDFSplitWorker(str(source_path), output_dir)
        self.pdf_split_worker.completed.connect(self._pdf_split_finished)
        self.pdf_split_worker.failed.connect(self._pdf_split_failed)
        self.pdf_split_worker.start()

    def _pdf_split_finished(self, message):
        self._clear_pdf_split("Finished. " + message)

    def _pdf_split_failed(self, message):
        self._clear_pdf_split("Split failed: " + message)

