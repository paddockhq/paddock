#!/usr/bin/env bash
# Shared must-block tests (spec section 7.4, step 4) for one sandbox.
#
# Environment (set by scripts/ci/run-cell.sh or scripts/ci/findings.sh):
#   PADDOCK_ROOT, PADDOCK_LOG_DIR, PADDOCK_CHECKS_FILE  as for tests/allow.sh
#   PADDOCK_SANDBOX         sandbox to test; the probe is already inside it
#   PADDOCK_AUTH_MODE       auth mode, used in check names (<check>:<mode>)
#   PADDOCK_RUN_MODE        m1: the bundle's own sandbox; the probe is listed in no
#                               rule, like a process outside the agent's tree.
#                           m2: a variant sandbox whose provider profile lists the
#                               probe in place of the agent, like any tool the agent
#                               runs (rules cover child processes, spec R2).
#                           fd: the findings job (NVIDIA's unmodified profiles).
#   PADDOCK_PROVIDER_FILE   provider profile in force (m2 and fd: the L7 probe plan)
#   PADDOCK_PROBE           probe path inside the sandbox (default PADDOCK_PROBE_PATH)
#   PADDOCK_DUMMY_CREDENTIAL  the provider's dummy key; the literal-credential test
#                           sends a different value of the same shape
#   PADDOCK_SURVEY=1        findings job: also record which methods each endpoint allows
#
# How a check is judged (docs/decisions/0002-must-block-observations.md):
#   - Logged denials pass only when the attempt fails AND OpenShell logs the matching
#     DENIED line. Failing without the line is "error" (the network, not OpenShell,
#     may have stopped it); an ALLOWED line or a successful attempt is "fail".
#   - UDP and the outside-resolver query produce no log line in OpenShell v0.1.2. The
#     probe sends them with curl tftp://, and they pass only on the broker's answer:
#     curl exit 55 "Destination address required". Any other failure, such as
#     "Network is unreachable" or a probe that cannot run, is "error".
#   - The file-write check passes on "Permission denied" for a folder that Unix
#     permissions allow (/var/tmp), so only Landlock can be the reason.
set -uo pipefail
# shellcheck source=scripts/ci/lib.sh
source "$PADDOCK_ROOT/scripts/ci/lib.sh"

sb="$PADDOCK_SANDBOX"
mode="$PADDOCK_AUTH_MODE"
run="$PADDOCK_RUN_MODE"
probe="${PADDOCK_PROBE:-$PADDOCK_PROBE_PATH}"
nonce="${PADDOCK_NONCE:-$(date +%s)$$}" # tests/unit/test_deny.py pins it
events="$PADDOCK_LOG_DIR/deny-$run-$mode-events.log"
out="$PADDOCK_LOG_DIR/deny-$run-$mode"
mkdir -p "$out"

check() { record_check "deny-$run-$1:$mode" "$2" "${3:-}"; }

# attempt <name> <command...>: run in the sandbox; output goes to $out/<name>.txt and
# the exit code to $rc.
rc=0
attempt() {
  local name="$1"
  shift
  rc=0
  sb_exec "$sb" 30 -- "$@" >"$out/$name.txt" 2>&1 || rc=$?
}

allowed_count() { # <host> [extra events filters...]
  local host="$1"
  shift
  fetch_events "$sb" "$events"
  paddock_py events --log "$events" --action ALLOWED --host "$host" "$@" --format count
}

# logged_block <item> <host> <port> <command...>
logged_block() {
  local item="$1" host="$2" port="$3"
  shift 3
  attempt "$item" "$@"
  if [ "$rc" -eq 0 ]; then
    check "$item" fail "the probe reached $host:$port"
  elif await_event "$sb" "$events" --action DENIED --kind NET --activity OPEN \
    --host "$host" --port "$port" --binary "$probe" >/dev/null; then
    check "$item" pass ""
  elif [ "$(allowed_count "$host")" -ge 1 ]; then
    check "$item" fail "OpenShell allowed a connection to $host:$port"
  else
    check "$item" error "the attempt failed (exit $rc) but OpenShell logged no denial for $host:$port; see $item.txt"
  fi
}

# errno_block <item> <curl tftp:// command...>: for UDP sends, which OpenShell blocks
# without a log line. Only the broker's refusal (ADR 0002) counts as blocked.
errno_block() {
  local item="$1"
  shift
  attempt "$item" "$@"
  if [ "$rc" -eq 0 ]; then
    check "$item" fail "the attempt succeeded"
  elif [ "$rc" -eq 55 ] && grep -q 'curl: (55) Destination address required' "$out/$item.txt"; then
    check "$item" pass ""
  else
    check "$item" error "failed (exit $rc) without the sandbox broker's error; see $item.txt"
  fi
}

# Spec 7.4 run mode 1 requires --no-login-shell (sb_exec adds it when the CLI has it).
if ! exec_flags | grep -qx -- --no-login-shell; then
  check setup error "this OpenShell CLI has no 'sandbox exec --no-login-shell'"
  exit 0
fi

# 1. A host no rule lists.
host="pd-$nonce-host.example.com"
logged_block unlisted-host "$host" 443 "$probe" -sS --max-time 15 "https://$host/"

# 2. A DNS lookup of an unlisted name. OpenShell answers with a placeholder address
#    and logs NET:REFUSE, so the log line, not the lookup result, is the proof.
host="pd-$nonce-dns.example.com"
attempt dns-unlisted "$probe" -sS --max-time 15 "https://$host/"
if await_event "$sb" "$events" --action DENIED --kind NET --activity REFUSE --host "$host" >/dev/null; then
  check dns-unlisted pass ""
elif [ "$(allowed_count "$host")" -ge 1 ]; then
  check dns-unlisted fail "OpenShell allowed $host"
else
  check dns-unlisted error "OpenShell logged no NET:REFUSE line for $host; see dns-unlisted.txt"
fi

# 3. DNS sent straight to an outside resolver, over UDP (no log line exists) and TCP.
errno_block dns-outside-udp "$probe" -sS --max-time 10 tftp://8.8.8.8:53/pd
logged_block dns-outside-tcp 8.8.8.8 53 "$probe" -sS --max-time 15 telnet://8.8.8.8:53

# 4. Raw TCP and UDP to an IP address.
logged_block tcp-ip 1.1.1.1 443 "$probe" -sS --max-time 15 telnet://1.1.1.1:443
errno_block udp-ip "$probe" -sS --max-time 10 tftp://1.1.1.1:9999/pd

# 5. IPv6.
logged_block ipv6 2606:4700:4700::1111 443 "$probe" -sS --max-time 15 -6 'https://[2606:4700:4700::1111]/'

# 6. sentry.io, which NVIDIA's example claude-code profile allows (spec 6.2).
logged_block sentry sentry.io 443 "$probe" -sS --max-time 15 -X POST \
  -H 'Content-Type: application/json' -d '{}' https://sentry.io/api/0/envelope/

# 7. A write outside the writable folders. Landlock applies to the whole sandbox,
#    so this runs once, in mode 1.
if [ "$run" = m1 ]; then
  attempt write-control sh -c "test -d /var/tmp && test -w /var/tmp && echo x >/tmp/pd-$nonce && echo ok"
  if ! grep -qx ok "$out/write-control.txt"; then
    check write-outside error "no world-writable /var/tmp, or /tmp is not writable; see write-control.txt"
  else
    attempt write-outside sh -c "echo x >/var/tmp/pd-$nonce"
    if [ "$rc" -eq 0 ]; then
      check write-outside fail "wrote /var/tmp/pd-$nonce, which policy.yaml does not list as writable"
    elif grep -qi 'Permission denied' "$out/write-outside.txt"; then
      check write-outside pass ""
    else
      check write-outside error "the write failed (exit $rc) without 'Permission denied'; see write-outside.txt"
    fi
  fi
fi

[ "$run" = m1 ] && exit 0

# 8. Mode 2 and findings: requests on the allowed hosts, judged at L7. The control
#    request proves the probe is treated as the agent; without it the other L7
#    results would only show that an unlisted binary is blocked.
url_host() { # https://host[:port]/path -> host
  local rest="${1#https://}"
  rest="${rest%%/*}"
  echo "${rest%%:*}"
}
url_path() { # https://host[:port]/path -> /path
  local rest="${1#https://}"
  echo "/${rest#*/}"
}
# The probe runs inside the sandbox, so it cannot write files the runner reads:
# HTTP attempts print the body, then a line "http=<status>" (curl -w).
W=(-w '\nhttp=%{http_code}\n')
http_code() { sed -n 's/^http=//p' "$1" | tail -n 1; }

if ! paddock_py probe-plan "$PADDOCK_PROVIDER_FILE" --nonce "$nonce" >"$out/plan.tsv" 2>"$out/plan.err"; then
  check plan error "could not plan the L7 requests from the provider profile; see plan.err"
  exit 0
fi
mapfile -t plan <"$out/plan.tsv"
controls=0
allowed_controls=0
control_url=""
control_method=""
for line in "${plan[@]}"; do
  IFS=$'\t' read -r kind method url <<<"$line"
  [ "$kind" = control ] || continue
  controls=$((controls + 1))
  attempt "control-$controls" "$probe" -sS --max-time 15 "${W[@]}" \
    -X "$method" -H 'Content-Type: application/json' -d '{}' "$url"
  if await_event "$sb" "$events" --action ALLOWED --kind HTTP --activity "$method" \
    --host "$(url_host "$url")" --path "$(url_path "$url")" >/dev/null; then
    allowed_controls=$((allowed_controls + 1))
    if [ -z "$control_url" ]; then
      control_url="$url"
      control_method="$method"
    fi
  fi
done
if [ "$controls" -eq 0 ]; then
  check l7 skip "the profile has no L7-inspected endpoint with a named host"
elif [ "$allowed_controls" -lt "$controls" ]; then
  check control error "only $allowed_controls of $controls allowed requests were logged as ALLOWED; the probe was not treated as the agent, so L7 results would prove nothing"
else
  check control pass "$controls endpoint(s)"
  for line in "${plan[@]}"; do
    IFS=$'\t' read -r kind method url <<<"$line"
    case "$kind" in l7-method | l7-path) ;; *) continue ;; esac
    host="$(url_host "$url")"
    name="$kind-$host"
    attempt "$name" "$probe" -sS --max-time 15 "${W[@]}" \
      -X "$method" -H 'Content-Type: application/json' -d '{}' "$url"
    code="$(http_code "$out/$name.txt")"
    if [ "$code" = 403 ] && grep -q '"policy_denied"' "$out/$name.txt" &&
      await_event "$sb" "$events" --action DENIED --kind HTTP --activity "$method" \
        --host "$host" --path "$(url_path "$url")" >/dev/null; then
      check "$name" pass ""
    elif [ "$(allowed_count "$host" --kind HTTP --activity "$method" --path "$(url_path "$url")")" -ge 1 ]; then
      check "$name" fail "OpenShell allowed $method $url (HTTP $code)"
    else
      check "$name" error "$method $url returned HTTP $code without OpenShell's policy_denied answer and log line"
    fi
  done

  # 9. A literal, attacker-supplied credential on the allowed host. Recorded for
  #    research (spec 7.4); it never passes or fails a cell.
  literal_line="$(printf '%s\n' "${plan[@]}" | grep -m1 $'^literal\t' || true)"
  if [ -n "$literal_line" ]; then
    IFS=$'\t' read -r _ header prefix <<<"$literal_line"
    literal="${PADDOCK_DUMMY_CREDENTIAL//0/1}"
    [ "$literal" != "$PADDOCK_DUMMY_CREDENTIAL" ] || literal="${literal}x"
    attempt literal-credential "$probe" -sS --max-time 15 "${W[@]}" \
      -X "$control_method" -H 'Content-Type: application/json' -H "$header: $prefix$literal" -d '{}' "$control_url"
    code="$(http_code "$out/literal-credential.txt")"
    if grep -qE '"(policy_denied|credential_unavailable|credential_endpoint_mismatch)"' "$out/literal-credential.txt"; then
      check literal-credential skip "blocked by OpenShell (HTTP $code)"
    else
      check literal-credential skip "forwarded unchanged to $(url_host "$control_url") (upstream answered HTTP $code)"
    fi
  fi
fi

# 10. Findings survey: which methods each endpoint lets the probe use.
if [ "${PADDOCK_SURVEY:-0}" = 1 ]; then
  survey_targets=()
  for line in "${plan[@]}"; do
    IFS=$'\t' read -r kind host port protocol <<<"$line"
    [ "$kind" = endpoint ] || continue
    if [[ "$host" == *"*"* ]]; then
      check "survey-$host" skip "wildcard host; not probed by name"
      continue
    fi
    authority="$host"
    [ "$port" = 443 ] || authority="$host:$port"
    for method in GET POST PUT DELETE; do
      attempt "survey-$method-$host" "$probe" -sS --max-time 15 "${W[@]}" \
        -X "$method" -H 'Content-Type: application/json' -d '{}' "https://$authority/pd-$nonce-survey"
      survey_targets+=("$method $host $protocol $(http_code "$out/survey-$method-$host.txt")")
    done
  done
  sleep 3
  fetch_events "$sb" "$events"
  for target in "${survey_targets[@]}"; do
    read -r method host protocol code <<<"$target"
    if [ "$protocol" = rest ]; then
      verdict="$(paddock_py events --log "$events" --kind HTTP --activity "$method" --host "$host" \
        --path "/pd-$nonce-survey" --format lines | grep -oE 'ALLOWED|DENIED' | sort -u | tr '\n' ' ')"
    else
      verdict="$(paddock_py events --log "$events" --kind NET --activity OPEN --host "$host" \
        --format lines | grep -oE 'ALLOWED|DENIED' | sort -u | tr '\n' ' ')"
    fi
    check "survey-$method-$host" skip "OpenShell: ${verdict:-no log line}; HTTP $code"
  done
fi
exit 0
