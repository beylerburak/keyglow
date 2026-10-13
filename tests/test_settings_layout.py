import json
import os
import tempfile
import unittest

from keyglow import layout, protocol, settings
from keyglow.settings import Settings


class SettingsTest(unittest.TestCase):
    def test_parse_color(self):
        self.assertEqual(settings.parse_color("#FF8000"), (255, 128, 0))
        self.assertEqual(settings.parse_color("00ff10"), (0, 255, 16))
        for bad in ("", "fff", "#12345g", "red"):
            with self.assertRaises(ValueError):
                settings.parse_color(bad)

    def test_validation_repairs_bad_values(self):
        s = Settings.from_dict({"effect": "nope", "color": "zzz", "speed": 7,
                                "brightness": "x", "direction": "sideways", "extra": 1})
        self.assertEqual(s.effect, Settings().effect)
        self.assertEqual(s.color, Settings().color)
        self.assertEqual(s.speed, 1.0)
        self.assertEqual(s.brightness, Settings().brightness)
        self.assertEqual(s.direction, Settings().direction)

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sub", "settings.json")
            original = Settings(effect="rainbow", color="#123abc", speed=0.25, direction="in")
            settings.save(original, path)
            self.assertEqual(settings.load(path), original)
            self.assertEqual(os.listdir(os.path.dirname(path)), ["settings.json"])

    def test_load_missing_or_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            self.assertEqual(settings.load(path), Settings())
            with open(path, "w") as f:
                f.write("{not json")
            self.assertEqual(settings.load(path), Settings())
            with open(path, "w") as f:
                json.dump(["a", "list"], f)
            self.assertEqual(settings.load(path), Settings())


class LayoutTest(unittest.TestCase):
    def test_codes_unique_and_addressable(self):
        codes = [k.code for k in layout.KEYS]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertFalse(set(codes) - set(protocol.ALL_KEYS))

    def test_inside_bounds(self):
        for k in layout.KEYS:
            self.assertGreaterEqual(k.x, 0)
            self.assertLessEqual(k.x + k.w, layout.WIDTH + 1e-9)
            self.assertLessEqual(k.y + k.h, layout.HEIGHT + 1e-9)

    def test_no_overlap(self):
        keys = [k for k in layout.KEYS if not k.iso_enter]
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                overlap = (a.x < b.x + b.w - 1e-9 and b.x < a.x + a.w - 1e-9
                           and a.y < b.y + b.h - 1e-9 and b.y < a.y + a.h - 1e-9)
                self.assertFalse(overlap, (a.label, b.label))

    def test_evdev_map_targets_layout(self):
        self.assertFalse(set(layout.EVDEV_TO_USAGE.values()) - set(layout.BY_CODE))


if __name__ == "__main__":
    unittest.main()
