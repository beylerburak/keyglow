"""Turns Settings into a hardware Scene, and simulates a Scene for the preview.

Every animation runs on the keyboard controller itself, so nothing has to
stay running on the computer once a scene is sent.
"""
import math
import random
from dataclasses import dataclass, field

from . import layout, protocol
from .protocol import Effect, Key, Wave, fade
from .settings import parse_color

TIME_UNIT = 0.01        # seconds per effect time unit (verified on hardware)
REACTIVE_UNIT = 0.001   # seconds per reactive duration unit
BLACK = (0, 0, 0)
STAR_SLOTS = 8


@dataclass(frozen=True)
class EffectInfo:
    id: str
    name: str
    description: str
    uses_color: bool = True
    uses_highlight: bool = False
    uses_speed: bool = True
    uses_direction: bool = False


EFFECTS = {e.id: e for e in (
    EffectInfo("static", "Static", "One steady color", uses_speed=False),
    EffectInfo("breathing", "Breathing", "Slowly fades in and out"),
    EffectInfo("spectrum", "Color Cycle", "All keys cycle through the rainbow", uses_color=False),
    EffectInfo("rainbow", "Rainbow Wave", "A rainbow that flows across the keys",
               uses_color=False, uses_direction=True),
    EffectInfo("wave", "Color Wave", "Pulses of color sweeping across the keys", uses_direction=True),
    EffectInfo("starlight", "Starlight", "Keys twinkle at random"),
    EffectInfo("reactive", "Reactive", "Keys light up as you type", uses_highlight=True),
)}


@dataclass
class Scene:
    effects: dict = field(default_factory=dict)   # slot -> Effect
    keys: dict = field(default_factory=dict)      # usage code -> Key

    @property
    def animated(self):
        return bool(self.effects)


def _scaled(rgb, brightness):
    return tuple(round(c * brightness) for c in rgb)


def _period(speed, slow, fast):
    """Seconds per cycle; speed 0..1 maps logarithmically from slow to fast."""
    return slow * (fast / slow) ** speed


def _units(seconds):
    return max(1, round(seconds / TIME_UNIT))


_WAVE_ORIGINS = {
    "right": dict(x=0.0, y=0.5, along_x=True, along_y=False),
    "left": dict(x=1.0, y=0.5, along_x=True, along_y=False),
    "down": dict(x=0.5, y=0.0, along_x=False, along_y=True),
    "up": dict(x=0.5, y=1.0, along_x=False, along_y=True),
    "out": dict(x=0.5, y=0.5, along_x=True, along_y=True),
    "in": dict(x=0.5, y=0.5, along_x=True, along_y=True, inward=True),
}


def _wave(settings):
    return Wave(wavelength=settings.wave_size, **_WAVE_ORIGINS[settings.direction])


def _all_keys(**kwargs):
    return {key.code: Key(**kwargs) for key in layout.KEYS}


def _rainbow(brightness, period):
    hues = [(255, 0, 0), (255, 255, 0), (0, 255, 0), (0, 255, 255),
            (0, 0, 255), (255, 0, 255), (255, 0, 0)]
    hues = [_scaled(h, brightness) for h in hues]
    step = _units(period / 6)
    transitions, _ = fade(hues[0], [(h, step) for h in hues[1:]])
    return Effect(hues[0], transitions)


def build_scene(settings):
    s = settings
    if not s.enabled:
        return Scene(keys=_all_keys(color=BLACK))
    color = _scaled(parse_color(s.color), s.brightness)

    if s.effect == "static":
        return Scene(keys=_all_keys(color=color))

    if s.effect == "reactive":
        highlight = _scaled(parse_color(s.highlight), s.brightness)
        fade_s = _period(s.speed, 1.5, 0.15)
        return Scene(keys=_all_keys(color=color, mode=protocol.MODE_REACTIVE,
                                    reactive_color=highlight,
                                    reactive_ms=round(fade_s / REACTIVE_UNIT)))

    linked = _all_keys(mode=protocol.MODE_EFFECT, effect=0)

    if s.effect == "breathing":
        p = _period(s.speed, 8.0, 1.2)
        transitions, _ = fade(color, [(BLACK, _units(p * 0.45)), (color, _units(p * 0.45)),
                                      (color, _units(p * 0.10))])
        return Scene({0: Effect(color, transitions)}, linked)

    if s.effect == "spectrum":
        return Scene({0: _rainbow(s.brightness, _period(s.speed, 30.0, 2.0))}, linked)

    if s.effect == "rainbow":
        effect = _rainbow(s.brightness, _period(s.speed, 12.0, 1.5))
        return Scene({0: Effect(effect.start, effect.transitions, _wave(s))}, linked)

    if s.effect == "wave":
        p = _period(s.speed, 6.0, 1.0)
        transitions, _ = fade(color, [(BLACK, _units(p * 0.4)), (BLACK, _units(p * 0.2)),
                                      (color, _units(p * 0.4))])
        return Scene({0: Effect(color, transitions, _wave(s))}, linked)

    if s.effect == "starlight":
        p = _period(s.speed, 6.0, 1.0)
        rise, fall = p * 0.12, p * 0.28
        effects = {}
        for slot in range(STAR_SLOTS):
            offset = slot * (p - rise - fall) / (STAR_SLOTS - 1)
            frames = [(BLACK, _units(offset))] if offset >= TIME_UNIT else []
            frames += [(color, _units(rise)), (BLACK, _units(fall))]
            rest = p - offset - rise - fall
            if rest >= TIME_UNIT:
                frames.append((BLACK, _units(rest)))
            transitions, _ = fade(BLACK, frames)
            effects[slot] = Effect(BLACK, transitions)
        # Stable pseudo-random spread of keys over the slots.
        codes = [key.code for key in layout.KEYS]
        random.Random(7).shuffle(codes)
        keys = {code: Key(mode=protocol.MODE_EFFECT, effect=i % STAR_SLOTS)
                for i, code in enumerate(codes)}
        return Scene(effects, keys)

    raise ValueError(f"unknown effect {s.effect!r}")


class Simulator:
    """Approximates what the controller shows, for the on-screen preview."""

    def __init__(self, scene):
        self.scene = scene
        self._effects = {slot: self._compile(e) for slot, e in scene.effects.items()}
        self._delays = {}
        for key in layout.KEYS:
            k = scene.keys.get(key.code)
            if k and k.mode == protocol.MODE_EFFECT and k.effect in scene.effects:
                self._delays[key.code] = self._delay(key, scene.effects[k.effect])

    @staticmethod
    def _compile(effect):
        segments, t, value = [], 0, [c << 4 for c in effect.start]
        for tr in effect.transitions:
            segments.append((t, tr.duration, tuple(value), tr.slope))
            value = [v + s * tr.duration for v, s in zip(value, tr.slope)]
            t += tr.duration
        return segments, max(t, 1)

    @staticmethod
    def _delay(key, effect):
        """Time units by which this key lags behind the wave origin."""
        wave = effect.wave
        if not wave or not (wave.along_x or wave.along_y):
            return 0.0
        kx, ky = layout.normalized_center(key)
        dx = (kx - wave.x) * protocol.WAVE_X_MAX if wave.along_x else 0.0
        dy = (ky - wave.y) * protocol.WAVE_Y_MAX if wave.along_y else 0.0
        length = protocol.WAVELENGTH_MIN + wave.wavelength * (
            protocol.WAVELENGTH_MAX - protocol.WAVELENGTH_MIN)
        total = sum(tr.duration for tr in effect.transitions)
        # The controller's exact distance scaling is unknown; this factor
        # makes the preview show roughly as many waves as the keyboard does.
        phase = math.hypot(dx, dy) / (length * 4)
        return (-phase if wave.inward else phase) * total

    def _effect_color(self, slot, units):
        segments, total = self._effects[slot]
        u = units % total
        for t0, duration, value, slope in segments:
            if u < t0 + duration:
                return tuple(max(0, min(255, (v + s * (u - t0)) / 16)) for v, s in zip(value, slope))
        return tuple(max(0, min(255, v / 16)) for v in segments[-1][2])

    def color(self, code, seconds, pressed_age=None):
        """RGB 0..255 floats of a key at a given time. ``pressed_age`` is the
        number of seconds since the key was last pressed, for reactive keys."""
        key = self.scene.keys.get(code)
        if key is None:
            return BLACK
        if key.mode == protocol.MODE_EFFECT and key.effect in self._effects:
            return self._effect_color(key.effect, seconds / TIME_UNIT - self._delays.get(code, 0.0))
        if key.mode == protocol.MODE_REACTIVE and pressed_age is not None:
            length = key.reactive_ms * REACTIVE_UNIT
            if pressed_age < length:
                mix = pressed_age / length
                return tuple(h + (c - h) * mix for h, c in zip(key.reactive_color, key.color))
        return key.color
