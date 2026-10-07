#!/usr/bin/env bash
# Findings job (spec 7.5): run the must-block suite against NVIDIA's unmodified
# example provider profiles, listed in tests/findings/profiles.tsv.
# Usage: findings.sh <output-dir>
#
# Results may describe an undisclosed weakness, and job logs on a public repo are
# public. So everything goes to files under <output-dir>, which the workflow
# encrypts before upload, and this script prints nothing about outcomes
# (PADDOCK_QUIET=1 silences record_check). It exits 0 unless setup fails.
#
# How a profile is tested: a findings image starts from the OpenCode bundle's
# image and has the static curl probe copied to one listed binary path of every
# profile (globs filled in), so the unmodified profile's rules apply to the probe
# exactly as they would to the agent.
set -uo pipefail
PADDOCK_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PADDOCK_ROOT
# shellcheck source=scripts/ci/lib.sh
source "$PADDOCK_ROOT/scripts/ci/lib.sh"
export PADDOCK_QUIET=1

out="${1:?usage: findings.sh <output-dir>}"
mkdir -p "$out/profiles"
version="$(jq -r '.versions[0]' "$PADDOCK_ROOT/scripts/ci/openshell-versions.json")"
bash "$PADDOCK_ROOT/scripts/ci/install-openshell.sh" "$version" >"$out/install.log" 2>&1 || die "OpenShell install failed"
XDG_RUNTIME_DIR="/run/user/$(id -u)"
export XDG_RUNTIME_DIR
probe="$(bash "$PADDOCK_ROOT/scripts/ci/install-probe.sh" 2>"$out/probe-install.log")" || die "probe install failed"
eval "$(paddock_py bundle-env "$PADDOCK_ROOT/bundles/opencode")"

mapfile -t entries < <(grep -v '^#' "$PADDOCK_ROOT/tests/findings/profiles.tsv" | grep -v '^[[:space:]]*$')
image_dir="$(mktemp -d)"
cp "$probe" "$image_dir/paddock-probe"
{
  echo "FROM $PADDOCK_IMAGE"
  echo "COPY paddock-probe /paddock-probe"
} >"$image_dir/Dockerfile"
base="https://raw.githubusercontent.com/NVIDIA/OpenShell/$version/providers"
for entry in "${entries[@]}"; do
  id="${entry%%$'\t'*}"
  curl -fsSL --retry 3 -o "$out/profiles/$id.yaml" "$base/$id.yaml" || die "could not download $id.yaml"
  path="$(paddock_py probe-binary "$out/profiles/$id.yaml")"
  if [ -n "$path" ]; then
    echo "RUN install -D -m 0755 /paddock-probe $path" >>"$image_dir/Dockerfile"
  fi
done
(cd "$out/profiles" && sha256sum ./*.yaml >SHA256SUMS)
cp "$image_dir/Dockerfile" "$out/findings.Dockerfile"
docker build -t paddock-findings:local "$image_dir" >"$out/image-build.log" 2>&1 || die "findings image build failed"

for entry in "${entries[@]}"; do
  id="${entry%%$'\t'*}"
  args=()
  if [[ "$entry" == *$'\t'* ]]; then
    read -r -a args <<<"${entry#*$'\t'}"
  fi
  profile_file="$out/profiles/$id.yaml"
  PADDOCK_LOG_DIR="$out/$id"
  PADDOCK_CHECKS_FILE="$PADDOCK_LOG_DIR/checks.tsv"
  export PADDOCK_LOG_DIR PADDOCK_CHECKS_FILE
  mkdir -p "$PADDOCK_LOG_DIR"
  : >"$PADDOCK_CHECKS_FILE"
  path="$(paddock_py probe-binary "$profile_file")"
  if [ -z "$path" ]; then
    record_check "findings-setup:$id" skip "the profile lists no binaries, so its rules match no process"
    continue
  fi
  sandbox="$(sandbox_name "fd-$id" findings)"
  provider="paddock-fd-$id"
  openshell sandbox delete "$sandbox" </dev/null >/dev/null 2>&1 || true
  openshell provider delete "$provider" </dev/null >/dev/null 2>&1 || true
  openshell provider profile delete "$id" </dev/null >/dev/null 2>&1 || true
  if ! openshell provider profile import -f "$profile_file" </dev/null >"$PADDOCK_LOG_DIR/import.log" 2>&1 ||
    ! openshell provider create --name "$provider" --type "$id" "${args[@]}" \
      </dev/null >"$PADDOCK_LOG_DIR/provider.log" 2>&1; then
    record_check "findings-setup:$id" error "could not import the profile or create the provider"
  elif ! openshell sandbox create --name "$sandbox" --from paddock-findings:local \
    --policy "$PADDOCK_ROOT/tests/findings/policy.yaml" --provider "$provider" \
    --no-tty --detach </dev/null >"$PADDOCK_LOG_DIR/sandbox.log" 2>&1 ||
    ! wait_until 300 "sandbox $sandbox" sandbox_ready "$sandbox"; then
    record_check "findings-setup:$id" error "the sandbox did not become Ready"
  else
    PADDOCK_SANDBOX="$sandbox" PADDOCK_AUTH_MODE="$id" PADDOCK_RUN_MODE=fd \
      PADDOCK_PROVIDER_FILE="$profile_file" PADDOCK_PROBE="$path" \
      PADDOCK_DUMMY_CREDENTIAL=paddock-findings-dummy PADDOCK_SURVEY=1 \
      bash "$PADDOCK_ROOT/tests/deny/run.sh" >"$PADDOCK_LOG_DIR/deny.log" 2>&1 ||
      record_check "findings-run:$id" error "tests/deny/run.sh exited non-zero"
  fi
  openshell logs "$sandbox" --source all -n 20000 </dev/null >"$PADDOCK_LOG_DIR/sandbox-logs.txt" 2>&1 || true
  openshell sandbox delete "$sandbox" </dev/null >/dev/null 2>&1 || true
  openshell provider delete "$provider" </dev/null >/dev/null 2>&1 || true
  openshell provider profile delete "$id" </dev/null >/dev/null 2>&1 || true
done
journalctl --user -u openshell-gateway --no-pager -n 2000 >"$out/gateway.log" 2>&1 || true
echo "findings run complete"
