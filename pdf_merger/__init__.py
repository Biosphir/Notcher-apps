from shared.window import NotcherFileDialog as QFileDialog
from notcher_widgets import asset_icon
from pathlib import Path
from shared.widgets import UploadDropArea, SortableFileRow
from shared.conversion import ConversionWorker
from PySide6.QtCore import Qt

from PySide6.QtGui import QPixmap



from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget, QStackedWidget, QProgressBar



class PDFMergerApp:
    def _build_pdf_merger_view(self):
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.setContentsMargins(0, 12, 0, 20)
        layout.setSpacing(8)
        self.pdf_merger_input_paths = []

        self.pdf_merger_files_stack = QStackedWidget()
        self.pdf_merger_files_stack.setMaximumHeight(170)

        self.pdf_merger_drop_area = UploadDropArea()
        self.pdf_merger_drop_area.setObjectName("pdfMergerDropArea")
        self.pdf_merger_drop_area.setStyleSheet("""
            QFrame#pdfMergerDropArea { background: transparent; border: 2px dashed #444444;
                border-radius: 12px; }
        """)
        self.pdf_merger_drop_area.clicked.connect(self._choose_pdf_merger_files)
        self.pdf_merger_drop_area.files_dropped.connect(self._accept_pdf_merger_files)
        drop_layout = QVBoxLayout(self.pdf_merger_drop_area)
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
        prompt = QLabel("Drag PDF files here or click to choose")
        prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prompt.setStyleSheet("color: #a3a3a3; border: none; font-size: 14px;")
        drop_layout.addWidget(prompt)
        drop_layout.addStretch(1)
        self.pdf_merger_files_stack.addWidget(self.pdf_merger_drop_area)

        list_page = QWidget()
        list_layout = QVBoxLayout(list_page)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(4)
        list_header = QHBoxLayout()
        self.pdf_merger_file_count = QLabel("Selected PDF files")
        self.pdf_merger_file_count.setStyleSheet(
            "color: #b3b3b3; border: none; font-size: 11px;"
        )
        list_header.addWidget(self.pdf_merger_file_count, 1)
        self.pdf_merger_add_button = QPushButton("+ Add files")
        self.pdf_merger_add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pdf_merger_add_button.setStyleSheet("""
            QPushButton { background: transparent; color: #bdbdbd; border: none;
                padding: 2px 4px; font-size: 12px; }
            QPushButton:hover { color: #ffffff; }
        """)
        self.pdf_merger_add_button.clicked.connect(self._choose_pdf_merger_files)
        list_header.addWidget(self.pdf_merger_add_button, 0, Qt.AlignmentFlag.AlignRight)
        list_layout.addLayout(list_header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        rows_widget = QWidget()
        self.pdf_merger_rows_layout = QVBoxLayout(rows_widget)
        self.pdf_merger_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.pdf_merger_rows_layout.setSpacing(0)
        self.pdf_merger_rows_layout.addStretch(1)
        scroll.setWidget(rows_widget)
        list_layout.addWidget(scroll, 1)
        self.pdf_merger_files_stack.addWidget(list_page)
        layout.addWidget(self.pdf_merger_files_stack, 1)

        self.pdf_merger_status = QLabel("Select at least two PDF files to merge.")
        self.pdf_merger_status.setWordWrap(True)
        self.pdf_merger_status.setStyleSheet(
            "color: #b3b3b3; border: none; font-size: 11px;"
        )
        layout.addWidget(self.pdf_merger_status)

        self.pdf_merger_progress = QProgressBar()
        self.pdf_merger_progress.setRange(0, 0)
        self.pdf_merger_progress.setTextVisible(False)
        self.pdf_merger_progress.setFixedHeight(5)
        self.pdf_merger_progress.setStyleSheet("""
            QProgressBar { background: #222222; border: none; border-radius: 2px; }
            QProgressBar::chunk { background: #7b9b8e; border-radius: 2px; }
        """)
        self.pdf_merger_progress.hide()
        layout.addWidget(self.pdf_merger_progress)

        self.pdf_merger_button = QPushButton("Merge PDFs")
        self.pdf_merger_button.setFixedHeight(30)
        self.pdf_merger_button.setEnabled(False)
        self.pdf_merger_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pdf_merger_button.setStyleSheet("""
            QPushButton { background: #242424; color: #f5f5f5; border: none;
                border-radius: 6px; padding: 4px 14px; }
            QPushButton:disabled { color: #a3a3a3; background: #151515; }
            QPushButton:hover:!disabled { background: #353535; }
        """)
        self.pdf_merger_button.clicked.connect(self._start_pdf_merge)
        layout.addWidget(self.pdf_merger_button, 0, Qt.AlignmentFlag.AlignRight)
        return view

    def _choose_pdf_merger_files(self):
        paths, _ = self._run_converter_dialog(
            lambda: QFileDialog.getOpenFileNames(
                self, "Choose PDF files", "", "PDF files (*.pdf)"
            )
        )
        if paths:
            self._accept_pdf_merger_files(paths)

    def _accept_pdf_merger_files(self, paths):
        valid = [str(Path(path)) for path in paths
                 if Path(path).suffix.lower() == ".pdf"]
        if not valid:
            self.pdf_merger_status.setText("Choose PDF files only.")
            return
        combined = list(dict.fromkeys(self.pdf_merger_input_paths + valid))
        self._set_pdf_merger_files(combined)

    def _set_pdf_merger_files(self, paths, status=None):
        self.pdf_merger_input_paths = list(dict.fromkeys(paths))
        while self.pdf_merger_rows_layout.count():
            item = self.pdf_merger_rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for index, file_path in enumerate(self.pdf_merger_input_paths):
            row = SortableFileRow(file_path)
            row.setObjectName("pdfMergerFileRow")
            row.setFixedHeight(36)
            row.setStyleSheet("""
                QFrame#pdfMergerFileRow { background: transparent; border: none;
                    border-bottom: 1px solid #303030; }
            """)
            row.reorder_requested.connect(self._reorder_pdf_merger_files)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(10, 0, 4, 0)
            row_layout.setSpacing(8)
            name = QLabel(Path(file_path).name)
            name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            name.setMinimumWidth(0)
            name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            name.setToolTip(file_path)
            name.setStyleSheet("color: #f0f0f0; border: none; font-size: 14px;")
            row_layout.addWidget(name, 1)
            remove = QPushButton("Ã—")
            remove.setAccessibleName(f"Remove {Path(file_path).name}")
            remove.setCursor(Qt.CursorShape.PointingHandCursor)
            remove.setFixedSize(28, 28)
            remove.setStyleSheet("""
                QPushButton { background: transparent; color: #f0f0f0; border: none;
                    font-size: 24px; padding: 0; }
                QPushButton:hover { color: #ff7777; }
            """)
            remove.clicked.connect(
                lambda checked=False, row_index=index:
                    self._remove_pdf_merger_file(row_index)
            )
            row_layout.addWidget(remove, 0, Qt.AlignmentFlag.AlignRight)
            self.pdf_merger_rows_layout.addWidget(row)
        self.pdf_merger_rows_layout.addStretch(1)

        count = len(self.pdf_merger_input_paths)
        self.pdf_merger_file_count.setText(f"{count} PDF file(s) selected")
        self.pdf_merger_files_stack.setCurrentIndex(1 if count else 0)
        self.pdf_merger_button.setEnabled(count > 1)
        if status is not None:
            self.pdf_merger_status.setText(status)
        elif count < 2:
            self.pdf_merger_status.setText("Select at least two PDF files to merge.")
        else:
            self.pdf_merger_status.setText(
                f"{count} PDF files ready. Drag rows to change their merge order."
            )

    def _remove_pdf_merger_file(self, index):
        if 0 <= index < len(self.pdf_merger_input_paths):
            paths = list(self.pdf_merger_input_paths)
            del paths[index]
            self._set_pdf_merger_files(paths)

    def _reorder_pdf_merger_files(self, source_path, target_path, place_after):
        paths = list(self.pdf_merger_input_paths)
        if source_path not in paths or target_path not in paths or source_path == target_path:
            return
        paths.remove(source_path)
        target_index = paths.index(target_path) + (1 if place_after else 0)
        paths.insert(target_index, source_path)
        self._set_pdf_merger_files(paths, "File order updated.")

    def _clear_pdf_merger(self, status="Select at least two PDF files to merge."):
        self.pdf_merger_input_paths = []
        while self.pdf_merger_rows_layout.count():
            item = self.pdf_merger_rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.pdf_merger_rows_layout.addStretch(1)
        self.pdf_merger_files_stack.setCurrentIndex(0)
        self.pdf_merger_files_stack.setEnabled(True)
        self.pdf_merger_file_count.setText("Selected PDF files")
        self.pdf_merger_progress.hide()
        self.pdf_merger_button.setEnabled(False)
        self.pdf_merger_status.setText(status)

    def _start_pdf_merge(self):
        if len(self.pdf_merger_input_paths) < 2:
            return
        first_path = Path(self.pdf_merger_input_paths[0])
        output_path, _ = self._run_converter_dialog(
            lambda: QFileDialog.getSaveFileName(
                self, "Save merged PDF", str(first_path.with_name("Merged.pdf")),
                "PDF files (*.pdf)"
            )
        )
        if not output_path:
            return
        output_path = str(Path(output_path).with_suffix(".pdf"))
        output_resolved = Path(output_path).resolve()
        if any(Path(path).resolve() == output_resolved
               for path in self.pdf_merger_input_paths):
            self.pdf_merger_status.setText(
                "Choose a new output filename so an original PDF is not overwritten."
            )
            return
        self.pdf_merger_files_stack.setEnabled(False)
        self.pdf_merger_button.setEnabled(False)
        self.pdf_merger_status.setText(
            f"Merging {len(self.pdf_merger_input_paths)} PDF files..."
        )
        self.pdf_merger_progress.show()
        self.pdf_merger_worker = ConversionWorker(
            list(self.pdf_merger_input_paths), "PDF", "PDF", output_path, True
        )
        self.pdf_merger_worker.completed.connect(self._pdf_merger_finished)
        self.pdf_merger_worker.failed.connect(self._pdf_merger_failed)
        self.pdf_merger_worker.start()

    def _pdf_merger_finished(self, message):
        self._clear_pdf_merger("Finished. " + message)

    def _pdf_merger_failed(self, message):
        self._clear_pdf_merger("Merge failed: " + message)

