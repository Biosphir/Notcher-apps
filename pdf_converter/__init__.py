from shared.window import NotcherFileDialog as QFileDialog
from notcher_widgets import asset_icon
from pathlib import Path
from notcher_widgets import NoWheelComboBox
from shared.widgets import UploadDropArea, SortableFileRow
from shared.conversion import ConversionWorker
from PySide6.QtCore import Qt

from PySide6.QtGui import QPixmap



from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget, QStackedWidget, QProgressBar



class PDFConverterApp:
    def _build_file_converter_view(self):
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.setContentsMargins(0, 12, 0, 20)
        layout.setSpacing(8)

        self.converter_input_paths = []
        self.converter_detected_format = ""
        self._converter_dialog_active = False

        self.converter_files_stack = QStackedWidget()
        self.converter_files_stack.setMaximumHeight(170)

        self.converter_drop_area = UploadDropArea()
        self.converter_drop_area.setObjectName("converterDropArea")
        self.converter_drop_area.setStyleSheet("""
            QFrame#converterDropArea { background: transparent; border: 2px dashed #444444;
                border-radius: 12px; }
        """)
        self.converter_drop_area.clicked.connect(self._choose_converter_files)
        self.converter_drop_area.files_dropped.connect(self._accept_dropped_files)
        drop_layout = QVBoxLayout(self.converter_drop_area)
        drop_layout.setContentsMargins(12, 12, 12, 12)
        drop_layout.setSpacing(6)
        drop_layout.addStretch(1)
        self.converter_icon_label = QLabel()
        upload_icon = asset_icon("bg-icon-upload.png").pixmap(64, 64)
        if not upload_icon.isNull():
            self.converter_icon_label.setPixmap(upload_icon.scaled(
                48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))
        self.converter_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.converter_icon_label.setStyleSheet("border: none;")
        drop_layout.addWidget(self.converter_icon_label)
        self.converter_prompt = QLabel("Drag files here or click to choose")
        self.converter_prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.converter_prompt.setWordWrap(True)
        self.converter_prompt.setStyleSheet("color: #a3a3a3; border: none; font-size: 14px;")
        drop_layout.addWidget(self.converter_prompt)
        drop_layout.addStretch(1)
        self.converter_files_stack.addWidget(self.converter_drop_area)

        self.converter_file_list_page = QWidget()
        file_page_layout = QVBoxLayout(self.converter_file_list_page)
        file_page_layout.setContentsMargins(0, 0, 0, 0)
        file_page_layout.setSpacing(4)
        list_header = QHBoxLayout()
        self.converter_file_count = QLabel("Selected files")
        self.converter_file_count.setStyleSheet("color: #b3b3b3; border: none; font-size: 11px;")
        list_header.addWidget(self.converter_file_count, 1)
        self.converter_add_files_button = QPushButton("+ Add files")
        self.converter_add_files_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.converter_add_files_button.setStyleSheet("""
            QPushButton { background: transparent; color: #bdbdbd; border: none;
                padding: 2px 4px; font-size: 12px; }
            QPushButton:hover { color: #ffffff; }
        """)
        self.converter_add_files_button.clicked.connect(self._choose_converter_files)
        list_header.addWidget(self.converter_add_files_button, 0, Qt.AlignmentFlag.AlignRight)
        file_page_layout.addLayout(list_header)

        self.converter_file_scroll = QScrollArea()
        self.converter_file_scroll.setWidgetResizable(True)
        self.converter_file_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.converter_file_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.converter_file_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )
        self.converter_file_rows_widget = QWidget()
        self.converter_file_rows_layout = QVBoxLayout(self.converter_file_rows_widget)
        self.converter_file_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.converter_file_rows_layout.setSpacing(0)
        self.converter_file_rows_layout.addStretch(1)
        self.converter_file_scroll.setWidget(self.converter_file_rows_widget)
        file_page_layout.addWidget(self.converter_file_scroll, 1)
        self.converter_files_stack.addWidget(self.converter_file_list_page)
        layout.addWidget(self.converter_files_stack, 1)

        format_row = QHBoxLayout()
        format_row.setSpacing(10)
        self.converter_source_format = QLabel("Auto detect")
        self.converter_source_format.setMinimumHeight(36)
        self.converter_source_format.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        self.converter_source_format.setStyleSheet("""
            QLabel { background: #111111; color: #a0a0a0; border: 1px solid #333333;
                border-radius: 8px; padding: 4px 10px; font-size: 14px; }
        """)
        format_row.addWidget(self.converter_source_format, 1)
        to_label = QLabel("to")
        to_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        format_row.addWidget(to_label, 0)
        self.converter_target_format = NoWheelComboBox()
        self.converter_target_format.addItems(
            ("Choose format...", "PDF", "DOCX", "PNG", "JPG")
        )
        self.converter_target_format.setMinimumHeight(36)
        self.converter_target_format.setMaxVisibleItems(8)
        self.converter_target_format.setEnabled(False)
        self.converter_target_format.setStyleSheet("""
            QComboBox { background: #050505; color: #f5f5f5; border: 1px solid #bdbdbd;
                border-radius: 8px; padding: 4px 10px; font-size: 14px; }
            QComboBox::drop-down { border: none; width: 24px; }
            QComboBox QAbstractItemView { background: #171717; color: #f5f5f5;
                selection-background-color: #333333; }
        """)
        self.converter_target_format.currentTextChanged.connect(
            self._update_converter_button
        )
        format_row.addWidget(self.converter_target_format, 1)
        layout.addLayout(format_row)

        self.converter_status = QLabel("")
        self.converter_status.setWordWrap(True)
        self.converter_status.setStyleSheet(
            "color: #b3b3b3; border: none; font-size: 11px;"
        )
        layout.addWidget(self.converter_status)

        self.converter_progress = QProgressBar()
        self.converter_progress.setRange(0, 0)
        self.converter_progress.setTextVisible(False)
        self.converter_progress.setFixedHeight(5)
        self.converter_progress.setStyleSheet("""
            QProgressBar { background: #222222; border: none; border-radius: 2px; }
            QProgressBar::chunk { background: #7b9b8e; border-radius: 2px; }
        """)
        self.converter_progress.hide()
        layout.addWidget(self.converter_progress)

        action_row = QHBoxLayout()
        self.converter_merge_checkbox = QCheckBox("Merge into 1 file")
        self.converter_merge_checkbox.setChecked(True)
        self.converter_merge_checkbox.setStyleSheet("""
            QCheckBox { color: #f0f0f0; spacing: 8px; font-size: 14px; }
            QCheckBox::indicator { width: 18px; height: 18px; }
            QCheckBox::indicator:unchecked { border: 1px solid #555555; border-radius: 9px; }
            QCheckBox::indicator:checked { background: #353535; border: 1px solid #555555;
                border-radius: 9px; }
        """)
        self.converter_merge_checkbox.hide()
        action_row.addWidget(self.converter_merge_checkbox, 0, Qt.AlignmentFlag.AlignLeft)
        action_row.addStretch(1)
        self.converter_button = QPushButton("Convert")
        self.converter_button.setFixedHeight(30)
        self.converter_button.setEnabled(False)
        self.converter_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.converter_button.setStyleSheet("""
            QPushButton { background: #242424; color: #f5f5f5; border: none;
                border-radius: 6px; padding: 4px 14px; }
            QPushButton:disabled { color: #a3a3a3; background: #151515; }
            QPushButton:hover:!disabled { background: #353535; }
        """)
        self.converter_button.clicked.connect(self._start_file_conversion)
        action_row.addWidget(self.converter_button, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(action_row)
        return view

    def _clear_converter_selection(self, status_text=""):
        self.converter_input_paths = []
        self.converter_detected_format = ""
        self.converter_source_format.setText("Auto detect")
        self.converter_prompt.setText("Drag files here or click to choose")
        while self.converter_file_rows_layout.count():
            item = self.converter_file_rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.converter_file_rows_layout.addStretch(1)
        self.converter_files_stack.setCurrentIndex(0)
        self.converter_files_stack.setEnabled(True)
        self.converter_file_count.setText("Selected files")
        self.converter_target_format.blockSignals(True)
        self.converter_target_format.clear()
        self.converter_target_format.addItems(
            ("Choose format...", "PDF", "DOCX", "PNG", "JPG")
        )
        self.converter_target_format.setCurrentIndex(0)
        self.converter_target_format.setEnabled(False)
        self.converter_target_format.blockSignals(False)
        self.converter_merge_checkbox.setChecked(True)
        self.converter_merge_checkbox.setEnabled(True)
        self.converter_merge_checkbox.hide()
        self.converter_progress.hide()
        self.converter_button.setEnabled(False)
        self.converter_status.setText(status_text)

    def _run_converter_dialog(self, callback):
        self._converter_dialog_active = True
        self.auto_hide_timer.stop()
        try:
            return callback()
        finally:
            self._converter_dialog_active = False

    def _update_converter_button(self, _value=None):
        target = self.converter_target_format.currentText()
        show_merge = target == "PDF" and len(self.converter_input_paths) > 1
        if show_merge and not self.converter_merge_checkbox.isVisible():
            self.converter_merge_checkbox.setChecked(True)
        self.converter_merge_checkbox.setVisible(show_merge)
        self.converter_button.setEnabled(
            bool(self.converter_input_paths)
            and (
                target in ("PDF", "DOCX", "PNG", "JPG")
                or (target == "ICO" and self.converter_detected_format == "PNG")
            )
            and (target != self.converter_detected_format or show_merge)
        )

    def _choose_converter_files(self):
        filter_text = (
            "Supported files (*.pdf *.docx *.png *.jpg *.jpeg);;"
            "PDF files (*.pdf);;Word documents (*.docx);;"
            "PNG images (*.png);;JPG images (*.jpg *.jpeg)"
        )
        files, _ = self._run_converter_dialog(
            lambda: QFileDialog.getOpenFileNames(
                self, "Choose files", "", filter_text
            )
        )
        if files:
            self._accept_dropped_files(files)

    def _accept_dropped_files(self, paths):
        supported = {".pdf": "PDF", ".docx": "DOCX", ".png": "PNG",
                     ".jpg": "JPG", ".jpeg": "JPG"}
        valid = [path for path in paths if Path(path).suffix.lower() in supported]
        if not valid:
            self.converter_status.setText(
                "Use PDF, DOCX, PNG, or JPG files."
            )
            return

        detected_formats = {supported[Path(path).suffix.lower()] for path in valid}
        if self.converter_detected_format:
            detected_formats.add(self.converter_detected_format)
        if len(detected_formats) > 1:
            self.converter_status.setText(
                "Select files of the same format so their source format can be detected."
            )
            return

        existing = list(self.converter_input_paths)
        combined = existing + valid
        unique_paths = list(dict.fromkeys(combined))
        self._set_converter_files(unique_paths)

    def _set_converter_files(self, paths):
        supported = {".pdf": "PDF", ".docx": "DOCX", ".png": "PNG",
                     ".jpg": "JPG", ".jpeg": "JPG"}
        valid = [
            str(Path(path)) for path in paths
            if Path(path).suffix.lower() in supported
        ]
        if not valid:
            self.converter_status.setText(
                "Use PDF, DOCX, PNG, or JPG files."
            )
            return
        detected = supported[Path(valid[0]).suffix.lower()]
        if any(supported[Path(path).suffix.lower()] != detected for path in valid):
            self.converter_status.setText(
                "Select files of the same format so their source format can be detected."
            )
            return

        self.converter_input_paths = list(dict.fromkeys(valid))
        self.converter_detected_format = detected
        self.converter_source_format.setText(detected)
        self.converter_prompt.setText(Path(valid[0]).name)
        self.converter_file_count.setText(
            f"{len(self.converter_input_paths)} file(s) selected"
        )

        while self.converter_file_rows_layout.count():
            item = self.converter_file_rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for index, file_path in enumerate(self.converter_input_paths):
            row = SortableFileRow(file_path)
            row.setObjectName("selectedConverterFile")
            row.setFixedHeight(36)
            row.setStyleSheet("""
                QFrame#selectedConverterFile {
                    background: transparent;
                    border: none;
                    border-bottom: 1px solid #303030;
                }
            """)
            row.reorder_requested.connect(self._reorder_converter_files)
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
            remove_button = QPushButton("Ã—")
            remove_button.setAccessibleName(f"Remove {Path(file_path).name}")
            remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
            remove_button.setFixedSize(28, 28)
            remove_button.setStyleSheet("""
                QPushButton { background: transparent; color: #f0f0f0; border: none;
                    font-size: 24px; padding: 0; }
                QPushButton:hover { color: #ff7777; }
            """)
            remove_button.clicked.connect(
                lambda checked=False, row_index=index:
                    self._remove_converter_file(row_index)
            )
            row_layout.addWidget(remove_button, 0, Qt.AlignmentFlag.AlignRight)
            self.converter_file_rows_layout.addWidget(row)
        self.converter_file_rows_layout.addStretch(1)
        self.converter_files_stack.setCurrentIndex(1)

        previous_target = self.converter_target_format.currentText()
        available_targets = ["PDF", "DOCX", "PNG", "JPG"]
        if detected == "PNG":
            available_targets.remove("PNG")
            available_targets.insert(0, "ICO")
        targets = [item for item in available_targets if item != detected]
        if detected == "PDF" and len(self.converter_input_paths) > 1:
            targets.insert(0, "PDF")
        self.converter_target_format.blockSignals(True)
        self.converter_target_format.clear()
        self.converter_target_format.addItem("Choose format...")
        self.converter_target_format.addItems(targets)
        if previous_target in targets:
            self.converter_target_format.setCurrentText(previous_target)
        else:
            self.converter_target_format.setCurrentIndex(0)
        self.converter_target_format.setEnabled(True)
        self.converter_target_format.blockSignals(False)
        self.converter_status.setText(
            f"{len(self.converter_input_paths)} {detected} file(s) ready. "
            "Choose the output format, then select Convert."
        )
        self._update_converter_button()

    def _reorder_converter_files(self, source_path, target_path, place_after):
        paths = list(self.converter_input_paths)
        if source_path not in paths or target_path not in paths or source_path == target_path:
            return
        paths.remove(source_path)
        target_index = paths.index(target_path)
        if place_after:
            target_index += 1
        paths.insert(target_index, source_path)
        previous_target = self.converter_target_format.currentText()
        self._set_converter_files(paths)
        if self.converter_target_format.findText(previous_target) >= 0:
            self.converter_target_format.setCurrentText(previous_target)
        self.converter_status.setText("File order updated.")

    def _remove_converter_file(self, index):
        if index < 0 or index >= len(self.converter_input_paths):
            return
        remaining = list(self.converter_input_paths)
        del remaining[index]
        if remaining:
            self._set_converter_files(remaining)
        else:
            self._clear_converter_selection()

    def _start_file_conversion(self):
        files = list(self.converter_input_paths)
        source_format = self.converter_detected_format
        target_format = self.converter_target_format.currentText()
        if not files:
            self._choose_converter_files()
            return
        if (
            target_format not in ("PDF", "DOCX", "PNG", "JPG", "ICO")
            or (target_format == "ICO" and source_format != "PNG")
        ):
            self.converter_status.setText("Choose a supported output format.")
            return

        merge_into_one = (
            target_format == "PDF"
            and len(files) > 1
            and self.converter_merge_checkbox.isChecked()
        )
        source_path = Path(files[0])
        needs_output_folder = (
            (target_format in ("PNG", "JPG") and source_format in ("PDF", "DOCX"))
            or (len(files) > 1 and not merge_into_one and (
                target_format == "PDF"
                or (target_format == "DOCX" and source_format == "PDF")
                or (target_format in ("PNG", "JPG", "ICO")
                    and source_format in ("PNG", "JPG"))
            ))
        )
        if needs_output_folder:
            output_path = self._run_converter_dialog(
                lambda: QFileDialog.getExistingDirectory(
                    self, "Choose output folder", str(source_path.parent)
                )
            )
            if not output_path:
                return
        else:
            suffix = target_format.lower()
            suggested_name = (
                "Merged.pdf" if merge_into_one
                else source_path.with_suffix("." + suffix).name
            )
            destination = source_path.with_name(suggested_name)
            output_path, _ = self._run_converter_dialog(
                lambda: QFileDialog.getSaveFileName(
                    self, "Save converted file", str(destination),
                    f"{target_format} files (*.{suffix})"
                )
            )
            if not output_path:
                return
            output_path = str(Path(output_path).with_suffix("." + suffix))

        self.converter_button.setEnabled(False)
        self.converter_files_stack.setEnabled(False)
        self.converter_target_format.setEnabled(False)
        self.converter_merge_checkbox.setEnabled(False)
        self.converter_status.setText(
            f"Processing {len(files)} file(s)..."
        )
        self.converter_progress.show()
        self.converter_worker = ConversionWorker(
            files, source_format, target_format, output_path, merge_into_one
        )
        self.converter_worker.completed.connect(self._converter_finished)
        self.converter_worker.failed.connect(self._converter_failed)
        self.converter_worker.start()

    def _converter_finished(self, message):
        status = "Finished. " + message if self.current_view == "file_converter" else ""
        self._clear_converter_selection(status)

    def _converter_failed(self, message):
        status = "Conversion failed: " + message if self.current_view == "file_converter" else ""
        self._clear_converter_selection(status)

