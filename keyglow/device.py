"""Finds the keyboard's hidraw node and sends packets to it."""
import errno
import fcntl
import glob
import os
import time

from . import protocol

VENDOR_ID = 0x1038
# SteelSeries KLC product ids. All of them speak the same protocol.
PRODUCT_IDS = {
    0x113A: "SteelSeries KLC",
    0x1122: "SteelSeries KLC (older MSI models)",
}

# The controller misbehaves when reports arrive back to back.
_REPORT_GAP = 0.005


class DeviceError(Exception):
    pass


class DeviceNotFound(DeviceError):
    pass


class DeviceAccessDenied(DeviceError):
    pass


def _hidiocsfeature(length):
    # _IOC(_IOC_WRITE | _IOC_READ, 'H', 0x06, length)
    return (3 << 30) | (length << 16) | (ord("H") << 8) | 0x06


def find():
    """Return (path, product id) of the KLC's control interface."""
    for node in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(os.path.join(node, "device", "uevent")) as f:
                uevent = dict(line.strip().split("=", 1) for line in f if "=" in line)
        except OSError:
            continue
        try:
            bus, vid, pid = (int(part, 16) for part in uevent.get("HID_ID", "").split(":"))
        except ValueError:
            continue
        if bus != 0x03 or vid != VENDOR_ID or pid not in PRODUCT_IDS:
            continue
        # Interface 0 carries the vendor-defined lighting reports; the other
        # interface is a consumer-control device.
        if os.path.realpath(os.path.join(node, "device")).split("/")[-2].endswith(":1.0"):
            return "/dev/" + os.path.basename(node), pid
    raise DeviceNotFound("No SteelSeries KLC keyboard controller found.")


class Keyboard:
    def __init__(self, path=None):
        self.path, self.product_id = (path, None) if path else find()
        try:
            self._fd = os.open(self.path, os.O_RDWR | os.O_CLOEXEC)
        except PermissionError as e:
            raise DeviceAccessDenied(
                f"No permission to open {self.path}. Install the udev rule (install.sh)."
            ) from e
        except FileNotFoundError as e:
            raise DeviceNotFound(str(e)) from e

    @property
    def name(self):
        return PRODUCT_IDS.get(self.product_id, "SteelSeries KLC")

    def close(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _call(self, fn):
        try:
            fn()
        except OSError as e:
            if e.errno in (errno.ENODEV, errno.ENXIO, errno.EIO):
                raise DeviceNotFound("The keyboard controller went away.") from e
            raise DeviceError(str(e)) from e
        time.sleep(_REPORT_GAP)

    def send_feature(self, packet):
        self._call(lambda: fcntl.ioctl(self._fd, _hidiocsfeature(len(packet)), packet))

    def send_output(self, packet):
        self._call(lambda: os.write(self._fd, packet))

    def apply(self, scene):
        """Send a full Scene (effects + keys) and latch it."""
        # Packets from two processes (a user's app and the system restore
        # service) must not interleave, so all users share one lock file.
        # A read-only descriptor is enough for flock.
        lock_dir = "/run/lock" if os.path.isdir("/run/lock") else "/tmp"
        path = os.path.join(lock_dir, "keyglow.lock")
        try:
            # Without O_CREAT: protected_regular forbids O_CREAT on another
            # user's file in a sticky directory, even for root.
            fd = os.open(path, os.O_RDONLY)
        except FileNotFoundError:
            fd = os.open(path, os.O_RDONLY | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            self._apply(scene)
        finally:
            os.close(fd)

    def _apply(self, scene):
        for slot in range(protocol.MAX_EFFECT_SLOTS):
            effect = scene.effects.get(slot)
            packet = (protocol.effect_packet(slot, effect) if effect
                      else protocol.empty_effect_packet(slot))
            self.send_feature(packet)
        for packet in protocol.key_packets(scene.keys):
            self.send_feature(packet)
        self.send_output(protocol.refresh_packet())
