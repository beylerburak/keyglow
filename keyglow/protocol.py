"""Wire protocol of the SteelSeries KLC per-key RGB controller found in MSI
laptops (and rebrands such as Monster).

The controller takes three kinds of packets:

* ``0x0e`` key packets (524-byte feature reports): colour and mode of up to
  42 keys of one region.
* ``0x0b`` effect packets (524-byte feature reports): an animation that keys
  can be linked to. The controller plays it on its own, so animations need
  no host CPU and stay smooth.
* ``0x09`` refresh packet (64-byte output report): latches everything sent
  before it. Nothing changes on the keyboard until it is sent.

Packet layouts follow the reverse engineering done by msi-perkeyrgb
(Askannz, TauAkiou) and captures of SteelSeries Engine presets.

Colours inside effects are 8.4 fixed point (value << 4). A transition holds
a per-channel slope in 1/16 colour steps per time unit, so a transition of
``d`` units changes a channel by ``slope * d / 16``.
"""
from dataclasses import dataclass, field

FEATURE_SIZE = 524
OUTPUT_SIZE = 64
KEYS_PER_PACKET = 42
MAX_TRANSITIONS = 16
MAX_EFFECT_SLOTS = 9

MODE_EFFECT = 0
MODE_STATIC = 1
MODE_REACTIVE = 8

# Region id -> HID usage codes of the keys that belong to it.
REGIONS = {
    0x2A: [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21,
           22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38,
           39, 58, 59, 60, 61, 62, 63],
    0x0B: [40, 49, 50, 100, 135, 136, 137, 138, 139, 144, 145],
    0x18: [41, 42, 43, 44, 45, 46, 47, 48, 51, 52, 53, 54, 55, 56, 57, 101,
           224, 225, 226, 227, 228, 229, 230, 240],
    0x24: [64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80,
           81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97,
           98, 99],
}
ALL_KEYS = [code for codes in REGIONS.values() for code in codes]

# Wave coordinates as seen in SteelSeries Engine captures.
WAVE_X_MAX = 0x105C
WAVE_Y_MAX = 0x040D
WAVELENGTH_MIN = 0x1F
WAVELENGTH_MAX = 0x3E9

_KEY_PACKET_TAIL = bytes(14) + b"\x08\x39"


@dataclass(frozen=True)
class Key:
    """How one key is lit."""
    color: tuple = (0, 0, 0)
    mode: int = MODE_STATIC
    effect: int = 0
    reactive_color: tuple = (0, 0, 0)
    reactive_ms: int = 0


@dataclass(frozen=True)
class Transition:
    slope: tuple      # signed per-channel slope, -128..127
    duration: int     # time units, 1..65535


@dataclass(frozen=True)
class Wave:
    """Phase-shifts an effect across the keyboard. Positions are 0..1."""
    x: float = 0.0
    y: float = 0.0
    along_x: bool = True
    along_y: bool = False
    wavelength: float = 0.5
    inward: bool = False


@dataclass(frozen=True)
class Effect:
    start: tuple
    transitions: tuple = field(default_factory=tuple)
    wave: Wave = None


def _clamp(value, low, high):
    return max(low, min(high, value))


def _u16(value):
    return int(value).to_bytes(2, "little", signed=value < 0)


def key_packet(region, keys):
    """``keys`` maps usage code -> Key for keys of ``region``."""
    if len(keys) > KEYS_PER_PACKET:
        raise ValueError("too many keys for one packet")
    packet = bytearray([0x0E, 0x00, region, 0x00])
    for code, key in keys.items():
        packet += bytes(key.color) + bytes(key.reactive_color)
        packet += _u16(key.reactive_ms)
        packet += bytes([key.effect, key.mode, 0x00, code])
    packet += bytes(12 * (KEYS_PER_PACKET - len(keys)))
    packet += _KEY_PACKET_TAIL
    assert len(packet) == FEATURE_SIZE
    return bytes(packet)


def key_packets(keys):
    """Split usage code -> Key into one packet per region (unknown codes are dropped)."""
    packets = []
    for region, codes in REGIONS.items():
        subset = {code: keys[code] for code in codes if code in keys}
        if subset:
            packets.append(key_packet(region, subset))
    return packets


def effect_packet(slot, effect):
    if not 1 <= len(effect.transitions) <= MAX_TRANSITIONS:
        raise ValueError("an effect needs 1..16 transitions")
    packet = bytearray(FEATURE_SIZE)
    packet[0] = 0x0B
    for i, tr in enumerate(effect.transitions):
        offset = 2 + i * 8
        packet[offset] = slot if i == 0 else i
        for c in range(3):
            packet[offset + 2 + c] = _clamp(tr.slope[c], -128, 127) & 0xFF
        packet[offset + 6:offset + 8] = _u16(_clamp(tr.duration, 1, 0xFFFF))
    for c in range(3):
        packet[0x84 + 2 * c:0x86 + 2 * c] = _u16(_clamp(effect.start[c], 0, 255) << 4)
    packet[0x8A] = 0xFF
    wave = effect.wave
    if wave:
        packet[0x8C:0x8E] = _u16(round(_clamp(wave.x, 0, 1) * WAVE_X_MAX))
        packet[0x8E:0x90] = _u16(round(_clamp(wave.y, 0, 1) * WAVE_Y_MAX))
        packet[0x90:0x92] = _u16(int(wave.along_x))
        packet[0x92:0x94] = _u16(int(wave.along_y))
        length = WAVELENGTH_MIN + _clamp(wave.wavelength, 0, 1) * (WAVELENGTH_MAX - WAVELENGTH_MIN)
        packet[0x94:0x96] = _u16(round(length))
        packet[0x9A] = int(wave.inward)
    packet[0x96] = len(effect.transitions)
    total = sum(tr.duration for tr in effect.transitions)
    packet[0x98:0x9A] = _u16(_clamp(total, 0, 0xFFFF))
    return bytes(packet)


def empty_effect_packet(slot):
    packet = bytearray(FEATURE_SIZE)
    packet[0] = 0x0B
    packet[2] = slot
    return bytes(packet)


def refresh_packet():
    return bytes([0x09]) + bytes(OUTPUT_SIZE - 1)


def fade(start, keyframes):
    """Build transitions that move from ``start`` through ``keyframes``.

    ``keyframes`` is a list of (color, duration). Slopes are rounded toward
    zero so a channel never overshoots 0..255 (the controller would wrap).
    Durations shorter than a full-range fade allows are stretched.
    Returns (transitions, end_color_actually_reached).
    """
    current = [c << 4 for c in start]
    transitions = []
    for color, duration in keyframes:
        target = [c << 4 for c in color]
        duration = max(1, int(duration))
        # |slope| <= 127 limits how fast a channel may change.
        need = max(abs(t - c) for t, c in zip(target, current))
        duration = max(duration, -(-need // 127))
        slope = tuple(int((t - c) / duration) for t, c in zip(target, current))
        current = [c + s * duration for c, s in zip(current, slope)]
        transitions.append(Transition(slope, duration))
    return tuple(transitions), tuple(c >> 4 for c in current)
