"""Windows desktop input for a locally approved Share Screen session."""
import ctypes
import math
import sys
from time import monotonic
from ctypes import wintypes
from uuid import uuid4

from PySide6.QtCore import QObject, QTimer, Signal, Slot

EXTRA_INFO = ctypes.c_size_t


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_int32), ("dy", ctypes.c_int32), ("data", ctypes.c_uint32),
        ("flags", ctypes.c_uint32), ("time", ctypes.c_uint32), ("extra", EXTRA_INFO),
    ]


class KeyInput(ctypes.Structure):
    _fields_ = [
        ("vk", ctypes.c_uint16), ("scan", ctypes.c_uint16), ("flags", ctypes.c_uint32),
        ("time", ctypes.c_uint32), ("extra", EXTRA_INFO),
    ]


class InputData(ctypes.Union):
    _fields_ = [("mouse", MouseInput), ("key", KeyInput)]


class Input(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("kind", ctypes.c_uint32), ("data", InputData)]


# Set 1 scan codes preserve physical keys across the two keyboard layouts.
SCAN = {
    "Escape": 0x01, "Minus": 0x0C, "Equal": 0x0D, "Backspace": 0x0E,
    "Tab": 0x0F, "BracketLeft": 0x1A, "BracketRight": 0x1B, "Enter": 0x1C,
    "ControlLeft": 0x1D, "Semicolon": 0x27, "Quote": 0x28, "Backquote": 0x29,
    "ShiftLeft": 0x2A, "Backslash": 0x2B, "Comma": 0x33, "Period": 0x34,
    "Slash": 0x35, "ShiftRight": 0x36, "AltLeft": 0x38, "Space": 0x39,
    "CapsLock": 0x3A, "NumLock": 0x45, "ScrollLock": 0x46,
    "NumpadMultiply": 0x37, "NumpadSubtract": 0x4A, "NumpadAdd": 0x4E,
    "NumpadDecimal": 0x53, "IntlBackslash": 0x56, "F11": 0x57, "F12": 0x58,
    "ControlRight": 0xE01D, "AltRight": 0xE038, "MetaLeft": 0xE05B,
    "MetaRight": 0xE05C, "ContextMenu": 0xE05D, "Home": 0xE047,
    "ArrowUp": 0xE048, "PageUp": 0xE049, "ArrowLeft": 0xE04B,
    "ArrowRight": 0xE04D, "End": 0xE04F, "ArrowDown": 0xE050,
    "PageDown": 0xE051, "Insert": 0xE052, "Delete": 0xE053,
    "NumpadEnter": 0xE01C, "NumpadDivide": 0xE035, "PrintScreen": 0xE037,
}
for row, start in (("QWERTYUIOP", 0x10), ("ASDFGHJKL", 0x1E), ("ZXCVBNM", 0x2C)):
    SCAN.update({f"Key{letter}": start + offset for offset, letter in enumerate(row)})
SCAN.update({f"Digit{digit}": 0x02 + index for index, digit in enumerate("1234567890")})
SCAN.update({f"F{number}": 0x3A + number for number in range(1, 11)})
SCAN.update({f"Numpad{digit}": scan for digit, scan in
             enumerate((0x52, 0x4F, 0x50, 0x51, 0x4B, 0x4C, 0x4D, 0x47, 0x48, 0x49))})

BUTTONS = {0: (0x0002, 0x0004), 1: (0x0020, 0x0040), 2: (0x0008, 0x0010)}


def windows_api():
    api = ctypes.WinDLL("user32", use_last_error=True)
    api.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int)
    api.SendInput.restype = wintypes.UINT
    return api


class MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD), ("rect", wintypes.RECT), ("work", wintypes.RECT),
        ("flags", wintypes.DWORD), ("name", wintypes.WCHAR * 32),
    ]


def monitors(api):
    entries = {}
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM,
    )

    @callback_type
    def collect(monitor, _dc, _rect, _data):
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        if api.GetMonitorInfoW(monitor, ctypes.byref(info)):
            entries[info.name] = (info.rect.left, info.rect.top, info.rect.right, info.rect.bottom)
        return True

    api.EnumDisplayMonitors.argtypes = (wintypes.HDC, ctypes.POINTER(wintypes.RECT), callback_type, wintypes.LPARAM)
    api.GetMonitorInfoW.argtypes = (wintypes.HMONITOR, ctypes.POINTER(MonitorInfo))
    api.EnumDisplayMonitors(None, None, collect, 0)
    return entries


def position(x, y, target, desktop):
    if not (math.isfinite(x) and math.isfinite(y) and 0 <= x <= 1 and 0 <= y <= 1):
        return None
    left, top, right, bottom = target
    origin_x, origin_y, width, height = desktop
    px = left + round(x * (right - left - 1))
    py = top + round(y * (bottom - top - 1))
    return (min(65535, ((px - origin_x) * 65536 + width - 1) // width),
            min(65535, ((py - origin_y) * 65536 + height - 1) // height))


class RemoteInput(QObject):
    availability_changed = Signal(bool)
    permission_changed = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.api = windows_api() if sys.platform == "win32" else None
        self.display_source = False
        self.ready = False
        self.target = None
        self.grant_id = ""
        self.check_displays_at = 0
        self.keys = set()
        self.buttons = set()
        self.lease = QTimer(self, singleShot=True, interval=3500)
        self.lease.timeout.connect(self.revoke)
        self.watch = QTimer(self, interval=50)
        self.watch.timeout.connect(self.check_local_stop)

    def set_display_source(self, display):
        self.revoke()
        self.display_source = display
        self.availability_changed.emit(self.available)

    @property
    def available(self):
        return bool(self.api and self.display_source and self.ready)

    @Slot(bool)
    def peer_ready(self, ready):
        self.ready = ready
        if not ready:
            self.revoke()
        self.availability_changed.emit(self.available)

    def grant(self, display):
        if not self.available:
            return
        entries = monitors(self.api)
        if display not in entries:
            return
        self.target = (display, entries[display])
        self.grant_id = str(uuid4())
        self.lease.start()
        self.watch.start()
        self.permission_changed.emit(self.grant_id)

    def revoke(self):
        if self.target is None:
            return
        self.release()
        self.target = None
        self.grant_id = ""
        self.lease.stop()
        self.watch.stop()
        self.permission_changed.emit("")

    def check_local_stop(self):
        if self.target is None:
            return
        # Ctrl+Alt+Shift+F12 works while a different Windows app has focus.
        pressed = all(self.api.GetAsyncKeyState(key) & 0x8000 for key in (0x11, 0x12, 0x10, 0x7B))
        if pressed:
            self.revoke()
            return
        now = monotonic()
        if now >= self.check_displays_at:
            self.check_displays_at = now + 0.25
            name, rect = self.target
            if monitors(self.api).get(name) != rect:
                self.revoke()

    def send(self, *events):
        batch = (Input * len(events))(*events)
        return self.api.SendInput(len(events), batch, ctypes.sizeof(Input))

    @staticmethod
    def mouse(flags, data=0, dx=0, dy=0):
        return Input(kind=0, mouse=MouseInput(dx, dy, data, flags, 0, 0))

    @staticmethod
    def key(code, up):
        flags = 0x0008 | (0x0001 if code & 0xE000 else 0) | (0x0002 if up else 0)
        return Input(kind=1, key=KeyInput(0, code & 0xFF, flags, 0, 0))

    def release(self):
        events = [self.key(key, True) for key in self.keys]
        events += [self.mouse(BUTTONS[button][1]) for button in self.buttons]
        if events:
            self.send(*events)
        self.keys.clear()
        self.buttons.clear()

    def authorized(self, grant_id):
        return self.target is not None and self.grant_id == grant_id

    @Slot(str)
    def heartbeat(self, grant_id):
        if self.authorized(grant_id):
            self.lease.start()

    @Slot(str)
    def release_input(self, grant_id):
        if self.authorized(grant_id):
            self.release()

    @Slot(str, str, bool)
    def keyboard(self, grant_id, code, down):
        scan = SCAN.get(code)
        if not self.authorized(grant_id) or scan is None or (not down and scan not in self.keys):
            return
        if self.send(self.key(scan, not down)) == 1:
            if down:
                self.keys.add(scan)
            else:
                self.keys.discard(scan)

    @Slot(str, str, float, float, int)
    def pointer(self, grant_id, action, x, y, value):
        if not self.authorized(grant_id):
            return
        desktop = tuple(self.api.GetSystemMetrics(metric) for metric in (76, 77, 78, 79))
        if desktop[2] < 1 or desktop[3] < 1:
            return
        coords = position(x, y, self.target[1], desktop)
        if coords is None:
            return
        move = self.mouse(0xC001, dx=coords[0], dy=coords[1])
        if action == "move":
            self.send(move)
        elif action in ("down", "up") and value in BUTTONS:
            if action == "up" and value not in self.buttons:
                return
            if self.send(move, self.mouse(BUTTONS[value][action == "up"])) == 2:
                if action == "down":
                    self.buttons.add(value)
                else:
                    self.buttons.discard(value)
        elif action in ("wheel", "horizontal") and -1200 <= value <= 1200:
            self.send(move, self.mouse(0x0800 if action == "wheel" else 0x1000, value))
