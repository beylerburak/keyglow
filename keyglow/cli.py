"""Command-line interface: ``keyglow --help``."""
import argparse
import os
import pwd
import sys
import time

from . import APP_NAME, __version__, device, settings as settings_mod
from .effects import EFFECTS, build_scene
from .settings import DIRECTIONS, parse_color


def _percent(text):
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}")
    if not 0 <= value <= 100:
        raise argparse.ArgumentTypeError("must be between 0 and 100")
    return value / 100


def _color(text):
    try:
        parse_color(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))
    return text


def apply(current, quiet=False, wait=0.0):
    """Send settings to the keyboard. ``wait`` seconds are spent retrying while
    the controller is not there yet (right after boot or resume)."""
    deadline = time.monotonic() + wait
    while True:
        try:
            with device.Keyboard() as kb:
                kb.apply(build_scene(current))
            break
        except device.DeviceNotFound as e:
            if time.monotonic() >= deadline:
                print(f"{APP_NAME}: {e}", file=sys.stderr)
                return 1
            time.sleep(0.5)
        except device.DeviceError as e:
            print(f"{APP_NAME}: {e}", file=sys.stderr)
            return 1
    if not quiet:
        describe(current)
    return 0


def latest_user_settings(homes=None):
    """Settings of the user who changed them last, or None.

    The system restore service runs as root before anyone logs in, so it
    looks at every user's settings file and keeps the newest one.
    """
    if homes is None:
        homes = {p.pw_dir for p in pwd.getpwall() if p.pw_uid >= 1000 and p.pw_dir}
    newest, newest_mtime = None, -1.0
    for home in homes:
        path = os.path.join(home, ".config", "keyglow", "settings.json")
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            continue
        if mtime > newest_mtime:
            newest, newest_mtime = path, mtime
    return settings_mod.load(newest) if newest else None


def describe(s):
    if not s.enabled:
        print("Lighting: off")
        return
    info = EFFECTS[s.effect]
    parts = [info.name]
    if info.uses_color:
        parts.append(s.color)
    if info.uses_highlight:
        parts.append(f"highlight {s.highlight}")
    if info.uses_speed:
        parts.append(f"speed {round(s.speed * 100)}%")
    if info.uses_direction:
        parts.append(f"direction {s.direction}, size {round(s.wave_size * 100)}%")
    parts.append(f"brightness {round(s.brightness * 100)}%")
    print("Lighting: " + ", ".join(parts))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="keyglow", description="Keyboard lighting for SteelSeries KLC keyboards.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    sub.add_parser("gui", help="open the Keyglow window")
    sub.add_parser("apply", help="send the saved settings to the keyboard").add_argument(
        "-q", "--quiet", action="store_true", help="print nothing on success")
    restore = sub.add_parser(
        "restore", help="apply the most recently saved settings of any user (used at boot and resume)")
    restore.add_argument("-q", "--quiet", action="store_true", help="print nothing on success")
    sub.add_parser("status", help="show the keyboard and the saved settings")
    sub.add_parser("effects", help="list the available effects")
    sub.add_parser("on", help="turn the lighting on")
    sub.add_parser("off", help="turn the lighting off")

    p = sub.add_parser("set", help="choose an effect and its options",
                       description="Choose an effect. Options you leave out keep their saved value.")
    p.add_argument("effect", choices=list(EFFECTS), metavar="EFFECT",
                   help="one of: " + ", ".join(EFFECTS))
    p.add_argument("-c", "--color", type=_color, help="main color, e.g. ff8000")
    p.add_argument("--highlight", type=_color, help="key press color (reactive)")
    p.add_argument("-s", "--speed", type=_percent, help="animation speed, 0-100")
    p.add_argument("-b", "--brightness", type=_percent, help="brightness, 0-100")
    p.add_argument("-d", "--direction", choices=DIRECTIONS, help="wave direction")
    p.add_argument("--wave-size", type=_percent, help="wave size, 0-100")

    args = parser.parse_args(argv)

    if args.command == "gui":
        from .app import run
        return run([sys.argv[0]])

    if args.command == "restore":
        latest = latest_user_settings()
        if latest is None:
            return 0
        return apply(latest, quiet=args.quiet, wait=10)

    current = settings_mod.load()

    if args.command in (None, "status"):
        try:
            path, _ = device.find()
            print(f"Keyboard: SteelSeries KLC at {path}")
        except device.DeviceError as e:
            print(f"Keyboard: {e}")
        describe(current)
        if args.command is None:
            print("\nRun 'keyglow --help' for commands, or 'keyglow gui' for the window.")
        return 0

    if args.command == "effects":
        width = max(len(e) for e in EFFECTS)
        for info in EFFECTS.values():
            print(f"{info.id:<{width}}  {info.description}")
        return 0

    if args.command == "apply":
        return apply(current, quiet=args.quiet, wait=10)

    if args.command in ("on", "off"):
        current = current.with_changes(enabled=args.command == "on")
    elif args.command == "set":
        changes = dict(enabled=True, effect=args.effect)
        for name in ("color", "highlight", "speed", "brightness", "direction", "wave_size"):
            value = getattr(args, name)
            if value is not None:
                changes[name] = value
        current = current.with_changes(**changes)

    settings_mod.save(current)
    return apply(current)


if __name__ == "__main__":
    sys.exit(main())
