"""Physical layout of the 17" MSI-style ISO keyboard with a numpad.

Positions are in key units (1u = one letter key). They drive the preview
and the spatial effects; the controller only cares about usage codes.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class KeySpec:
    code: int       # HID usage code
    label: str
    x: float
    y: float
    w: float = 1.0
    h: float = 1.0
    iso_enter: bool = False   # L-shaped: the lower row is 0.25u narrower on the left

    @property
    def center(self):
        return self.x + self.w / 2, self.y + self.h / 2


FN_ROW_HEIGHT = 0.75
NUMPAD_X = 15.5
WIDTH = 19.5
HEIGHT = FN_ROW_HEIGHT + 5


def _row(y, start_x, keys, h=1.0):
    out, x = [], start_x
    for key in keys:
        if key is None:          # gap
            x += 0.5
            continue
        code, label, *rest = key
        w = rest[0] if rest else 1.0
        out.append(KeySpec(code, label, x, y, w, h))
        x += w
    return out


def _build():
    keys = []
    top = [(0x29, "Esc")] + [(0x3A + i, f"F{i + 1}") for i in range(12)] + [
        (0x46, "PrtSc"), (0x49, "Ins"), (0x4C, "Del"), (0x4A, "Home"),
        (0x4B, "PgUp"), (0x4E, "PgDn"), (0x4D, "End")]
    step = WIDTH / len(top)
    keys += [KeySpec(code, label, i * step, 0, step, FN_ROW_HEIGHT)
             for i, (code, label) in enumerate(top)]

    y = FN_ROW_HEIGHT
    keys += _row(y, 0, [(0x35, "`")] + [(0x1E + i, str((i + 1) % 10)) for i in range(10)]
                 + [(0x2D, "-"), (0x2E, "="), (0x2A, "Backspace", 2)])
    keys += _row(y + 1, 0, [(0x2B, "Tab", 1.5)] + [(c, ch) for c, ch in zip(
        [0x14, 0x1A, 0x08, 0x15, 0x17, 0x1C, 0x18, 0x0C, 0x12, 0x13, 0x2F, 0x30], "QWERTYUIOP[]")])
    # ISO enter spans two rows.
    keys.append(KeySpec(0x28, "Enter", 13.5, y + 1, 1.5, 2, iso_enter=True))
    keys += _row(y + 2, 0, [(0x39, "Caps", 1.75)] + [(c, ch) for c, ch in zip(
        [0x04, 0x16, 0x07, 0x09, 0x0A, 0x0B, 0x0D, 0x0E, 0x0F, 0x33, 0x34, 0x32], "ASDFGHJKL;'#")])
    keys += _row(y + 3, 0, [(0xE1, "Shift", 1.25), (0x64, "\\")] + [(c, ch) for c, ch in zip(
        [0x1D, 0x1B, 0x06, 0x19, 0x05, 0x11, 0x10, 0x36, 0x37, 0x38], "ZXCVBNM,./")]
                 + [(0xE5, "Shift", 1.75), (0x52, "↑")])
    keys += _row(y + 4, 0, [(0xE0, "Ctrl", 1.25), (0xF0, "Fn"), (0xE3, "Super"), (0xE2, "Alt"),
                            (0x2C, "", 4.75), (0xE6, "AltGr"), (0x65, "Menu"), (0xE4, "Ctrl"),
                            (0x50, "←"), (0x51, "↓"), (0x4F, "→")])

    nx = NUMPAD_X
    keys += _row(y, nx, [(0x53, "Num"), (0x54, "/"), (0x55, "*"), (0x56, "-")])
    keys += _row(y + 1, nx, [(0x5F, "7"), (0x60, "8"), (0x61, "9")])
    keys.append(KeySpec(0x57, "+", nx + 3, y + 1, 1, 2))
    keys += _row(y + 2, nx, [(0x5C, "4"), (0x5D, "5"), (0x5E, "6")])
    keys += _row(y + 3, nx, [(0x59, "1"), (0x5A, "2"), (0x5B, "3")])
    keys.append(KeySpec(0x58, "Enter", nx + 3, y + 3, 1, 2))
    keys += _row(y + 4, nx, [(0x62, "0", 2), (0x63, ".")])
    return tuple(keys)


KEYS = _build()
BY_CODE = {key.code: key for key in KEYS}


def normalized_center(key):
    """Key center in 0..1 across the whole keyboard."""
    cx, cy = key.center
    return cx / WIDTH, cy / HEIGHT


# Linux evdev key codes -> HID usage codes, for keys on this layout. Lets the
# preview light up the key that was actually pressed.
EVDEV_TO_USAGE = {
    1: 0x29, 2: 0x1E, 3: 0x1F, 4: 0x20, 5: 0x21, 6: 0x22, 7: 0x23, 8: 0x24,
    9: 0x25, 10: 0x26, 11: 0x27, 12: 0x2D, 13: 0x2E, 14: 0x2A, 15: 0x2B,
    16: 0x14, 17: 0x1A, 18: 0x08, 19: 0x15, 20: 0x17, 21: 0x1C, 22: 0x18,
    23: 0x0C, 24: 0x12, 25: 0x13, 26: 0x2F, 27: 0x30, 28: 0x28, 29: 0xE0,
    30: 0x04, 31: 0x16, 32: 0x07, 33: 0x09, 34: 0x0A, 35: 0x0B, 36: 0x0D,
    37: 0x0E, 38: 0x0F, 39: 0x33, 40: 0x34, 41: 0x35, 42: 0xE1, 43: 0x32,
    44: 0x1D, 45: 0x1B, 46: 0x06, 47: 0x19, 48: 0x05, 49: 0x11, 50: 0x10,
    51: 0x36, 52: 0x37, 53: 0x38, 54: 0xE5, 55: 0x55, 56: 0xE2, 57: 0x2C,
    58: 0x39, 59: 0x3A, 60: 0x3B, 61: 0x3C, 62: 0x3D, 63: 0x3E, 64: 0x3F,
    65: 0x40, 66: 0x41, 67: 0x42, 68: 0x43, 69: 0x53, 71: 0x5F, 72: 0x60,
    73: 0x61, 74: 0x56, 75: 0x5C, 76: 0x5D, 77: 0x5E, 78: 0x57, 79: 0x59,
    80: 0x5A, 81: 0x5B, 82: 0x62, 83: 0x63, 86: 0x64, 87: 0x44, 88: 0x45,
    96: 0x58, 97: 0xE4, 98: 0x54, 99: 0x46, 100: 0xE6, 102: 0x4A, 103: 0x52,
    104: 0x4B, 105: 0x50, 106: 0x4F, 107: 0x4D, 108: 0x51, 109: 0x4E,
    110: 0x49, 111: 0x4C, 125: 0xE3, 127: 0x65,
}
