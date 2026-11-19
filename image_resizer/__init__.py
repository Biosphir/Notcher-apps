"""Resize images offline, preserving originals and writing output atomically."""
from pathlib import Path

from PySide6.QtCore import QSaveFile, QIODevice, QThread, Qt, Signal
from PySide6.QtGui import QColor, QImage, QImageReader, QImageWriter, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSpinBox
from shared.window import NotcherFileDialog, NotcherWindow


class SaveImage(QThread):
    saved = Signal(bool, str)

    def __init__(self, image, size, format_name, quality, filename, parent):
        super().__init__(parent)
        self.image, self.size = image, size
        self.format_name, self.quality, self.filename = format_name, quality, filename

    def run(self):
        output = QSaveFile(self.filename)
        try:
            image = self.image.scaled(*self.size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            if image.isNull():
                raise ValueError("Could not resize this image. Try smaller dimensions.")
            if self.format_name == "JPG":
                background = QImage(image.size(), QImage.Format.Format_RGB32)
                background.fill(QColor("white"))
                painter = QPainter(background)
                painter.drawImage(0, 0, image)
                painter.end()
                image = background
            if not output.open(QIODevice.OpenModeFlag.WriteOnly):
                raise OSError(output.errorString())
            if not image.save(output, self.format_name, self.quality):
                raise OSError("This image format could not be saved.")
            if not output.commit():
                raise OSError(output.errorString())
            self.saved.emit(True, "Saved " + Path(self.filename).name)
        except Exception as error:
            output.cancelWriting()
            self.saved.emit(False, str(error))


class ImageResizer(NotcherWindow):
    def __init__(self):
        super().__init__("Image Resizer", (590, 530), (480, 450))
        self.image = QImage()
        self.source_path = None
        self.worker = None
        QApplication.instance().aboutToQuit.connect(self.finish_pending_save)
        layout = self.body_layout
        choose = QPushButton("Choose image…")
        choose.clicked.connect(self.choose_image)
        layout.addWidget(choose)
        self.preview = QLabel("Choose an image to resize")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(130)
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.preview.setStyleSheet("background: #111111; border-radius: 10px; color: #858585;")
        layout.addWidget(self.preview, 1)
        self.info = QLabel("PNG, JPG, WebP and other formats supported by this device")
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color: #999999; font-size: 12px;")
        layout.addWidget(self.info)
        dimensions = QHBoxLayout()
        self.width_input, self.height_input = QSpinBox(), QSpinBox()
        for label, field in (("Width", self.width_input), ("Height", self.height_input)):
            dimensions.addWidget(QLabel(label))
            field.setRange(1, 16384)
            field.setSuffix(" px")
            field.setAccessibleName(label + " in pixels")
            dimensions.addWidget(field, 1)
        layout.addLayout(dimensions)
        self.keep_ratio = QCheckBox("Keep aspect ratio")
        self.keep_ratio.setChecked(True)
        self.keep_ratio.toggled.connect(lambda checked: self.dimension_changed(True) if checked else None)
        layout.addWidget(self.keep_ratio)
        options = QHBoxLayout()
        options.addWidget(QLabel("Save as"))
        self.format = QComboBox()
        supported = {bytes(value).decode().lower() for value in QImageWriter.supportedImageFormats()}
        self.format.addItems([name for name in ("PNG", "JPG", "WEBP") if name.lower() in supported or name == "JPG" and "jpeg" in supported])
        options.addWidget(self.format, 1)
        options.addWidget(QLabel("Quality"))
        self.quality = QSpinBox()
        self.quality.setRange(1, 100)
        self.quality.setValue(90)
        self.quality.setToolTip("JPG/WebP compression quality. PNG is lossless.")
        options.addWidget(self.quality)
        layout.addLayout(options)
        self.format.currentTextChanged.connect(lambda text: self.quality.setEnabled(text != "PNG"))
        self.quality.setEnabled(self.format.currentText() != "PNG")
        self.status = QLabel("Original files are kept. Transparent JPG areas become white.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #999999; font-size: 12px;")
        layout.addWidget(self.status)
        self.save_button = QPushButton("Save resized image…")
        self.save_button.setProperty("primary", True)
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_image)
        layout.addWidget(self.save_button)
        self.width_input.valueChanged.connect(lambda: self.dimension_changed(True))
        self.height_input.valueChanged.connect(lambda: self.dimension_changed(False))

    def choose_image(self):
        if self.worker is not None:
            return
        filename, _ = NotcherFileDialog.getOpenFileName(self, "Choose image", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)")
        if filename:
            self.load_image(filename)

    def load_image(self, filename):
        reader = QImageReader(filename)
        reader.setAutoTransform(True)
        size = reader.size()
        if size.width() * size.height() > 80000000 or max(size.width(), size.height()) > 16384:
            self.status.setText("Choose an image up to 80 megapixels and 16,384 pixels per side.")
            return False
        image = reader.read()
        if image.isNull():
            self.status.setText("Could not read this image: " + reader.errorString())
            return False
        self.image, self.source_path = image, Path(filename)
        for field, value in ((self.width_input, image.width()), (self.height_input, image.height())):
            field.blockSignals(True)
            field.setValue(value)
            field.blockSignals(False)
        self.info.setText(f"{self.source_path.name} · {image.width():,} × {image.height():,} px")
        self.preview.setPixmap(QPixmap.fromImage(image.scaled(470, 180, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)))
        self.status.setText("Choose the output dimensions, then save a new copy.")
        self.save_button.setEnabled(True)
        return True

    def dimension_changed(self, from_width):
        if self.image.isNull() or not self.keep_ratio.isChecked():
            return
        source, target = (self.width_input, self.height_input) if from_width else (self.height_input, self.width_input)
        ratio = self.image.height() / self.image.width() if from_width else self.image.width() / self.image.height()
        if round(source.value() * ratio) > target.maximum():
            source.blockSignals(True)
            source.setValue(max(1, int(target.maximum() / ratio)))
            source.blockSignals(False)
        target.blockSignals(True)
        target.setValue(max(1, round(source.value() * ratio)))
        target.blockSignals(False)

    def save_image(self):
        if self.worker is not None or self.image.isNull():
            return
        width, height = self.width_input.value(), self.height_input.value()
        if width * height > 80000000:
            self.status.setText("Reduce the output dimensions to 80 megapixels or less.")
            return
        format_name = self.format.currentText()
        extension = format_name.lower()
        suggested = self.source_path.with_name(f"{self.source_path.stem}-{width}x{height}.{extension}")
        filename, _ = NotcherFileDialog.getSaveFileName(self, "Save resized image", str(suggested), f"{format_name} image (*.{extension})")
        if not filename:
            return
        if not Path(filename).suffix:
            filename += "." + extension
            if Path(filename).exists():
                self.status.setText("This output already exists. Include the extension in the filename to confirm replacement, or choose another name.")
                return
        if Path(filename).resolve() == self.source_path.resolve():
            self.status.setText("Choose a different filename to keep the original image.")
            return
        self.worker = SaveImage(self.image, (width, height), format_name, self.quality.value(), filename, self)
        self.worker.saved.connect(lambda ok, message: self.status.setText(message))
        self.worker.finished.connect(self.save_finished)
        self.save_button.setEnabled(False)
        self.status.setText("Saving image…")
        self.worker.start()

    def save_finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.save_button.setEnabled(True)

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.status.setText("Finishing the image save. Please close again in a moment.")
            event.ignore()
            return
        super().closeEvent(event)

    def finish_pending_save(self):
        if self.worker is not None:
            self.worker.wait()
