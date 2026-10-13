"""User settings, stored as JSON in ~/.config/keyglow/settings.json."""
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, fields, replace

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "keyglow")
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")

DIRECTIONS = ("right", "left", "down", "up", "out", "in")
_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


def parse_color(value):
    """'#ff8000' or 'ff8000' -> (255, 128, 0)."""
    match = _HEX.match(str(value).strip())
    if not match:
        raise ValueError(f"Invalid color: {value!r} (expected a hex color like ff8000)")
    h = match.group(1)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def format_color(rgb):
    return "#{:02x}{:02x}{:02x}".format(*rgb)


@dataclass(frozen=True)
class Settings:
    enabled: bool = True
    effect: str = "static"
    color: str = "#00ff00"
    highlight: str = "#ffffff"
    brightness: float = 1.0
    speed: float = 0.5
    direction: str = "right"
    wave_size: float = 0.5

    def validated(self):
        from .effects import EFFECTS  # avoid an import cycle

        def unit(value, default):
            try:
                return min(1.0, max(0.0, float(value)))
            except (TypeError, ValueError):
                return default

        def color(value, default):
            try:
                return format_color(parse_color(value))
            except ValueError:
                return default

        d = Settings()
        return Settings(
            enabled=bool(self.enabled),
            effect=self.effect if self.effect in EFFECTS else d.effect,
            color=color(self.color, d.color),
            highlight=color(self.highlight, d.highlight),
            brightness=unit(self.brightness, d.brightness),
            speed=unit(self.speed, d.speed),
            direction=self.direction if self.direction in DIRECTIONS else d.direction,
            wave_size=unit(self.wave_size, d.wave_size),
        )

    def with_changes(self, **changes):
        return replace(self, **changes).validated()

    @classmethod
    def from_dict(cls, data):
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names}).validated()


def load(path=CONFIG_FILE):
    try:
        with open(path) as f:
            return Settings.from_dict(json.load(f))
    except (OSError, ValueError, TypeError, AttributeError):
        return Settings()


def save(settings, path=CONFIG_FILE):
    """Write atomically so a reader never sees a half-written file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".settings-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(asdict(settings), f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
