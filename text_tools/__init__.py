"""Small, offline text transformations with undo and clipboard support."""
import re

from PySide6.QtWidgets import QApplication, QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton
from shared.window import NotcherWindow


def transform(text, operation):
    if operation == "UPPERCASE":
        return text.upper()
    if operation == "lowercase":
        return text.lower()
    if operation == "Title Case":
        return text.title()
    if operation == "Trim lines":
        return "\n".join(line.strip() for line in text.split("\n"))
    if operation == "Remove duplicate lines":
        return "\n".join(dict.fromkeys(text.split("\n")))
    if operation == "Remove blank lines":
        return "\n".join(line for line in text.split("\n") if line.strip())
    if operation == "Sort lines A–Z":
        return "\n".join(sorted(text.split("\n"), key=str.casefold))
    return text


class TextTools(NotcherWindow):
    def __init__(self):
        super().__init__("Text Tools", (640, 490), (480, 360))
        layout = self.body_layout
        hint = QLabel("Clean up text, change case, and count words. Everything stays on this device.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #999999; font-size: 12px;")
        layout.addWidget(hint)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("Type or paste text here…")
        self.editor.setAccessibleName("Text to edit")
        self.editor.textChanged.connect(self.update_counts)
        layout.addWidget(self.editor, 1)
        self.counts = QLabel()
        self.counts.setStyleSheet("color: #999999; font-size: 12px;")
        layout.addWidget(self.counts)
        actions = QHBoxLayout()
        self.operation = QComboBox()
        self.operation.setMinimumContentsLength(10)
        self.operation.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.operation.addItems(["UPPERCASE", "lowercase", "Title Case", "Trim lines", "Remove duplicate lines", "Remove blank lines", "Sort lines A–Z"])
        self.operation.setAccessibleName("Text transformation")
        actions.addWidget(self.operation, 1)
        apply = QPushButton("Apply")
        apply.setProperty("primary", True)
        apply.clicked.connect(self.apply)
        actions.addWidget(apply)
        undo = QPushButton("Undo")
        undo.clicked.connect(self.editor.undo)
        actions.addWidget(undo)
        copy = QPushButton("Copy")
        copy.clicked.connect(self.copy_all)
        actions.addWidget(copy)
        layout.addLayout(actions)
        self.update_counts()

    def update_counts(self):
        text = self.editor.toPlainText()
        words = len(re.findall(r"\S+", text))
        self.counts.setText(f"{words:,} words · {len(text):,} characters · {len(text.splitlines()) if text else 0:,} lines")

    def apply(self):
        cursor = self.editor.textCursor()
        selected = cursor.hasSelection()
        text = cursor.selectedText().replace("\u2029", "\n") if selected else self.editor.toPlainText()
        result = transform(text, self.operation.currentText())
        if result == text:
            return
        if not selected:
            cursor.select(cursor.SelectionType.Document)
        cursor.beginEditBlock()
        cursor.insertText(result)
        cursor.endEditBlock()
        self.editor.setTextCursor(cursor)

    def copy_all(self):
        QApplication.clipboard().setText(self.editor.toPlainText())
