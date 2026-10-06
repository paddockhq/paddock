#!/usr/bin/env bash
# Run every check for one CI matrix cell: one bundle on one OpenShell release.
# Usage: run-cell.sh <bundle> <openshell-tag> <runner-label> [--live]
# Writes results/<bundle>--<tag>--<runner>.json and keeps logs under
# results/logs/<bundle>--<tag>--<runner>/. Exits 0 only when the cell passes.
# --live uses real credentials from the environment instead of dummy values.
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
PADDOCK_LOG_DIR="$results_dir/logs/$cell"
PADDOCK_CHECKS_FILE="$PADDOCK_LOG_DIR/checks.tsv"
export PADDOCK_LOG_DIR PADDOCK_CHECKS_FILE
mkdir -p "$PADDOCK_LOG_DIR"
: >"$PADDOCK_CHECKS_FILE"
primary="$(jq -r '.versions[0]' "$PADDOCK_ROOT/scripts/ci/openshell-versions.json")"
prover="$HOME/.local/bin/openshell-prover"

finish() {
  journalctl --user -u openshell-gateway --no-pager -n 500 >"$PADDOCK_LOG_DIR/gateway.log" 2>&1 || true
  paddock_py result --bundle "$bundle" --openshell-version "$version" --runner "$runner" \
    --checks "$PADDOCK_CHECKS_FILE" --out "$results_dir/$cell.json"
  exit $?
}
trap finish EXIT

# Order matters: OpenShell refuses to delete a provider that a sandbox uses, or a
# profile that a provider uses. Each delete exits 0 when the object is missing.
cleanup_mode() {
  local sandbox="$1" provider="$2" profile="$3"
  openshell sandbox delete "$sandbox" </dev/null >/dev/null 2>&1 || true
  openshell provider delete "$provider" </dev/null >/dev/null 2>&1 || true
  openshell provider profile delete "$profile" </dev/null >/dev/null 2>&1 || true
}

# No --auto-providers/--no-auto-providers flag: with stdin closed, a missing
# provider then fails the create instead of being skipped with a warning.
create_sandbox() {
  local sandbox="$1" provider="$2" mode="$3"
  openshell sandbox create --name "$sandbox" --from "$PADDOCK_IMAGE" \
    --policy "$bundle_dir/policy.yaml" --provider "$provider" \
    "${PADDOCK_ENV_ARGS[@]}" --no-tty --detach </dev/null >"$PADDOCK_LOG_DIR/sandbox-$mode.log" 2>&1 &&
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
  if ! openshell sandbox get "$sandbox" --policy-only </dev/null >"$candidate" 2>>"$PADDOCK_LOG_DIR/sandbox-$mode.log"; then
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

run_mode() {
  local mode="$1" provider_file="$2" dummy_credential="$3"
  local sandbox provider="paddock-${bundle}-${mode}"
  sandbox="$(sandbox_name "$bundle" "$mode")"
  eval "$(paddock_py provider-info "$provider_file")"
  cleanup_mode "$sandbox" "$provider" "$PROFILE_ID"

  if openshell provider profile lint -f "$provider_file" </dev/null >"$PADDOCK_LOG_DIR/lint-$mode.log" 2>&1; then
    record_check "profile-lint:$mode" pass ""
  else
    record_check "profile-lint:$mode" fail "$(tail -n 5 "$PADDOCK_LOG_DIR/lint-$mode.log")"
    return
  fi
  if ! openshell provider profile import -f "$provider_file" </dev/null >"$PADDOCK_LOG_DIR/import-$mode.log" 2>&1; then
    record_check "provider:$mode" error "profile import failed: $(tail -n 3 "$PADDOCK_LOG_DIR/import-$mode.log")"
    return
  fi
  local cred_args=() env_name
  for env_name in "${PROFILE_CREDENTIAL_ENVS[@]}"; do
    if [ "$live" = 1 ]; then
      if [ -z "${!env_name:-}" ]; then
        record_check "provider:$mode" error "a live run needs $env_name in the environment"
        return
      fi
      cred_args+=(--credential "$env_name")
    else
      cred_args+=(--credential "$env_name=$dummy_credential")
    fi
  done
  if openshell provider create --name "$provider" --type "$PROFILE_ID" "${cred_args[@]}" \
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
    openshell logs "$sandbox" --source all </dev/null >"$PADDOCK_LOG_DIR/sandbox-logs-$mode.txt" 2>&1 || true
    cleanup_mode "$sandbox" "$provider" "$PROFILE_ID"
    return
  fi

  prover_check "$sandbox" "$mode"

  PADDOCK_BUNDLE_DIR="$bundle_dir" PADDOCK_SANDBOX="$sandbox" PADDOCK_AUTH_MODE="$mode" PADDOCK_LIVE="$live" \
    bash "$bundle_dir/tests/allow.sh" >"$PADDOCK_LOG_DIR/allow-$mode.log" 2>&1 ||
    record_check "allow:$mode" error "tests/allow.sh exited non-zero; see allow-$mode.log"

  openshell logs "$sandbox" --source all </dev/null >"$PADDOCK_LOG_DIR/sandbox-logs-$mode.txt" 2>&1 || true
  cleanup_mode "$sandbox" "$provider" "$PROFILE_ID"
}

log "cell $cell"
# PADDOCK_PREINSTALLED=1: an earlier workflow step without secrets installed
# OpenShell and the prover, so third-party installers never see a credential.
preinstalled="${PADDOCK_PREINSTALLED:-0}"
if [ "$preinstalled" = 1 ]; then
  if openshell_is "$version"; then
    record_check setup pass "OpenShell $version (preinstalled)"
  else
    record_check setup error "preinstalled OpenShell is not $version: $(openshell --version 2>&1)"
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

if paddock_py validate --root "$PADDOCK_ROOT" "$bundle" >"$PADDOCK_LOG_DIR/validate.log" 2>&1; then
  record_check validate pass ""
else
  record_check validate fail "$(tail -n 5 "$PADDOCK_LOG_DIR/validate.log")"
  exit 1
fi
eval "$(paddock_py bundle-env "$bundle_dir")"
if [ "$PADDOCK_DISTRIBUTION" != upstream ]; then
  record_check image error "distribution '$PADDOCK_DISTRIBUTION' needs image builds, which arrive with the Codex bundle (Plan 2)"
  exit 1
fi

for i in "${!PADDOCK_AUTH_MODES[@]}"; do
  run_mode "${PADDOCK_AUTH_MODES[$i]}" "$bundle_dir/${PADDOCK_PROVIDER_FILES[$i]}" "${PADDOCK_DUMMY_CREDENTIALS[$i]}"
done
