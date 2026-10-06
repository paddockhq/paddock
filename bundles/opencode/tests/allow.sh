#!/usr/bin/env bash
# Must-work tests for the OpenCode bundle (spec section 7.4, step 3).
# run-cell.sh runs this once per auth mode; see the allow.sh contract in Plan 1, Task 8.
set -uo pipefail
# shellcheck source=scripts/ci/lib.sh
source "$PADDOCK_ROOT/scripts/ci/lib.sh"
eval "$(paddock_py bundle-env "$PADDOCK_BUNDLE_DIR")"

sb="$PADDOCK_SANDBOX"
mode="$PADDOCK_AUTH_MODE"
model="${OPENCODE_TEST_MODEL:-openrouter/nvidia/nemotron-3.5-lightning:free}"

# 1. The agent starts and reports its version.
if out="$(sb_exec "$sb" 60 "${PADDOCK_ENV_ARGS[@]}" -- opencode --version 2>&1)"; then
  record_check "version:$mode" pass "$out"
else
  record_check "version:$mode" fail "$out"
fi

# 2. OpenCode's data folder is writable (HOME is /sandbox for UID 1000).
# shellcheck disable=SC2016  # $HOME must expand inside the sandbox, not here
if out="$(sb_exec "$sb" 30 -- sh -c 'mkdir -p "$HOME/.local/share/opencode" && touch "$HOME/.local/share/opencode/.paddock-write-test"' 2>&1)"; then
  record_check "state-writable:$mode" pass ""
else
  record_check "state-writable:$mode" fail "$out"
fi

# 3. A real request reaches OpenRouter, and nothing else is contacted.
#    CI uses a dummy key, so OpenRouter answers 401 and opencode exits non-zero.
#    The live smoke test (--live) uses a real key and expects an answer.
rc=0
out="$(sb_exec "$sb" 180 "${PADDOCK_ENV_ARGS[@]}" -- opencode run --standalone -m "$model" "Reply with exactly: OK" 2>&1)" || rc=$?
printf '%s\n' "$out" >"$PADDOCK_LOG_DIR/opencode-run-$mode.log"
sleep 3
events="$PADDOCK_LOG_DIR/policy-events-$mode.log"
openshell logs "$sb" --source sandbox </dev/null >"$events" 2>&1 || true
denied="$(paddock_py events --log "$events" --action DENIED --format hosts)"
allowed="$(paddock_py events --log "$events" --action ALLOWED --host openrouter.ai --format count)"
if [ -n "$denied" ]; then
  record_check "egress:$mode" fail "denied destinations: $(tr '\n' ' ' <<<"$denied")"
elif [ "${allowed:-0}" -lt 1 ]; then
  record_check "egress:$mode" fail "no allowed connection to openrouter.ai was logged"
else
  record_check "egress:$mode" pass "openrouter.ai only"
fi

if [ "$PADDOCK_LIVE" = 1 ]; then
  if [ "$rc" -eq 0 ] && grep -q 'OK' <<<"$out"; then
    record_check "live-answer:$mode" pass ""
  else
    record_check "live-answer:$mode" fail "exit $rc: $(tail -n 3 <<<"$out")"
  fi
elif [ "$rc" -ne 0 ] && grep -qiE '401|user not found|unauthori[sz]ed|authentication' <<<"$out"; then
  # A CLI failure also exits non-zero, so require OpenRouter's auth error in the output.
  record_check "upstream-auth-error:$mode" pass "exit $rc with the dummy key, as expected"
else
  record_check "upstream-auth-error:$mode" fail "expected OpenRouter's auth error with the dummy key; got exit $rc: $(tail -n 3 <<<"$out")"
fi
