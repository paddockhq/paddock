#!/usr/bin/env bash
# Download openshell-prover for a release, verify its checksum, and install it
# to ~/.local/bin. Usage: install-prover.sh <release-tag>
set -euo pipefail
# shellcheck source=scripts/ci/lib.sh
source "$(dirname "$0")/lib.sh"

version="${1:?usage: install-prover.sh <release-tag>}"
case "$(uname -m)" in
  x86_64) arch=x86_64 ;;
  aarch64 | arm64) arch=aarch64 ;;
  *) die "unsupported architecture $(uname -m)" ;;
esac
asset="openshell-prover-${arch}-unknown-linux-musl.tar.gz"
base="https://github.com/NVIDIA/OpenShell/releases/download/${version}"
work="$(mktemp -d)"
curl -fsSL --retry 3 -o "$work/$asset" "$base/$asset"
curl -fsSL --retry 3 -o "$work/checksums.txt" "$base/openshell-prover-checksums-sha256.txt"
(cd "$work" && grep " ${asset}\$" checksums.txt | sha256sum -c -)
tar -xzf "$work/$asset" -C "$work"
binary="$(find "$work" -type f -name openshell-prover | head -n 1)"
[ -n "$binary" ] || die "openshell-prover not found inside $asset"
mkdir -p "$HOME/.local/bin"
install -m 0755 "$binary" "$HOME/.local/bin/openshell-prover"
"$HOME/.local/bin/openshell-prover" --version
