#!/usr/bin/env bash
# Run every check for one CI matrix cell: one bundle on one OpenShell release.
# Usage: run-cell.sh <bundle> <openshell-tag> <runner-label> [--live]
# Writes results/<bundle>--<tag>--<runner>.json and keeps logs under
# results/logs/<bundle>--<tag>--<runner>/. Exits 0 only when the cell passes.
# --live uses real credentials from the environment instead of dummy values, and
# skips the must-block suite (the weekly live run checks only the real answer).
set -uo pipefail

PADDOCK_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PADDOCK_ROOT
# shellcheck source=scripts/ci/lib.sh
source "$PADDOCK_ROOT/scripts/ci/lib.sh"

bundle="${1:?usage: run-cell.sh <bundle> <openshell-tag> <runner-label> [--live]}"
version="${2:?missing the OpenShell release tag}"
runner="${3:?missing the runner label}"
live=0
if [ "${4:-}" = "--live" ]; then live=1; fi

bundle_dir="$PADDOCK_ROOT/bundles/$bundle"
cell="${bundle}--${version}--${runner}"
results_dir="$PADDOCK_ROOT/results"
# Raw logs stay outside results/, which CI uploads publicly even after a cancel or
# a timeout, until finish() decides what may be published (spec 7.6).
PADDOCK_LOG_DIR="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/paddock-logs/$cell"
PADDOCK_CHECKS_FILE="$PADDOCK_LOG_DIR/checks.tsv"
export PADDOCK_LOG_DIR PADDOCK_CHECKS_FILE
rm -rf "$PADDOCK_LOG_DIR"
mkdir -p "$PADDOCK_LOG_DIR" "$results_dir"
: >"$PADDOCK_CHECKS_FILE"
primary="$(jq -r '.versions[0]' "$PADDOCK_ROOT/scripts/ci/openshell-versions.json")"
prover="$HOME/.local/bin/openshell-prover"
probe=""

finish() {
  local rc=0
  journalctl --user -u openshell-gateway --no-pager -n 500 >"$PADDOCK_LOG_DIR/gateway.log" 2>&1 || true
  paddock_py result --bundle "$bundle" --openshell-version "$version" --runner "$runner" \
    --checks "$PADDOCK_CHECKS_FILE" --out "$results_dir/$cell.json" || rc=$?
  # Spec 7.6: a must-block check that did not pass may describe an unfixed
  # OpenShell weakness. The public result withholds its details (results.py), and
  # publish_logs seals the raw logs for the maintainer instead of publishing them.
  publish_logs "$PADDOCK_LOG_DIR" "$results_dir" "$cell"
  exit "$rc"
}
trap finish EXIT

# Order matters: OpenShell refuses to delete a provider that a sandbox uses, or a
# profile that a provider uses. Each delete exits 0 when the object is missing.
cleanup_mode() {
  local sandbox="$1" provider="$2" profile="$3"
  oc sandbox delete "$sandbox" </dev/null >/dev/null 2>&1 || true
  oc provider delete "$provider" </dev/null >/dev/null 2>&1 || true
  oc provider profile delete "$profile" </dev/null >/dev/null 2>&1 || true
}

# No --auto-providers/--no-auto-providers flag: with stdin closed, a missing
# provider then fails the create instead of being skipped with a warning.
# <label> names the log file: sandbox-<label>.log.
create_sandbox() {
  local sandbox="$1" provider="$2" label="$3"
  oc sandbox create --name "$sandbox" --from "$PADDOCK_IMAGE" \
    --policy "$bundle_dir/policy.yaml" --provider "$provider" \
    "${PADDOCK_ENV_ARGS[@]}" --no-tty --detach </dev/null >"$PADDOCK_LOG_DIR/sandbox-$label.log" 2>&1 &&
    wait_until 300 "sandbox $sandbox to be Ready" sandbox_ready "$sandbox"
}

prover_check() {
  local sandbox="$1" mode="$2"
  if [ "$version" != "$primary" ]; then
    record_check "prover:$mode" skip "the prover runs only on the primary version ($primary)"
    return
  fi
  if [ ! -x "$prover" ]; then
    record_check "prover:$mode" error "openshell-prover is not installed"
    return
  fi
  local candidate="$PADDOCK_LOG_DIR/effective-policy-$mode.yaml"
  local out="$PADDOCK_LOG_DIR/prover-$mode.json"
  if ! oc sandbox get "$sandbox" --policy-only </dev/null >"$candidate" 2>>"$PADDOCK_LOG_DIR/sandbox-$mode.log"; then
    record_check "prover:$mode" error "could not read the effective policy"
    return
  fi
  local rc=0 result
  "$prover" check "$candidate" --boundary "$bundle_dir/boundary.yaml" --output json --timeout 30s >"$out" 2>&1 || rc=$?
  result="$(jq -r '.result // "unknown"' "$out" 2>/dev/null || echo unknown)"
  if [ "$rc" -eq 0 ] && [ "$result" = within_boundary ]; then
    record_check "prover:$mode" pass ""
  elif [ "$rc" -eq 1 ]; then
    record_check "prover:$mode" fail "exceeds boundary: $(jq -c '.counterexample' "$out" 2>/dev/null)"
  else
    record_check "prover:$mode" error "prover exit $rc ($result): $(jq -r '.reason // empty' "$out" 2>/dev/null)"
  fi
}

# credential_args <mode> <dummy>: fill CRED_ARGS with --credential flags for
# PROFILE_CREDENTIAL_ENVS: names only in a live run (values come from the
# environment), dummy values otherwise.
credential_args() {
  local mode="$1" dummy="$2" env_name
  CRED_ARGS=()
  for env_name in "${PROFILE_CREDENTIAL_ENVS[@]}"; do
    if [ "$live" = 1 ]; then
      if [ -z "${!env_name:-}" ]; then
        record_check "provider:$mode" error "a live run needs $env_name in the environment"
        return 1
      fi
      CRED_ARGS+=(--credential "$env_name")
    else
      CRED_ARGS+=(--credential "$env_name=$dummy")
    fi
  done
}

# require_allow_checks <mode>: tests/allow.sh must record the must-work checks
# (spec 7.4 step 3); an early exit must not leave the cell green.
require_allow_checks() {
  local mode="$1" name
  for name in version state-writable egress; do
    if ! grep -q "^$name:$mode"$'\t' "$PADDOCK_CHECKS_FILE"; then
      record_check "allow-contract:$mode" error "tests/allow.sh recorded no $name:$mode check"
    fi
  done
  if ! grep -qE "^(upstream-auth-error|live-answer):$mode"$'\t' "$PADDOCK_CHECKS_FILE"; then
    record_check "allow-contract:$mode" error "tests/allow.sh recorded no upstream-auth-error:$mode or live-answer:$mode check"
  fi
}

# deny_suite <run m1|m2> <sandbox> <mode> <provider-file> <dummy>: upload the probe
# and run the shared must-block tests.
deny_suite() {
  local run="$1" sandbox="$2" mode="$3" provider_file="$4" dummy="$5"
  if [ -z "$probe" ]; then
    record_check "deny-$run-setup:$mode" error "the probe is not installed; see probe-install.log"
    return
  fi
  if ! upload_probe "$sandbox" "$probe"; then
    record_check "deny-$run-setup:$mode" error "could not upload and run the probe in $sandbox"
    return
  fi
  PADDOCK_SANDBOX="$sandbox" PADDOCK_AUTH_MODE="$mode" PADDOCK_RUN_MODE="$run" \
    PADDOCK_PROVIDER_FILE="$provider_file" PADDOCK_DUMMY_CREDENTIAL="$dummy" \
    bash "$PADDOCK_ROOT/tests/deny/run.sh" >"$PADDOCK_LOG_DIR/deny-$run-$mode.log" 2>&1 ||
    record_check "deny-$run:$mode" error "tests/deny/run.sh exited non-zero; see deny-$run-$mode.log"
}

# child_mode <mode> <provider-file> <dummy>: must-block run mode 2, in a variant
# sandbox whose provider profile lists the probe in place of the agent. The
# variant deliberately exceeds boundary.yaml, so the prover does not run here.
child_mode() {
  local mode="$1" provider_file="$2" dummy="$3"
  local variant="$PADDOCK_LOG_DIR/variant-$mode.yaml" sandbox provider="paddock-${bundle}-${mode}-child" info
  sandbox="$(sandbox_name "$bundle" "$mode/child")"
  unset VARIANT_PROFILE_ID
  if ! info="$(paddock_py variant-profile "$provider_file" --out "$variant")"; then
    record_check "deny-m2-setup:$mode" error "could not write the variant profile"
    return
  fi
  eval "$info"
  cleanup_mode "$sandbox" "$provider" "$VARIANT_PROFILE_ID"
  if ! oc provider profile import -f "$variant" </dev/null >"$PADDOCK_LOG_DIR/import-$mode-child.log" 2>&1 ||
    ! oc provider create --name "$provider" --type "$VARIANT_PROFILE_ID" "${CRED_ARGS[@]}" \
      </dev/null >"$PADDOCK_LOG_DIR/provider-$mode-child.log" 2>&1; then
    record_check "deny-m2-setup:$mode" error "could not create the variant provider; see import-$mode-child.log"
    cleanup_mode "$sandbox" "$provider" "$VARIANT_PROFILE_ID"
    return
  fi
  if create_sandbox "$sandbox" "$provider" "$mode-child"; then
    deny_suite m2 "$sandbox" "$mode" "$variant" "$dummy"
  else
    record_check "deny-m2-setup:$mode" error "the variant sandbox did not become Ready; see sandbox-$mode-child.log"
  fi
  oc logs "$sandbox" --source all -n 20000 </dev/null >"$PADDOCK_LOG_DIR/sandbox-logs-$mode-child.txt" 2>&1 || true
  cleanup_mode "$sandbox" "$provider" "$VARIANT_PROFILE_ID"
}

run_mode() {
  local mode="$1" provider_file="$2" dummy_credential="$3"
  local sandbox provider="paddock-${bundle}-${mode}" info
  sandbox="$(sandbox_name "$bundle" "$mode")"
  unset PROFILE_ID PROFILE_CREDENTIAL_ENVS
  if ! info="$(paddock_py provider-info "$provider_file")"; then
    record_check "provider:$mode" error "could not read $provider_file"
    return
  fi
  eval "$info"
  cleanup_mode "$sandbox" "$provider" "$PROFILE_ID"

  if oc provider profile lint -f "$provider_file" </dev/null >"$PADDOCK_LOG_DIR/lint-$mode.log" 2>&1; then
    record_check "profile-lint:$mode" pass ""
  else
    record_check "profile-lint:$mode" fail "$(tail -n 5 "$PADDOCK_LOG_DIR/lint-$mode.log")"
    return
  fi
  if ! oc provider profile import -f "$provider_file" </dev/null >"$PADDOCK_LOG_DIR/import-$mode.log" 2>&1; then
    record_check "provider:$mode" error "profile import failed: $(tail -n 3 "$PADDOCK_LOG_DIR/import-$mode.log")"
    return
  fi
  credential_args "$mode" "$dummy_credential" || return
  if oc provider create --name "$provider" --type "$PROFILE_ID" "${CRED_ARGS[@]}" \
    </dev/null >"$PADDOCK_LOG_DIR/provider-$mode.log" 2>&1; then
    record_check "provider:$mode" pass ""
  else
    record_check "provider:$mode" error "$(tail -n 3 "$PADDOCK_LOG_DIR/provider-$mode.log")"
    return
  fi

  if create_sandbox "$sandbox" "$provider" "$mode"; then
    record_check "sandbox:$mode" pass ""
  else
    record_check "sandbox:$mode" fail "the sandbox did not become Ready; see sandbox-$mode.log"
    oc logs "$sandbox" --source all </dev/null >"$PADDOCK_LOG_DIR/sandbox-logs-$mode.txt" 2>&1 || true
    cleanup_mode "$sandbox" "$provider" "$PROFILE_ID"
    return
  fi

  prover_check "$sandbox" "$mode"

  PADDOCK_BUNDLE_DIR="$bundle_dir" PADDOCK_SANDBOX="$sandbox" PADDOCK_AUTH_MODE="$mode" PADDOCK_LIVE="$live" \
    bash "$bundle_dir/tests/allow.sh" >"$PADDOCK_LOG_DIR/allow-$mode.log" 2>&1 ||
    record_check "allow:$mode" error "tests/allow.sh exited non-zero; see allow-$mode.log"
  require_allow_checks "$mode"

  # Must-block run mode 1 uses the same sandbox, after the must-work tests.
  if [ "$live" != 1 ]; then
    deny_suite m1 "$sandbox" "$mode" "$provider_file" "$dummy_credential"
  fi

  oc logs "$sandbox" --source all -n 20000 </dev/null >"$PADDOCK_LOG_DIR/sandbox-logs-$mode.txt" 2>&1 || true
  cleanup_mode "$sandbox" "$provider" "$PROFILE_ID"

  if [ "$live" != 1 ]; then
    child_mode "$mode" "$provider_file" "$dummy_credential"
  fi
}

log "cell $cell"
# PADDOCK_PREINSTALLED=1: an earlier workflow step without secrets installed
# OpenShell and the prover, so third-party installers never see a credential.
preinstalled="${PADDOCK_PREINSTALLED:-0}"
if [ "$preinstalled" = 1 ]; then
  if openshell_is "$version"; then
    record_check setup pass "OpenShell $version (preinstalled)"
  else
    record_check setup error "preinstalled OpenShell is not $version: $(oc --version 2>&1)"
    exit 1
  fi
elif bash "$PADDOCK_ROOT/scripts/ci/install-openshell.sh" "$version" >"$PADDOCK_LOG_DIR/install.log" 2>&1; then
  record_check setup pass "OpenShell $version"
else
  record_check setup error "installing OpenShell $version failed; see install.log"
  exit 1
fi
XDG_RUNTIME_DIR="/run/user/$(id -u)"
export XDG_RUNTIME_DIR
if [ "$version" = "$primary" ] && [ "$preinstalled" != 1 ] &&
  ! bash "$PADDOCK_ROOT/scripts/ci/install-prover.sh" "$version" >"$PADDOCK_LOG_DIR/prover-install.log" 2>&1; then
  record_check prover-setup error "installing openshell-prover failed; see prover-install.log"
fi
if [ "$live" != 1 ]; then
  probe="$(bash "$PADDOCK_ROOT/scripts/ci/install-probe.sh" 2>"$PADDOCK_LOG_DIR/probe-install.log")" || probe=""
fi

if paddock_py validate --root "$PADDOCK_ROOT" "$bundle" >"$PADDOCK_LOG_DIR/validate.log" 2>&1; then
  record_check validate pass ""
else
  record_check validate fail "$(tail -n 5 "$PADDOCK_LOG_DIR/validate.log")"
  exit 1
fi
eval "$(paddock_py bundle-env "$bundle_dir")"
if [ "$PADDOCK_DISTRIBUTION" != upstream ]; then
  record_check image error "distribution '$PADDOCK_DISTRIBUTION' needs image builds, which arrive with the Codex bundle (M4)"
  exit 1
fi

for i in "${!PADDOCK_AUTH_MODES[@]}"; do
  run_mode "${PADDOCK_AUTH_MODES[$i]}" "$bundle_dir/${PADDOCK_PROVIDER_FILES[$i]}" "${PADDOCK_DUMMY_CREDENTIALS[$i]}"
done
