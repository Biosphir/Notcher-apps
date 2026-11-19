"""Offline conversions using base-unit factors and explicit temperatures."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton
from shared.window import NotcherWindow

UNITS = {
    "Length": {"Millimeters": .001, "Centimeters": .01, "Meters": 1, "Kilometers": 1000, "Inches": .0254, "Feet": .3048, "Yards": .9144, "Miles": 1609.344},
    "Weight": {"Milligrams": .000001, "Grams": .001, "Kilograms": 1, "Tonnes": 1000, "Ounces": .028349523125, "Pounds": .45359237},
    "Temperature": {"Celsius": 1, "Fahrenheit": 1, "Kelvin": 1},
    "Data size": {"Bytes": 1, "KB (1000 bytes)": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4, "KiB (1024 bytes)": 1024, "MiB": 1024**2, "GiB": 1024**3, "TiB": 1024**4},
    "Area": {"Square meters": 1, "Square kilometers": 1000000, "Hectares": 10000, "Square feet": .09290304, "Acres": 4046.8564224},
}


def convert(value, category, source, target):
    if category != "Temperature":
        return value * UNITS[category][source] / UNITS[category][target]
    celsius = (value - 32) * 5 / 9 if source == "Fahrenheit" else value - 273.15 if source == "Kelvin" else value
    if celsius < -273.150000001:
        raise ValueError("Temperature cannot be below absolute zero.")
    return celsius * 9 / 5 + 32 if target == "Fahrenheit" else celsius + 273.15 if target == "Kelvin" else celsius


class UnitConverter(NotcherWindow):
    def __init__(self):
        super().__init__("Unit Converter", (540, 380), (460, 340))
        layout = self.body_layout
        self.category = QComboBox()
        self.category.addItems(UNITS)
        self.category.setAccessibleName("Conversion category")
        layout.addWidget(self.category)
        self.value = QDoubleSpinBox()
        self.value.setRange(-1e12, 1e12)
        self.value.setDecimals(8)
        self.value.setValue(1)
        self.value.setAccessibleName("Value to convert")
        layout.addWidget(self.value)
        units = QHBoxLayout()
        self.source, self.target = QComboBox(), QComboBox()
        for combo in (self.source, self.target):
            combo.setMinimumContentsLength(10)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.source.setAccessibleName("From unit")
        self.target.setAccessibleName("To unit")
        units.addWidget(self.source, 1)
        swap = QPushButton("⇄")
        swap.setAccessibleName("Swap units")
        swap.clicked.connect(self.swap)
        units.addWidget(swap)
        units.addWidget(self.target, 1)
        layout.addLayout(units)
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.result.setStyleSheet("font-size: 25px; font-weight: 600;")
        layout.addWidget(self.result, 1)
        copy = QPushButton("Copy result")
        copy.clicked.connect(self.copy_result)
        layout.addWidget(copy)
        self.category.currentTextChanged.connect(self.change_category)
        self.value.valueChanged.connect(self.update_result)
        self.source.currentTextChanged.connect(self.update_result)
        self.target.currentTextChanged.connect(self.update_result)
        self.change_category()

    def change_category(self):
        names = list(UNITS[self.category.currentText()])
        for combo in (self.source, self.target):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            combo.blockSignals(False)
        self.target.setCurrentIndex(1)
        self.update_result()

    def swap(self):
        source, target = self.source.currentIndex(), self.target.currentIndex()
        self.source.setCurrentIndex(target)
        self.target.setCurrentIndex(source)

    def update_result(self, *_):
        if not self.source.currentText() or not self.target.currentText():
            return
        try:
            result = convert(self.value.value(), self.category.currentText(), self.source.currentText(), self.target.currentText())
            self.result_text = f"{result:,.12g}"
            self.result.setText(self.result_text + " " + self.target.currentText())
        except ValueError as error:
            self.result_text = ""
            self.result.setText(str(error))

    def copy_result(self):
        if self.result_text:
            QApplication.clipboard().setText(self.result_text)
