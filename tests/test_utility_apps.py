"""Offline utility checks. Run with the Notcher host checkout beside this repo."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT.parent / "Notcher"), str(ROOT.parent / "Notcher/notcher-apps")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread
from PySide6.QtGui import QColor, QImage, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from image_resizer import ImageResizer
from text_tools import TextTools, transform
from unit_converter import UnitConverter, convert


class UtilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_conversions(self):
        self.assertAlmostEqual(convert(1, "Length", "Miles", "Meters"), 1609.344)
        self.assertAlmostEqual(convert(1, "Weight", "Pounds", "Grams"), 453.59237)
        self.assertAlmostEqual(convert(32, "Temperature", "Fahrenheit", "Celsius"), 0)
        self.assertAlmostEqual(convert(0, "Temperature", "Kelvin", "Celsius"), -273.15)
        self.assertEqual(convert(1, "Data size", "KiB (1024 bytes)", "Bytes"), 1024)
        self.assertEqual(convert(1, "Area", "Hectares", "Square meters"), 10000)
        with self.assertRaises(ValueError):
            convert(-1, "Temperature", "Kelvin", "Celsius")
        window = UnitConverter()
        try:
            window.category.setCurrentText("Temperature")
            window.source.setCurrentText("Celsius")
            window.target.setCurrentText("Fahrenheit")
            window.value.setValue(100)
            self.assertEqual(window.result_text, "212")
            window.swap()
            self.assertEqual(window.source.currentText(), "Fahrenheit")
        finally:
            window.close()

    def test_text_operations_selection_and_undo(self):
        self.assertEqual(transform("b\na\nb", "Remove duplicate lines"), "b\na")
        self.assertEqual(transform("  a  \n b ", "Trim lines"), "a\nb")
        self.assertEqual(transform("a\n \nb", "Remove blank lines"), "a\nb")
        self.assertEqual(transform("z\nA\nb", "Sort lines A–Z"), "A\nb\nz")
        window = TextTools()
        try:
            window.editor.setPlainText("hello world")
            cursor = window.editor.textCursor()
            cursor.setPosition(0)
            cursor.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
            window.editor.setTextCursor(cursor)
            window.operation.setCurrentText("UPPERCASE")
            window.apply()
            self.assertEqual(window.editor.toPlainText(), "HELLO world")
            window.editor.undo()
            self.assertEqual(window.editor.toPlainText(), "hello world")
            self.assertIn("2 words", window.counts.text())
        finally:
            window.close()

    def test_resize_saves_a_copy_with_correct_dimensions_and_white_jpg(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            image = QImage(200, 100, QImage.Format.Format_ARGB32)
            image.fill(QColor(255, 0, 0, 0))
            self.assertTrue(image.save(str(source)))
            original = source.read_bytes()
            window = ImageResizer()
            try:
                self.assertTrue(window.load_image(str(source)))
                window.width_input.setValue(100)
                self.assertEqual(window.height_input.value(), 50)
                window.format.setCurrentText("JPG")
                output = Path(directory) / "small.jpg"
                with patch("image_resizer.NotcherFileDialog.getSaveFileName", return_value=(str(output), "")):
                    window.save_image()
                    deadline = time.monotonic() + 5
                    while window.worker is not None and time.monotonic() < deadline:
                        QTest.qWait(10)
                self.assertIsNone(window.worker)
                result = QImage(str(output))
                self.assertEqual((result.width(), result.height()), (100, 50))
                self.assertGreater(result.pixelColor(20, 20).red(), 245)
                self.assertGreater(result.pixelColor(20, 20).green(), 245)
                self.assertEqual(source.read_bytes(), original)
                with patch("image_resizer.NotcherFileDialog.getSaveFileName", return_value=(str(source), "")):
                    window.save_image()
                    self.assertIsNone(window.worker)
                self.assertFalse(window.load_image(str(Path(directory) / "missing.png")))
            finally:
                window.finish_pending_save()
                window.close()


if __name__ == "__main__":
    unittest.main()
