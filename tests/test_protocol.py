import unittest

from keyglow import protocol
from keyglow.protocol import Effect, Key, Transition, Wave


class KeyPacketTest(unittest.TestCase):
    def test_static_key_layout(self):
        packet = protocol.key_packet(0x2A, {0x04: Key((10, 20, 30))})
        self.assertEqual(len(packet), protocol.FEATURE_SIZE)
        self.assertEqual(packet[:4], bytes([0x0E, 0x00, 0x2A, 0x00]))
        # color, reactive color, reactive time, effect, mode, 0, keycode
        self.assertEqual(packet[4:16], bytes([10, 20, 30, 0, 0, 0, 0, 0, 0, 1, 0, 0x04]))
        self.assertEqual(packet[16:28], bytes(12))
        self.assertEqual(packet[-2:], b"\x08\x39")

    def test_reactive_key(self):
        key = Key((1, 2, 3), mode=protocol.MODE_REACTIVE, reactive_color=(4, 5, 6), reactive_ms=500)
        packet = protocol.key_packet(0x2A, {0x05: key})
        self.assertEqual(packet[4:16], bytes([1, 2, 3, 4, 5, 6, 0xF4, 0x01, 0, 8, 0, 0x05]))

    def test_too_many_keys(self):
        with self.assertRaises(ValueError):
            protocol.key_packet(0x2A, {code: Key() for code in range(43)})

    def test_key_packets_split_by_region_and_drop_unknown(self):
        keys = {code: Key() for code in protocol.ALL_KEYS}
        keys[0x66] = Key()  # not addressable
        packets = protocol.key_packets(keys)
        self.assertEqual(sorted(p[2] for p in packets), sorted(protocol.REGIONS))
        self.assertTrue(all(len(code) <= protocol.KEYS_PER_PACKET for code in protocol.REGIONS.values()))

    def test_refresh(self):
        self.assertEqual(protocol.refresh_packet(), b"\x09" + bytes(63))


class EffectPacketTest(unittest.TestCase):
    # Captured from SteelSeries Engine ("freeway" preset, effect slot 1).
    CAPTURE = bytes.fromhex(
        "0b000100850000002100010000000000600002007b000000210000000000000000"
        + "00" * 99
        + "f00f00000000ff00fdff5d0201000000ef020300a20001"
    ).ljust(protocol.FEATURE_SIZE, b"\0")

    def test_matches_capture(self):
        effect = Effect(
            start=(255, 0, 0),
            transitions=(Transition((-123, 0, 0), 33), Transition((0, 0, 0), 96),
                         Transition((123, 0, 0), 33)),
        )
        packet = protocol.effect_packet(1, effect)
        # Everything but the wave block (0x8c..0x95, 0x9a) must match.
        wave = set(range(0x8C, 0x96)) | {0x9A}
        diffs = [i for i in range(protocol.FEATURE_SIZE)
                 if i not in wave and packet[i] != self.CAPTURE[i]]
        self.assertEqual(diffs, [])

    def test_wave_block(self):
        effect = Effect((0, 0, 0), (Transition((0, 0, 0), 100),),
                        Wave(x=1, y=0, along_x=True, along_y=False, wavelength=1, inward=True))
        packet = protocol.effect_packet(0, effect)
        self.assertEqual(int.from_bytes(packet[0x8C:0x8E], "little"), protocol.WAVE_X_MAX)
        self.assertEqual(packet[0x90:0x94], bytes([1, 0, 0, 0]))
        self.assertEqual(int.from_bytes(packet[0x94:0x96], "little"), protocol.WAVELENGTH_MAX)
        self.assertEqual(packet[0x9A], 1)

    def test_transition_count_limits(self):
        with self.assertRaises(ValueError):
            protocol.effect_packet(0, Effect((0, 0, 0), ()))
        with self.assertRaises(ValueError):
            protocol.effect_packet(0, Effect((0, 0, 0), (Transition((0, 0, 0), 1),) * 17))

    def test_empty_effect(self):
        packet = protocol.empty_effect_packet(3)
        self.assertEqual(packet[:3], b"\x0b\x00\x03")
        self.assertFalse(any(packet[3:]))


class FadeTest(unittest.TestCase):
    def test_full_swing_needs_33_units(self):
        transitions, end = protocol.fade((255, 0, 0), [((0, 0, 0), 1)])
        self.assertEqual(transitions[0].duration, 33)
        self.assertEqual(transitions[0].slope, (-123, 0, 0))

    def test_never_overshoots(self):
        for start, target, duration in [((255, 255, 255), (0, 0, 0), 37),
                                        ((0, 0, 0), (255, 128, 7), 999),
                                        ((17, 200, 3), (250, 1, 99), 50)]:
            transitions, end = protocol.fade(start, [(target, duration)])
            for got, want, began in zip(end, target, start):
                self.assertTrue(min(began, want) <= got <= max(began, want))

    def test_hold(self):
        transitions, end = protocol.fade((10, 20, 30), [((10, 20, 30), 500)])
        self.assertEqual(transitions[0], Transition((0, 0, 0), 500))
        self.assertEqual(end, (10, 20, 30))


if __name__ == "__main__":
    unittest.main()
