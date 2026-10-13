#!/usr/bin/env bash
# Builds keyglow_<version>_all.deb from this source tree.
# Usage: packaging/build-deb.sh [OUT_DIR]   (default: dist/)
# Prints the path of the built package.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=$(realpath -m "${1:-$ROOT/dist}")
APP_ID=io.github.beylerburak.Keyglow
VERSION=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$ROOT/keyglow/__init__.py")
[ -n "$VERSION" ] || { echo "Error: could not read the version." >&2; exit 1; }

PKG=$(mktemp -d)
trap 'rm -rf "$PKG"' EXIT

install -Dm755 "$ROOT/bin/keyglow" "$PKG/usr/bin/keyglow"
for f in "$ROOT"/keyglow/*.py; do
    install -Dm644 "$f" "$PKG/usr/lib/python3/dist-packages/keyglow/$(basename "$f")"
done
install -Dm644 "$ROOT/data/$APP_ID.desktop" "$PKG/usr/share/applications/$APP_ID.desktop"
install -Dm644 "$ROOT/data/$APP_ID.metainfo.xml" "$PKG/usr/share/metainfo/$APP_ID.metainfo.xml"
install -Dm644 "$ROOT/data/$APP_ID.svg" "$PKG/usr/share/icons/hicolor/scalable/apps/$APP_ID.svg"
install -Dm644 "$ROOT/data/70-keyglow.rules" "$PKG/usr/lib/udev/rules.d/70-keyglow.rules"
install -Dm644 "$ROOT/systemd/keyglow.service" "$PKG/usr/lib/systemd/user/keyglow.service"
install -Dm644 "$ROOT/systemd/keyglow-restore.service" "$PKG/usr/lib/systemd/system/keyglow-restore.service"
install -Dm644 "$ROOT/README.md" "$PKG/usr/share/doc/keyglow/README.md"
{
    echo "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/"
    echo "Upstream-Name: Keyglow"
    echo "Source: https://github.com/beylerburak/keyglow"
    echo
    echo "Files: *"
    echo "Copyright: 2026 beylerburak"
    echo "License: GPL-3+"
    echo " On Debian systems, the full text is in /usr/share/common-licenses/GPL-3."
} > "$PKG/usr/share/doc/keyglow/copyright"
chmod 644 "$PKG/usr/share/doc/keyglow/copyright"

mkdir -p "$PKG/DEBIAN"
cat > "$PKG/DEBIAN/control" <<EOF
Package: keyglow
Version: $VERSION
Architecture: all
Maintainer: beylerburak <burakbeyler@icloud.com>
Installed-Size: $(du -sk --exclude=DEBIAN "$PKG" | cut -f1)
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, gir1.2-gtk-4.0, gir1.2-adw-1 (>= 1.5), udev, systemd
Section: utils
Priority: optional
Homepage: https://github.com/beylerburak/keyglow
Description: keyboard lighting for MSI laptops with SteelSeries keyboards
 Keyglow controls the per-key RGB keyboard of MSI-based laptops (including
 rebrands such as Monster) that use a SteelSeries KLC controller, like
 SteelSeries GG does on Windows. It offers static colors and effects such as
 breathing, color cycle, rainbow wave, starlight and reactive typing, all
 played by the keyboard controller itself.
EOF
install -m755 "$ROOT/packaging/postinst" "$ROOT/packaging/prerm" "$ROOT/packaging/postrm" "$PKG/DEBIAN/"

find "$PKG" -type d -exec chmod 755 {} +
mkdir -p "$OUT"
DEB="$OUT/keyglow_${VERSION}_all.deb"
dpkg-deb --root-owner-group -Zxz --build "$PKG" "$DEB" >&2
echo "$DEB"
