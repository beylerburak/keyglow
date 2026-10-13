#!/usr/bin/env bash
# Installs Keyglow on Ubuntu, Debian and other apt-based systems.
#
#   curl -fsSL https://raw.githubusercontent.com/beylerburak/keyglow/main/install.sh | bash
#
# Run from a clone of the repository, it builds the package from that source
# instead of downloading the latest release. Remove with: sudo apt remove keyglow
set -euo pipefail

REPO=beylerburak/keyglow

say() { printf '\n==> %s\n' "$*"; }
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -ne 0 ] || die "run this as your normal user, without sudo. It asks for your password when needed."
command -v apt-get >/dev/null || die "this installer needs an apt-based system such as Ubuntu or Debian."

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
chmod 755 "$TMP"   # apt reads the package as an unprivileged user

SCRIPT=${BASH_SOURCE[0]:-}
SOURCE=""
if [ -n "$SCRIPT" ] && [ -f "$SCRIPT" ]; then
    SOURCE=$(cd "$(dirname "$SCRIPT")" && pwd)
    [ -f "$SOURCE/packaging/build-deb.sh" ] || SOURCE=""
fi

if [ -n "$SOURCE" ]; then
    say "Building the package from $SOURCE"
    DEB=$("$SOURCE/packaging/build-deb.sh" "$TMP")
else
    command -v curl >/dev/null || die "curl not found."
    say "Finding the latest release"
    URL=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
        | grep -o '"browser_download_url": *"[^"]*_all\.deb"' | head -n 1 | cut -d '"' -f 4)
    [ -n "$URL" ] || die "no release package found at https://github.com/$REPO/releases"
    DEB="$TMP/$(basename "$URL")"
    say "Downloading $(basename "$URL")"
    curl -fL --progress-bar -o "$DEB" "$URL"
fi
chmod 644 "$DEB"

say "Installing (asks for your password)"
sudo apt-get install -y "$DEB"

say "Applying your lighting"
keyglow apply || echo "The keyboard did not respond. Open Keyglow to see what is wrong."

say "Done. Open Keyglow from the app menu, or run: keyglow --help"
