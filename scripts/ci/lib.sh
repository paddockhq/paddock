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

# paddock_py <args...>: run the PadDock Python helpers from this checkout.
paddock_py() {
  PYTHONPATH="${PADDOCK_ROOT}/scripts${PYTHONPATH:+:$PYTHONPATH}" python3 -m paddock "$@"
}

# record_check <name> <pass|fail|error|skip> [detail]
# Appends one tab-separated check result to $PADDOCK_CHECKS_FILE.
record_check() {
  local name="$1" status="$2" detail="${3:-}"
  [ -n "${PADDOCK_CHECKS_FILE:-}" ] || die "PADDOCK_CHECKS_FILE is not set"
  detail="${detail//$'\t'/ }"
  detail="${detail//$'\n'/ }"
  printf '%s\t%s\t%s\n' "$name" "$status" "${detail:0:500}" >>"$PADDOCK_CHECKS_FILE"
  log "check ${name}: ${status}${detail:+ - ${detail:0:200}}"
}

# exec_flags: print the `openshell sandbox exec` flags this CLI supports, one per
# line. v0.0.116 has no --no-login-shell.
exec_flags() {
  local help flag
  help="$(openshell sandbox exec --help </dev/null 2>&1 || true)"
  for flag in --no-tty --no-login-shell; do
    if grep -q -- "$flag" <<<"$help"; then
      printf '%s\n' "$flag"
    fi
  done
}

# sb_exec <sandbox> <timeout-seconds> [extra exec flags, e.g. --env K=V ...] -- <command...>
# Runs a command in a sandbox with stdin closed, prints its output, and returns
# its exit code (124 when the timeout expires).
sb_exec() {
  local sandbox="$1" timeout_s="$2"
  shift 2
  local extra=()
  while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do
    extra+=("$1")
    shift
  done
  if [ "$#" -gt 0 ]; then shift; fi
  local flags=()
  mapfile -t flags < <(exec_flags)
  timeout --kill-after=10 "$((timeout_s + 60))" \
    openshell sandbox exec -n "$sandbox" --timeout "$timeout_s" "${flags[@]}" "${extra[@]}" -- "$@" </dev/null
}

# sandbox_ready <name>: succeed when the sandbox phase is Ready.
sandbox_ready() {
  local phase
  phase="$(openshell sandbox get "$1" -o json </dev/null 2>/dev/null | jq -r '.phase // empty' 2>/dev/null)"
  case "$phase" in
    Ready | *_READY) return 0 ;;
    *) return 1 ;;
  esac
}

# sandbox_name <bundle> <mode>: a sandbox name OpenShell accepts (a DNS-1123 label
# of at most 19 characters) that stays unique for each bundle and auth mode.
sandbox_name() {
  local hash
  hash="$(printf '%s/%s' "$1" "$2" | sha256sum | cut -c1-6)"
  printf '%s-%s\n' "${1:0:12}" "$hash"
}

# openshell_is <tag>: succeed only when the installed CLI is exactly release <tag>.
openshell_is() {
  [ "$(openshell --version 2>/dev/null)" = "openshell ${1#v}" ]
}
