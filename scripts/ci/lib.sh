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
  local out err rc=0
  err="$(mktemp)"
  out="$(timeout 15 openshell status -o json </dev/null 2>"$err")" || rc=$?
  if [ "$rc" -eq 0 ]; then
    rm -f "$err"
    jq -e '.status == "connected"' >/dev/null 2>&1 <<<"$out"
    return
  fi
  # Fall back to the text output only when this CLI has no `-o json` (a usage error).
  if [ "$rc" -eq 2 ] || grep -qiE 'unexpected argument|unrecognized|unknown (option|argument)' "$err"; then
    rm -f "$err"
    timeout 15 openshell status </dev/null 2>/dev/null | grep -q 'Version:'
    return
  fi
  rm -f "$err"
  return 1
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
  # PADDOCK_QUIET=1 (findings job): job logs are public, so outcomes stay in the file.
  if [ "${PADDOCK_QUIET:-0}" != 1 ]; then
    log "check ${name}: ${status}${detail:+ - ${detail:0:200}}"
  fi
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
    Ready | SANDBOX_PHASE_READY) return 0 ;;
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

# Where CI uploads the static curl probe inside a sandbox (scripts/paddock/probe.py).
PADDOCK_PROBE_PATH=/sandbox/.paddock/curl

# upload_probe <sandbox> <local-probe>: copy the probe into the sandbox and check
# that it runs. Upload it before its first network use: OpenShell pins each
# binary's hash the first time it connects.
upload_probe() {
  openshell sandbox upload "$1" "$2" "${PADDOCK_PROBE_PATH%/*}/" </dev/null >/dev/null 2>&1 &&
    sb_exec "$1" 30 -- chmod 0755 "$PADDOCK_PROBE_PATH" >/dev/null 2>&1 &&
    sb_exec "$1" 30 -- "$PADDOCK_PROBE_PATH" --version >/dev/null 2>&1
}

# fetch_events <sandbox> <file>: save the sandbox's policy log. The default
# `-n 200` can drop older lines.
fetch_events() {
  openshell logs "$1" --source sandbox -n 20000 </dev/null >"$2" 2>&1 || true
}

# await_event <sandbox> <file> <paddock events filters...>
# OpenShell pushes log lines in batches, so poll until a matching event arrives
# (PADDOCK_EVENT_WAIT seconds, default 10). Prints the final count and succeeds
# when it is at least 1.
await_event() {
  local sandbox="$1" file="$2"
  shift 2
  local tries="${PADDOCK_EVENT_WAIT:-10}" count=0
  while :; do
    fetch_events "$sandbox" "$file"
    count="$(paddock_py events --log "$file" "$@" --format count 2>/dev/null)" || count=0
    if [ "$count" -ge 1 ]; then break; fi
    tries=$((tries - 1))
    if [ "$tries" -le 0 ]; then break; fi
    sleep 1
  done
  echo "$count"
  [ "$count" -ge 1 ]
}

# seal_logs <dir> <out.age>: encrypt a folder to the maintainer's age key
# (.github/findings-recipients.txt) and delete the plaintext. Without the key or
# the age tool, the plaintext is still deleted: withheld beats published
# (spec 7.6).
seal_logs() {
  local dir="$1" out="$2" recipients="$PADDOCK_ROOT/.github/findings-recipients.txt"
  if [ -s "$recipients" ] &&
    { command -v age >/dev/null || { sudo apt-get update -qq && sudo apt-get install -y -qq age; } >/dev/null 2>&1; }; then
    tar -C "${dir%/*}" -czf - "${dir##*/}" | age -R "$recipients" -o "$out" || rm -f "$out"
  fi
  rm -rf "$dir"
}
