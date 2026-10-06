#!/usr/bin/env bash
# Install a pinned OpenShell release with NVIDIA's installer and wait until the
# local gateway is connected. Usage: install-openshell.sh <release-tag>
set -euo pipefail
# shellcheck source=scripts/ci/lib.sh
source "$(dirname "$0")/lib.sh"

version="${1:?usage: install-openshell.sh <release-tag, for example v0.1.2>}"

# The Linux package runs the gateway as a systemd *user* service, and CI
# runners have no login session. Lingering starts the user's systemd manager.
sudo loginctl enable-linger "$USER"
XDG_RUNTIME_DIR="/run/user/$(id -u)"
export XDG_RUNTIME_DIR
wait_until 60 "the user systemd bus" test -S "$XDG_RUNTIME_DIR/bus"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
if [ -n "${GITHUB_ENV:-}" ]; then
  {
    echo "XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR"
    echo "DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS"
  } >>"$GITHUB_ENV"
fi

# Runners ship Podman 4.9 and OpenShell auto-detects Podman before Docker, so
# pin Docker. v0.1.x reads OPENSHELL_COMPUTE_DRIVER; v0.0.x reads OPENSHELL_DRIVERS.
systemctl --user set-environment OPENSHELL_COMPUTE_DRIVER=docker OPENSHELL_DRIVERS=docker

installer="$(mktemp)"
curl -fsSL --retry 3 -o "$installer" \
  "https://raw.githubusercontent.com/NVIDIA/OpenShell/${version}/install.sh"
OPENSHELL_VERSION="$version" OPENSHELL_INSTALL_METHOD=deb \
  OPENSHELL_INSTALL_GATEWAY_TIMEOUT=180 sh "$installer"

if ! wait_until 180 "the OpenShell gateway" gateway_connected; then
  systemctl --user status openshell-gateway --no-pager >&2 || true
  journalctl --user -u openshell-gateway --no-pager -n 200 >&2 || true
  die "OpenShell ${version} gateway did not connect"
fi
openshell --version
