"""Animated drawing of the keyboard that mirrors what the controller shows."""
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Pango, PangoCairo  # noqa: E402

from . import layout  # noqa: E402
from .effects import Simulator  # noqa: E402

DECK = (0.09, 0.09, 0.10)
KEYCAP = (0.15, 0.15, 0.16)
LABEL_OFF = (0.42, 0.42, 0.45)
GAP = 0.09          # space between keys, in key units
RADIUS = 0.14       # key corner radius, in key units
PADDING = 0.45      # deck border, in key units


def _rounded_rect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -1.5708, 0)
    cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
    cr.arc(x + r, y + r, r, 3.1416, 4.7124)
    cr.close_path()


def _iso_enter(cr, x, y, w, h, r, notch):
    """L-shaped enter: full width on top, ``notch`` narrower on the bottom half."""
    mid = y + h / 2
    cr.new_sub_path()
    cr.arc(x + r, y + r, r, 3.1416, 4.7124)
    cr.arc(x + w - r, y + r, r, -1.5708, 0)
    cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + notch + r, y + h - r, r, 1.5708, 3.1416)
    cr.line_to(x + notch, mid)
    cr.line_to(x + r, mid)
    cr.arc(x + r, mid - r, r, 1.5708, 3.1416)
    cr.close_path()


class KeyboardPreview(Gtk.DrawingArea):
    def __init__(self):
        super().__init__(hexpand=True)
        self.update_property([Gtk.AccessibleProperty.LABEL], ["Keyboard lighting preview"])
        self._sim = None
        self._start = time.monotonic()
        self._pressed = {}
        self._tick = None
        self._layouts = {}
        self._font_px = None
        self.set_draw_func(self._draw)

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_measure(self, orientation, for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            return 280, 700, -1, -1
        width = for_size if for_size > 0 else 700
        height = round(width * (layout.HEIGHT + 2 * PADDING) / (layout.WIDTH + 2 * PADDING))
        return height, height, -1, -1

    def set_scene(self, scene):
        self._sim = Simulator(scene)
        self._pressed.clear()
        self._update_ticking()
        self.queue_draw()

    def press(self, code):
        if code in layout.BY_CODE:
            self._pressed[code] = time.monotonic()
            self._update_ticking()

    def _animating(self):
        if not self._sim:
            return False
        if not Gtk.Settings.get_default().props.gtk_enable_animations:
            return bool(self._pressed)
        return self._sim.scene.animated or bool(self._pressed)

    def _update_ticking(self):
        if self._animating() and self._tick is None:
            self._tick = self.add_tick_callback(self._on_tick)
        self.queue_draw()

    def _on_tick(self, _widget, _clock):
        now = time.monotonic()
        self._pressed = {c: t for c, t in self._pressed.items() if now - t < 3}
        self.queue_draw()
        if not self._animating():
            self._tick = None
            return False
        return True

    def _label_layout(self, text, font_px):
        if font_px != self._font_px:
            self._layouts.clear()
            self._font_px = font_px
        lay = self._layouts.get(text)
        if lay is None:
            lay = self.create_pango_layout(text)
            desc = self.get_pango_context().get_font_description().copy()
            desc.set_absolute_size(font_px * Pango.SCALE)
            desc.set_weight(Pango.Weight.SEMIBOLD)
            lay.set_font_description(desc)
            self._layouts[text] = lay
        return lay

    def _draw(self, _area, cr, width, height):
        total_w = layout.WIDTH + 2 * PADDING
        total_h = layout.HEIGHT + 2 * PADDING
        scale = min(width / total_w, height / total_h)
        ox = (width - total_w * scale) / 2
        oy = (height - total_h * scale) / 2

        cr.set_source_rgb(*DECK)
        _rounded_rect(cr, ox, oy, total_w * scale, total_h * scale, 0.5 * scale)
        cr.fill()

        animate = Gtk.Settings.get_default().props.gtk_enable_animations
        now = time.monotonic()
        t = now - self._start if animate else 0.0
        font_px = max(6.0, 0.24 * scale)
        gap, radius = GAP * scale, RADIUS * scale

        for key in layout.KEYS:
            pressed = self._pressed.get(key.code)
            rgb = self._sim.color(key.code, t, None if pressed is None else now - pressed) \
                if self._sim else (0, 0, 0)
            r, g, b = (c / 255 for c in rgb)
            glow = max(r, g, b)

            x = ox + (PADDING + key.x) * scale + gap / 2
            y = oy + (PADDING + key.y) * scale + gap / 2
            w, h = key.w * scale - gap, key.h * scale - gap

            def shape(grow=0.0):
                if key.iso_enter:
                    _iso_enter(cr, x - grow, y - grow, w + 2 * grow, h + 2 * grow,
                               radius + grow, 0.25 * scale)
                else:
                    _rounded_rect(cr, x - grow, y - grow, w + 2 * grow, h + 2 * grow, radius + grow)

            if glow > 0.01:
                # Light bleeding out from under the keycap.
                cr.set_source_rgba(r, g, b, 0.18 * glow)
                shape(gap * 1.4)
                cr.fill()
                cr.set_source_rgba(r, g, b, 0.45 * glow)
                shape(gap * 0.6)
                cr.fill()

            cr.set_source_rgb(*(k + c * 0.28 for k, c in zip(KEYCAP, (r, g, b))))
            shape()
            cr.fill_preserve()
            cr.set_line_width(max(1.0, 0.03 * scale))
            cr.set_source_rgba(r, g, b, 0.25 + 0.5 * glow) if glow > 0.01 \
                else cr.set_source_rgba(1, 1, 1, 0.06)
            cr.stroke()

            if key.label and w > font_px * 1.2:
                lay = self._label_layout(key.label, font_px)
                _ink, logical = lay.get_pixel_extents()
                if logical.width < w - 2:
                    if glow > 0.01:
                        cr.set_source_rgb(*(0.25 + 0.75 * c for c in (r, g, b)))
                    else:
                        cr.set_source_rgb(*LABEL_OFF)
                    lx = x + (w - logical.width) / 2
                    ly = y + (min(h, 1.0 * scale - gap) - logical.height) / 2
                    cr.move_to(lx, ly)
                    PangoCairo.show_layout(cr, lay)
