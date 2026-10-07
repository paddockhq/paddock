#!/usr/bin/env bash
# Download the static curl that the must-block tests run inside sandboxes, verify
# it against pinned checksums, and install it to ~/.local/share/paddock/curl.
# Usage: install-probe.sh   (prints the installed path)
# Source: https://github.com/stunnel/static-curl (MIT), release 8.22.0, musl build.
# CI only downloads and runs it; PadDock never redistributes it.
set -euo pipefail
# shellcheck source=scripts/ci/lib.sh
source "$(dirname "$0")/lib.sh"

release=8.22.0
case "$(uname -m)" in
  x86_64)
    arch=x86_64
    tarball_sha=dfb02460ba2abe513087538f12a3cf79b74b64a5ea3787ce8ac0cdb11251f884
    binary_sha=b7443db66d622a27ef2152bb2032d6ada9fb29a8917f22b9521a993f8e61cd7f
    ;;
  aarch64 | arm64)
    arch=aarch64
    tarball_sha=cf94cbeaae1b3c1944a4a761ef04478f8f0b23e93a324b5ed009b2082eda11f3
    binary_sha=c392bc0ea0c7951ee170e0eb7874c9d4000397254d788552ffaa4e7ccb75ae07
    ;;
  *) die "unsupported architecture $(uname -m)" ;;
esac

work="$(mktemp -d)"
tarball="$work/curl.tar.xz"
curl -fsSL --retry 3 -o "$tarball" \
  "https://github.com/stunnel/static-curl/releases/download/${release}/curl-linux-${arch}-musl-${release}.tar.xz"
echo "$tarball_sha  $tarball" | sha256sum -c - >&2
tar -xJf "$tarball" -C "$work"
binary="$(find "$work" -type f -name curl | head -n 1)"
[ -n "$binary" ] || die "curl not found inside the static-curl tarball"
echo "$binary_sha  $binary" | sha256sum -c - >&2
dest="$HOME/.local/share/paddock/curl"
mkdir -p "${dest%/*}"
install -m 0755 "$binary" "$dest"
echo "$dest"
