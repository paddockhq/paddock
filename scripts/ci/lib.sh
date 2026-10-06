# shellcheck shell=bash
# Shared helpers for PadDock CI scripts. Source this file; do not run it.

log() { printf '[paddock] %s\n' "$*" >&2; }

die() {
  log "ERROR: $*"
  exit 1
}

# wait_until <timeout-seconds> <description> <command...>
# Re-runs the command every 2 seconds until it succeeds or the timeout passes.
wait_until() {
  local timeout="$1" what="$2"
  shift 2
  local waited=0
  until "$@"; do
    if [ "$waited" -ge "$timeout" ]; then
      log "timed out after ${timeout}s waiting for ${what}"
      return 1
    fi
    sleep 2
    waited=$((waited + 2))
  done
}

# gateway_connected: succeed only when `openshell status` reports a connected
# gateway. `openshell status` exits 0 even when disconnected, so read its output.
# v0.1.x supports `-o json`; older releases print a "Version:" line when connected.
gateway_connected() {
  local out
  if out="$(openshell status -o json </dev/null 2>/dev/null)" && [ -n "$out" ]; then
    jq -e '.status == "connected"' >/dev/null 2>&1 <<<"$out"
    return
  fi
  openshell status </dev/null 2>/dev/null | grep -q 'Version:'
}
