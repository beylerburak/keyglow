"""Keyglow window (GTK 4 + libadwaita)."""
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, AUTHOR, AUTHOR_URL, WEBSITE, __version__, device, layout  # noqa: E402
from . import settings as settings_mod  # noqa: E402
from .effects import EFFECTS, build_scene  # noqa: E402
from .preview import KeyboardPreview  # noqa: E402
from .settings import format_color, parse_color  # noqa: E402

APPLY_DELAY_MS = 120

SWATCHES = [
    ("Red", "#ff0000"), ("Orange", "#ff5000"), ("Yellow", "#ffc800"),
    ("Green", "#00ff00"), ("Teal", "#00ffa0"), ("Cyan", "#00c8ff"),
    ("Blue", "#0028ff"), ("Purple", "#8000ff"), ("Pink", "#ff0080"),
    ("White", "#ffffff"),
]

DIRECTION_NAMES = {
    "right": "Left to Right", "left": "Right to Left",
    "down": "Top to Bottom", "up": "Bottom to Top",
    "out": "From the Center", "in": "Toward the Center",
}

CSS = """
.swatch { min-width: 32px; min-height: 32px; padding: 0; border-radius: 9999px;
          box-shadow: inset 0 0 0 1px alpha(black, 0.15); }
.swatch image { color: black; -gtk-icon-shadow: none; }
.swatch.dark-check image { color: white; }
.swatch:checked { outline: 2px solid @accent_color; outline-offset: 2px; }
""" + "".join(
    f".swatch-{hexcode[1:]} {{ background: {hexcode}; }}\n" for _, hexcode in SWATCHES)


class Applier:
    """Sends scenes to the keyboard on a worker thread, newest request wins."""

    def __init__(self, on_result):
        self._on_result = on_result
        self._pending = None
        self._cond = threading.Condition()
        threading.Thread(target=self._run, daemon=True).start()

    def submit(self, settings):
        with self._cond:
            self._pending = settings
            self._cond.notify()

    def _run(self):
        while True:
            with self._cond:
                while self._pending is None:
                    self._cond.wait()
                current, self._pending = self._pending, None
            error = None
            try:
                with device.Keyboard() as kb:
                    kb.apply(build_scene(current))
            except device.DeviceError as e:
                error = e
            except Exception as e:  # keep the worker alive whatever happens
                error = device.DeviceError(f"Unexpected error: {e}")
            GLib.idle_add(self._on_result, error)


def _scale_row(title, subtitle, value, on_change, marks=None):
    row = Adw.ActionRow(title=title, subtitle=subtitle or "")
    scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
    scale.set_value(value * 100)
    scale.set_draw_value(False)
    scale.set_hexpand(True)
    scale.set_valign(Gtk.Align.CENTER)
    scale.set_size_request(140, -1)
    for pos, label in (marks or {}).items():
        scale.add_mark(pos, Gtk.PositionType.BOTTOM, label)
    scale.update_property([Gtk.AccessibleProperty.LABEL], [title])
    scale.connect("value-changed", lambda s: on_change(s.get_value() / 100))
    row.add_suffix(scale)
    return row, scale


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=APP_NAME)
        self.set_default_size(720, 860)
        self.set_size_request(360, 400)
        self.settings = settings_mod.load()
        self._apply_source = None
        self._syncing = False
        self.applier = Applier(self._on_applied)

        # Header
        self.title = Adw.WindowTitle(title=APP_NAME)
        header = Adw.HeaderBar(title_widget=self.title)
        menu = Gio.Menu()
        menu.append("_About Keyglow", "app.about")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                       primary=True, tooltip_text="Main Menu"))

        self.banner = Adw.Banner(button_label="_Retry")
        self.banner.connect("button-clicked", lambda _b: self._schedule_apply(0))

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24,
                          margin_top=12, margin_bottom=32, margin_start=12, margin_end=12)
        clamp = Adw.Clamp(maximum_size=760, tightening_threshold=560, child=content)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                      vexpand=True, child=clamp)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.append(self.banner)
        body.append(scroller)
        self.toasts = Adw.ToastOverlay(child=body)

        view = Adw.ToolbarView(content=self.toasts)
        view.add_top_bar(header)
        self.set_content(view)

        # Preview
        self.preview = KeyboardPreview()
        content.append(self.preview)

        content.append(self._build_lighting_group())
        content.append(self._build_effect_group())
        content.append(self._build_color_group())
        content.append(self._build_motion_group())
        content.append(self._build_footer())

        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key_pressed)
        self.add_controller(keys)

        self._sync_widgets()
        self._schedule_apply(0)

    # ---- building -----------------------------------------------------

    def _build_lighting_group(self):
        group = Adw.PreferencesGroup()
        self.enabled_row = Adw.SwitchRow(title="Keyboard Lighting",
                                         subtitle="Fn + F8 also changes the brightness")
        self.enabled_row.connect("notify::active", lambda r, _p: self._change(enabled=r.get_active()))
        group.add(self.enabled_row)
        self.brightness_row, self.brightness = _scale_row(
            "Brightness", None, self.settings.brightness,
            lambda v: self._change(brightness=max(v, 0.05)))
        group.add(self.brightness_row)
        return group

    def _build_effect_group(self):
        self.effect_group = Adw.PreferencesGroup(title="Effect")
        self.effect_checks = {}
        first = None
        for info in EFFECTS.values():
            check = Gtk.CheckButton(group=first, valign=Gtk.Align.CENTER)
            first = first or check
            row = Adw.ActionRow(title=info.name, subtitle=info.description, activatable_widget=check)
            row.add_prefix(check)
            check.connect("toggled", self._on_effect_toggled, info.id)
            self.effect_group.add(row)
            self.effect_checks[info.id] = check
        return self.effect_group

    def _build_color_group(self):
        self.color_group = Adw.PreferencesGroup(title="Color")

        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                           min_children_per_line=5, max_children_per_line=10,
                           row_spacing=12, column_spacing=12,
                           margin_top=14, margin_bottom=14, margin_start=12, margin_end=12)
        self.swatches = {}
        for name, hexcode in SWATCHES:
            # Not a toggle group: a custom color must be able to uncheck them all.
            button = Gtk.ToggleButton(tooltip_text=name,
                                      halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER,
                                      css_classes=["swatch", f"swatch-{hexcode[1:]}"])
            if sum(parse_color(hexcode)) < 300:
                button.add_css_class("dark-check")
            check = Gtk.Image(icon_name="object-select-symbolic")
            button.set_child(check)
            button.bind_property("active", check, "visible", GObject.BindingFlags.SYNC_CREATE)
            button.update_property([Gtk.AccessibleProperty.LABEL], [name])
            button.connect("toggled", self._on_swatch_toggled, hexcode)
            flow.append(button)
            self.swatches[hexcode] = button
        self.swatch_row = Adw.PreferencesRow(activatable=False, selectable=False, child=flow,
                                             title="Preset Colors")
        self.color_group.add(self.swatch_row)

        self.custom_row = Adw.ActionRow(title="Custom Color")
        self.custom_button = Gtk.ColorDialogButton(
            dialog=Gtk.ColorDialog(title="Custom Color", with_alpha=False), valign=Gtk.Align.CENTER)
        self.custom_button.connect("notify::rgba", self._on_custom_color)
        self.custom_row.add_suffix(self.custom_button)
        self.custom_row.set_activatable_widget(self.custom_button)
        self.color_group.add(self.custom_row)

        self.highlight_row = Adw.ActionRow(title="Key Press Color",
                                           subtitle="Shown briefly when a key is pressed")
        self.highlight_button = Gtk.ColorDialogButton(
            dialog=Gtk.ColorDialog(title="Key Press Color", with_alpha=False), valign=Gtk.Align.CENTER)
        self.highlight_button.connect("notify::rgba", self._on_highlight_color)
        self.highlight_row.add_suffix(self.highlight_button)
        self.highlight_row.set_activatable_widget(self.highlight_button)
        self.color_group.add(self.highlight_row)
        return self.color_group

    def _build_motion_group(self):
        self.motion_group = Adw.PreferencesGroup(title="Animation")
        self.speed_row, self.speed = _scale_row(
            "Speed", None, self.settings.speed, lambda v: self._change(speed=v))
        self.motion_group.add(self.speed_row)

        self.direction_ids = list(DIRECTION_NAMES)
        self.direction_row = Adw.ComboRow(
            title="Direction", model=Gtk.StringList.new(list(DIRECTION_NAMES.values())))
        self.direction_row.connect("notify::selected", self._on_direction)
        self.motion_group.add(self.direction_row)

        self.size_row, self.size = _scale_row(
            "Wave Size", None, self.settings.wave_size, lambda v: self._change(wave_size=v))
        self.motion_group.add(self.size_row)
        return self.motion_group

    def _build_footer(self):
        return Gtk.Label(
            use_markup=True, justify=Gtk.Justification.CENTER, wrap=True,
            css_classes=["dim-label", "caption"],
            label=f'{APP_NAME} {__version__} · Made by <a href="{AUTHOR_URL}">@{AUTHOR}</a>')

    # ---- state ----------------------------------------------------------

    def _sync_widgets(self):
        """Make every widget reflect self.settings without feeding back."""
        s = self.settings
        info = EFFECTS[s.effect]
        self._syncing = True
        try:
            self.enabled_row.set_active(s.enabled)
            self.brightness.set_value(s.brightness * 100)
            self.effect_checks[s.effect].set_active(True)
            for hexcode, button in self.swatches.items():
                button.set_active(hexcode == s.color)
            self.custom_button.set_rgba(self._rgba(s.color))
            self.highlight_button.set_rgba(self._rgba(s.highlight))
            self.speed.set_value(s.speed * 100)
            self.direction_row.set_selected(self.direction_ids.index(s.direction))
            self.size.set_value(s.wave_size * 100)
        finally:
            self._syncing = False

        for widget in (self.brightness_row, self.effect_group, self.color_group, self.motion_group):
            widget.set_sensitive(s.enabled)
        self.color_group.set_visible(info.uses_color or info.uses_highlight)
        self.swatch_row.set_visible(info.uses_color)
        self.custom_row.set_visible(info.uses_color)
        self.highlight_row.set_visible(info.uses_highlight)
        self.motion_group.set_visible(info.uses_speed or info.uses_direction)
        self.speed_row.set_title("Fade Time" if s.effect == "reactive" else "Speed")
        self.direction_row.set_visible(info.uses_direction)
        self.size_row.set_visible(info.uses_direction)
        self.preview.set_scene(build_scene(s))

    @staticmethod
    def _rgba(hexcode):
        rgba = Gdk.RGBA()
        rgba.parse(hexcode)
        return rgba

    def _change(self, **changes):
        if self._syncing:
            return
        new = self.settings.with_changes(**changes)
        if new == self.settings:
            return
        self.settings = new
        self._sync_widgets()
        self._schedule_apply(APPLY_DELAY_MS)

    def _schedule_apply(self, delay):
        if self._apply_source:
            GLib.source_remove(self._apply_source)
        self._apply_source = GLib.timeout_add(delay, self._apply_now)

    def _apply_now(self):
        self._apply_source = None
        try:
            settings_mod.save(self.settings)
        except OSError as e:
            self.toasts.add_toast(Adw.Toast(title=f"Could not save settings: {e.strerror}"))
        self.applier.submit(self.settings)
        return GLib.SOURCE_REMOVE

    def _on_applied(self, error):
        if error is None:
            self.banner.set_revealed(False)
            self.title.set_subtitle("SteelSeries KLC")
        else:
            self.banner.set_title(str(error))
            self.banner.set_revealed(True)
            self.title.set_subtitle("Keyboard not connected")
        return GLib.SOURCE_REMOVE

    # ---- signal handlers -----------------------------------------------

    def _on_effect_toggled(self, check, effect_id):
        if check.get_active():
            self._change(effect=effect_id)

    def _on_swatch_toggled(self, button, hexcode):
        if button.get_active():
            self._change(color=hexcode)
        elif not self._syncing and hexcode == self.settings.color:
            button.set_active(True)   # clicking the selected swatch keeps it selected

    def _on_custom_color(self, button, _pspec):
        rgba = button.get_rgba()
        self._change(color=format_color(tuple(round(c * 255) for c in (rgba.red, rgba.green, rgba.blue))))

    def _on_highlight_color(self, button, _pspec):
        rgba = button.get_rgba()
        self._change(highlight=format_color(tuple(round(c * 255) for c in (rgba.red, rgba.green, rgba.blue))))

    def _on_direction(self, row, _pspec):
        index = row.get_selected()
        if 0 <= index < len(self.direction_ids):
            self._change(direction=self.direction_ids[index])

    def _on_key_pressed(self, _controller, _keyval, keycode, _state):
        code = layout.EVDEV_TO_USAGE.get(keycode - 8)
        if code is not None:
            self.preview.press(code)
        return False


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        GLib.set_application_name(APP_NAME)

    def do_startup(self):
        Adw.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        about = Gio.SimpleAction(name="about")
        about.connect("activate", self._on_about)
        self.add_action(about)
        quit_action = Gio.SimpleAction(name="quit")
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Control>q"])
        self.set_accels_for_action("window.close", ["<Control>w"])

    def do_activate(self):
        window = self.get_active_window() or Window(self)
        window.present()

    def _on_about(self, *_):
        dialog = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            version=__version__,
            developer_name=AUTHOR,
            developers=[f"{AUTHOR} {AUTHOR_URL}"],
            copyright=f"© 2026 {AUTHOR}",
            website=WEBSITE,
            issue_url=f"{WEBSITE}/issues",
            comments="Keyboard lighting for MSI-based laptops with a SteelSeries KLC "
                     "per-key RGB controller. Effects run on the keyboard itself.",
            license_type=Gtk.License.GPL_3_0,
        )
        dialog.add_link("GitHub Profile", AUTHOR_URL)
        dialog.add_credit_section("Protocol research", ["msi-perkeyrgb (Askannz, TauAkiou)", "OpenRGB"])
        dialog.present(self.get_active_window())


def run(argv=None):
    return Application().run(argv if argv is not None else sys.argv)
