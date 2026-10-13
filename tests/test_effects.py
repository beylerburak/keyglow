import unittest

from keyglow import effects, layout, protocol
from keyglow.settings import Settings


def _all_settings():
    for effect in effects.EFFECTS:
        for speed in (0.0, 0.5, 1.0):
            for brightness in (0.05, 0.5, 1.0):
                for direction in ("right", "in"):
                    yield Settings(effect=effect, speed=speed, brightness=brightness,
                                   direction=direction, color="#ff8000", highlight="#0040ff")


class BuildSceneTest(unittest.TestCase):
    def test_every_combination_encodes(self):
        for s in _all_settings():
            with self.subTest(settings=s):
                scene = effects.build_scene(s)
                self.assertEqual(set(scene.keys), {k.code for k in layout.KEYS})
                self.assertLessEqual(len(scene.effects), protocol.MAX_EFFECT_SLOTS)
                for slot, effect in scene.effects.items():
                    protocol.effect_packet(slot, effect)
                    self.assertLessEqual(sum(t.duration for t in effect.transitions), 0xFFFF)
                protocol.key_packets(scene.keys)

    def test_channels_stay_in_range(self):
        for s in _all_settings():
            for effect in effects.build_scene(s).effects.values():
                value = [c << 4 for c in effect.start]
                for tr in effect.transitions:
                    value = [v + sl * tr.duration for v, sl in zip(value, tr.slope)]
                    self.assertTrue(all(0 <= v <= 255 << 4 for v in value), (s, value))

    def test_keys_link_to_existing_effects(self):
        for s in _all_settings():
            scene = effects.build_scene(s)
            for key in scene.keys.values():
                if key.mode == protocol.MODE_EFFECT:
                    self.assertIn(key.effect, scene.effects)

    def test_off_is_black_and_static(self):
        scene = effects.build_scene(Settings(enabled=False, effect="rainbow"))
        self.assertFalse(scene.effects)
        self.assertTrue(all(k.color == (0, 0, 0) and k.mode == protocol.MODE_STATIC
                            for k in scene.keys.values()))

    def test_brightness_scales_static_color(self):
        scene = effects.build_scene(Settings(color="#ff8000", brightness=0.5))
        self.assertEqual(scene.keys[0x04].color, (128, 64, 0))

    def test_faster_is_shorter(self):
        def period(speed):
            scene = effects.build_scene(Settings(effect="breathing", speed=speed))
            return sum(t.duration for t in scene.effects[0].transitions)
        self.assertGreater(period(0.0), period(0.5))
        self.assertGreater(period(0.5), period(1.0))

    def test_starlight_spreads_keys(self):
        scene = effects.build_scene(Settings(effect="starlight"))
        used = {k.effect for k in scene.keys.values()}
        self.assertEqual(used, set(range(effects.STAR_SLOTS)))


class SimulatorTest(unittest.TestCase):
    def test_static(self):
        sim = effects.Simulator(effects.build_scene(Settings(color="#123456")))
        self.assertEqual(sim.color(0x04, 12.3), (0x12, 0x34, 0x56))

    def test_breathing_dims_and_returns(self):
        sim = effects.Simulator(effects.build_scene(Settings(effect="breathing", speed=1.0,
                                                            color="#ff0000")))
        start = sim.color(0x04, 0.0)
        period = sum(t.duration for t in sim.scene.effects[0].transitions) * effects.TIME_UNIT
        darkest = min(sim.color(0x04, period * i / 50)[0] for i in range(50))
        self.assertAlmostEqual(start[0], 255, delta=1)
        self.assertLess(darkest, 20)
        self.assertAlmostEqual(sim.color(0x04, period)[0], start[0], delta=1)

    def test_wave_shifts_keys(self):
        sim = effects.Simulator(effects.build_scene(Settings(effect="rainbow", direction="right")))
        self.assertNotEqual(sim.color(0x29, 1.0), sim.color(0x58, 1.0))  # Esc vs numpad Enter

    def test_reactive_flash_fades_back(self):
        s = Settings(effect="reactive", color="#000000", highlight="#ffffff", speed=0.0)
        sim = effects.Simulator(effects.build_scene(s))
        self.assertEqual(sim.color(0x04, 0, pressed_age=0.0), (255, 255, 255))
        self.assertEqual(sim.color(0x04, 0, pressed_age=10.0), (0, 0, 0))
        self.assertEqual(sim.color(0x04, 0), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
