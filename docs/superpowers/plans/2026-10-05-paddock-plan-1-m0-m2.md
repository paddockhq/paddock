# PadDock Plan 1 (M0–M2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that OpenShell runs on GitHub's free runners (M0), build the CI harness that tests bundles against real OpenShell gateways (M1), and land an OpenCode bundle that passes that harness (M2).

**Architecture:**
- **One GitHub Actions job per cell.** A cell is one bundle × one OpenShell release × one runner architecture.
- **Each job installs OpenShell the way users do.** It uses NVIDIA's own installer, pinned to a release.
- **`scripts/ci/run-cell.sh` drives the stock `openshell` CLI.** For each cell it:
  1. creates the provider and the sandbox;
  2. runs `openshell-prover` to check that the gateway-composed policy stays within the bundle's `boundary.yaml`;
  3. runs the bundle's must-work tests;
  4. writes one result file.
- **Testable logic lives in Python; bash stays a thin driver.** The bundle schema, matrix, log parsing, results and report live in a small package, `scripts/paddock`, so they can be unit-tested.

**Tech Stack:**
- GitHub Actions on `ubuntu-24.04` and `ubuntu-24.04-arm`
- bash 5
- Python 3.12 with PyYAML 6.0.3, jsonschema 4.26.0 and pytest 9.1.1
- OpenShell v0.1.2 and v0.0.116 (the `openshell` CLI and `openshell-prover`)
- OpenCode image `ghcr.io/anomalyco/opencode:2.0.21`
- `jq` and `shellcheck`, both preinstalled on the runner image

**Spec:** `docs/superpowers/specs/2026-10-05-paddock-design.md`

**Scope.** This is Plan 1 of several and covers milestones M0–M2 from spec §10. Each later plan is written after the previous one lands:
- **M3:** the shared must-block suite and the findings job
- **M4:** the Codex bundle and image builds
- **M5:** the Claude Code bundle
- **M6:** releases, signing, Renovate, committing `COMPATIBILITY.md`, and auto-opening issues for nightly failures
- **M7:** CODEOWNERS, SECURITY.md, CONTRIBUTING.md, the full README, and outreach

**Spec refinements found during research.** The tasks below already apply all of them.
1. **Two new optional fields in `bundle.yaml`:**
   - `env`: non-secret variables passed with `--env`. Upstream images cannot bake in the R3 settings, so the bundle has to pass them.
   - `openshell_min_version`: an OpenShell version floor, used only if a bundle cannot work on the N-1 release.
2. **R3's OpenCode list shrinks.** OpenCode 2.x reads only `OPENCODE_DISABLE_MODELS_FETCH` and `OPENCODE_DISABLE_AUTOUPDATE`. `OPENCODE_DISABLE_LSP_DOWNLOAD`, `_SHARE` and `_DEFAULT_PLUGINS` exist only in 1.x, so they do nothing in 2.x.
3. **Q1 is answered: no policy-composition code is needed.** `openshell sandbox get <name> --policy-only` prints the gateway-composed effective policy, that is, the base policy plus `_provider_*` rules.
4. **The prover runs only on the primary (newest) OpenShell release.** v0.0.116 ships no prover, so N-1 cells record the prover check as `skip`.
5. **The repository is public from Task 1,** because the free arm64 runners serve only public repositories.

## Global Constraints

- **Repository:** `github.com/paddockhq/paddock`, public, default branch `main`.
- **License and sign-off:** Apache-2.0. Every commit is signed off (`git commit -s`) for DCO.
- **Runners:** `ubuntu-24.04` and `ubuntu-24.04-arm` only. Never `ubuntu-latest`, which moves to Ubuntu 26.04 in November 2026.
- **OpenShell versions under test:** `v0.1.2` (primary, the latest minor line) and `v0.0.116` (the N-1 line). They are listed newest first in `scripts/ci/openshell-versions.json`.
- **OpenShell install:** use only NVIDIA's installer, fetched from the same tag: `https://raw.githubusercontent.com/NVIDIA/OpenShell/<tag>/install.sh`, run with `OPENSHELL_VERSION=<tag>` and `OPENSHELL_INSTALL_METHOD=deb`.
- **Compute driver:** pin the gateway to Docker by setting `OPENSHELL_COMPUTE_DRIVER=docker` (read by v0.1.x) and `OPENSHELL_DRIVERS=docker` (read by v0.0.x) in the systemd user environment. The runners also have Podman 4.9.3, and OpenShell auto-detects Podman before Docker.
- **Pinned actions:** always reference actions by full SHA, with the version in a comment:
  - `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1`
  - `actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0`
  - `actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1`
  - `actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1`
- **Workflow permissions:** every workflow sets `permissions: contents: read` at the top level, and every checkout uses `persist-credentials: false`.
- **Matrix values in workflows:** pass them to `run:` steps through `env:`, never by interpolating `${{ }}` inside the script text.
- **Python:** Python 3.12 in CI (`actions/setup-python` with `python-version: '3.12'`). Dependencies are pinned in `requirements-dev.txt`.
- **Line endings:** every file uses LF (enforced by `.gitattributes`). The maintainer works on Windows and every script runs on Linux.
- **Secrets:** a secret reaches a sandbox only through `openshell provider create --credential KEY`. `--env` carries only non-secret values.
- **Stdin:** every `openshell` call in a script closes stdin (`</dev/null`). Otherwise the CLI reads piped stdin until it ends.
- **Upstream images are pinned by digest.** OpenCode: `ghcr.io/anomalyco/opencode:2.0.21@sha256:6d3cebbaaeed11b9dd1ea6d2ca8a3ec17eb548c5aed37e17c7ae80fd8b2f22b2`.
- **Policy rules:** bundle files follow rules R1–R6 in spec §6.2.
- **Local commands:** on the maintainer's Windows machine, run them in Git Bash from the repository root, with the virtual environment first on `PATH`:
  - Windows: prefix each command with `PATH="$PWD/.venv/Scripts:$PATH"`.
  - Linux or macOS: run `source .venv/bin/activate` first.

  Commands in this plan are written as plain `python ...`.
- **Pushing:** pushing branches and pull requests to `paddockhq/paddock` needs the maintainer's go-ahead once, in Task 1. This plan never force-pushes and never deletes `main`.

## Review Focus

1. **A file saved with CRLF line endings on Windows.**
   - *What goes wrong:* bash fails on Linux with `$'\r': command not found`, far from the cause.
   - *Expected:* `paddock validate` rejects CRLF in any bundle script or YAML file, with a message naming the file.
   - *Test:* `test_crlf_line_endings_are_rejected` in Task 4.
2. **OpenShell v0.0.116 lacks a flag the harness uses.** For example, `sandbox exec` there has no `--no-login-shell`.
   - *Expected:* the runner reads `--help` to find the supported flags and still runs.
   - *Test:* `test_exec_flags_follow_cli_help` in Task 8.
3. **`openshell status` exits 0 while the gateway is disconnected.**
   - *Expected:* the install script keeps waiting, then fails with diagnostics instead of continuing.
   - *Test:* `test_gateway_connected_rejects_disconnected_status` in Task 8.
4. **Log lines in less common shapes:** IPv6 hosts in brackets, `NET:REFUSE ... /tcp`, the ISO-timestamp file format, and `ALLOWED` lines.
   - *Expected:* the parser extracts host, port, binary and action, or ignores the line. It never crashes or attributes an event to the wrong host.
   - *Tests:* `test_parses_ipv6_and_refuse_lines` and `test_parses_file_format_lines` in Task 6.
5. **A cell job dies before writing its result file,** for example because the runner was lost or setup crashed.
   - *Expected:* the report shows that cell as `not run`, and the failed job keeps the run red. The report must not crash or hide the gap.
   - *Test:* `test_missing_result_is_reported_as_not_run` in Task 7.

---

## File Structure

| Path | Responsibility | Task |
|---|---|---|
| `.gitattributes` | Force LF line endings | 1 |
| `scripts/ci/lib.sh` | Shared bash helpers: logging, waiting, gateway check, exec flags, check recording | 2, 8 |
| `scripts/ci/install-openshell.sh` | Install a pinned OpenShell release and wait for its gateway | 2 |
| `.github/workflows/m0-feasibility.yml` | Throwaway M0 check, deleted at the end of Task 2 | 2 |
| `docs/decisions/0001-ci-runners.md` | M0 result and decision | 2 |
| `LICENSE`, `NOTICE`, `README.md`, `.gitignore` | Project basics | 3 |
| `pyproject.toml`, `requirements-dev.txt` | pytest config and pinned dev dependencies | 3 |
| `scripts/paddock/__init__.py`, `scripts/paddock/__main__.py` | Python CLI entry point (`python -m paddock`) | 3 |
| `scripts/paddock/bundle.schema.json`, `scripts/paddock/bundle.py` | `bundle.yaml` schema, loading, cross-file checks, shell export | 4 |
| `scripts/ci/openshell-versions.json`, `scripts/paddock/matrix.py` | Versions under test; the CI matrix | 5 |
| `scripts/paddock/logs.py` | Parse OCSF policy events from `openshell logs` | 6 |
| `scripts/paddock/results.py` | Per-cell result files and the compatibility report | 7 |
| `scripts/ci/install-prover.sh`, `scripts/ci/run-cell.sh` | Prover install; the per-cell test runner | 8 |
| `.github/workflows/ci.yml` | Unit checks, matrix plan, cell jobs, report | 9 |
| `bundles/opencode/*` | The OpenCode bundle | 10 |
| `.github/workflows/live-smoke.yml` | Weekly real-request smoke test | 11 |
| `tests/unit/*` | Unit tests for every Python module and bash helper | 3–8 |

---

### Task 1: Publish the repository on GitHub

**Files:**
- Create: `.gitattributes`

**Interfaces:**
- Consumes: the local repository at `D:\Project\NewShell` (spec commit `1579dea` on `main`).
- Produces: remote `origin` = `https://github.com/paddockhq/paddock.git`; `main` pushed; LF line endings enforced.

- [ ] **Step 1 (maintainer, browser): Create the organization and repository.**
  1. Create the organization `paddockhq` on the Free plan at https://github.com/account/organizations/new.
  2. Create the repository `paddockhq/paddock`: public, with no README, license, or .gitignore. The local repository already has history.
  3. In the repository, open Settings → Actions → General → Actions permissions. Choose "Allow paddockhq, and select non-paddockhq, actions and reusable workflows", tick only "Allow actions created by GitHub", and save. Every action this plan uses is under `actions/`.

- [ ] **Step 2 (maintainer, PowerShell): Install the GitHub CLI and sign in.**

```powershell
winget install --id GitHub.cli --source winget
```

Open a new terminal so `gh` is on `PATH`, then:

```powershell
gh auth login --hostname github.com --git-protocol https --web
gh auth status
```

Expected: `Logged in to github.com account <your account>`.

- [ ] **Step 3: Enforce LF line endings.**

Create `.gitattributes`:

```gitattributes
* text=auto eol=lf
```

Then run:

```bash
git add .gitattributes
git add --renormalize .
git status --short
git commit -s -m "Enforce LF line endings"
```

Expected: `git status` lists `.gitattributes`, possibly with the renormalized spec file, and the commit succeeds.

- [ ] **Step 4: Ask the maintainer to approve pushing.**

Ask exactly: "OK to push `main` to https://github.com/paddockhq/paddock now, and to push this plan's branches and open pull requests there as later tasks need them?" Continue only after a yes.

- [ ] **Step 5: Push and verify.**

```bash
git remote add origin https://github.com/paddockhq/paddock.git
git push -u origin main
gh repo view paddockhq/paddock --json visibility,defaultBranchRef --jq '.visibility + " " + .defaultBranchRef.name'
```

Expected output of the last command: `PUBLIC main`.

---

### Task 2: M0 — prove that OpenShell runs on free runners

**Files:**
- Create: `scripts/ci/lib.sh`
- Create: `scripts/ci/install-openshell.sh`
- Create: `.github/workflows/m0-feasibility.yml` (deleted in Step 8)
- Create: `docs/decisions/0001-ci-runners.md`

**Interfaces:**
- Consumes: the `origin` remote from Task 1.
- Produces:
  - `scripts/ci/lib.sh` with these functions:
    - `log MESSAGE`
    - `die MESSAGE`: logs the message and exits 1
    - `wait_until TIMEOUT_SECONDS DESCRIPTION COMMAND...`: returns 0 as soon as the command succeeds, or 1 after the timeout
    - `gateway_connected`: returns 0 only for a connected gateway
  - `scripts/ci/install-openshell.sh <tag>`:
    - exits 0 only when the gateway reports connected;
    - when run in Actions, appends `XDG_RUNTIME_DIR` and `DBUS_SESSION_BUS_ADDRESS` to `$GITHUB_ENV`.

This task is a feasibility check. The workflow is thrown away at the end. `lib.sh` and `install-openshell.sh` are kept, and Task 8 extends them. If v0.1.2 fails on `ubuntu-24.04`, the plan stops at Step 7.

- [ ] **Step 1: Create the branch.**

```bash
git switch -c m0-feasibility
```

- [ ] **Step 2: Create `scripts/ci/lib.sh`.**

```bash
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
```

- [ ] **Step 3: Create `scripts/ci/install-openshell.sh`.**

```bash
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
```

- [ ] **Step 4: Create `.github/workflows/m0-feasibility.yml`.**

```yaml
name: m0-feasibility
# Throwaway check for milestone M0 (spec section 10). Deleted once recorded.
on:
  push:
    branches: [m0-feasibility]
  workflow_dispatch:

permissions:
  contents: read

jobs:
  probe:
    strategy:
      fail-fast: false
      matrix:
        runner: [ubuntu-24.04, ubuntu-24.04-arm]
        openshell: [v0.1.2, v0.0.116]
    runs-on: ${{ matrix.runner }}
    timeout-minutes: 30
    env:
      RUNNER_LABEL: ${{ matrix.runner }}
      OPENSHELL_TAG: ${{ matrix.openshell }}
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false

      - name: Probe the runner
        run: |
          {
            echo "### $RUNNER_LABEL / OpenShell $OPENSHELL_TAG"
            echo '```'
            echo "kernel:    $(uname -r)"
            echo "lsm:       $(cat /sys/kernel/security/lsm)"
            echo "cgroup fs: $(stat -fc %T /sys/fs/cgroup)"
            echo "docker:    $(docker version --format '{{.Server.Version}}')"
            echo '```'
          } | tee -a "$GITHUB_STEP_SUMMARY"

      - name: Install OpenShell
        run: bash scripts/ci/install-openshell.sh "$OPENSHELL_TAG"

      - name: A sandbox blocks unlisted egress
        run: |
          openshell sandbox create --name m0 --from docker.io/curlimages/curl:latest \
            --no-tty --detach </dev/null
          phase=""
          for _ in $(seq 1 60); do
            phase="$(openshell sandbox get m0 -o json </dev/null 2>/dev/null | jq -r '.phase // empty' 2>/dev/null || true)"
            case "$phase" in Ready | *_READY) break ;; esac
            sleep 5
          done
          echo "phase: $phase" | tee -a "$GITHUB_STEP_SUMMARY"
          case "$phase" in Ready | *_READY) ;; *) exit 1 ;; esac
          if openshell sandbox exec -n m0 --no-tty -- curl -sS --max-time 15 https://example.com </dev/null; then
            echo "::error::curl reached example.com; expected the policy to block it"
            exit 1
          fi
          echo "egress blocked: yes" >> "$GITHUB_STEP_SUMMARY"
          sleep 3
          openshell logs m0 --source sandbox </dev/null > m0-logs.txt 2>&1 || true
          cat m0-logs.txt
          if grep -qE 'NET:[A-Z]+ .*DENIED .*-> example\.com:443' m0-logs.txt; then
            echo "denial logged: yes" >> "$GITHUB_STEP_SUMMARY"
          else
            echo "denial logged: no" >> "$GITHUB_STEP_SUMMARY"
          fi

      - name: Gateway diagnostics
        if: failure()
        run: |
          systemctl --user status openshell-gateway --no-pager || true
          journalctl --user -u openshell-gateway --no-pager -n 300 || true
```

- [ ] **Step 5: Commit, push, and watch the run.**

```bash
git add scripts/ci/lib.sh scripts/ci/install-openshell.sh .github/workflows/m0-feasibility.yml
git commit -s -m "Add M0 runner feasibility check"
git push -u origin m0-feasibility
run_id=""
for _ in $(seq 1 30); do
  run_id="$(gh run list --repo paddockhq/paddock --workflow m0-feasibility.yml --branch m0-feasibility --limit 1 --json databaseId --jq '.[0].databaseId')"
  [ -n "$run_id" ] && break
  sleep 5
done
echo "run: https://github.com/paddockhq/paddock/actions/runs/$run_id"
gh run watch "$run_id" --repo paddockhq/paddock --exit-status
```

Expected: four jobs run, one for each runner and OpenShell version pair. If any fail, read the failure:

```bash
gh run view "$run_id" --repo paddockhq/paddock --log-failed
```

- [ ] **Step 6: Collect the results.**

```bash
gh run view "$run_id" --repo paddockhq/paddock --json jobs --jq '.jobs[] | .name + ": " + .conclusion'
```

Open the run page and copy each job's summary: kernel, LSM list, cgroup filesystem, Docker version, phase, "egress blocked" and "denial logged".

- [ ] **Step 7: Decide.**

| Observation | Decision |
|---|---|
| All four jobs passed | Free runners work. Continue to Step 8. |
| v0.1.2 passed on both runners; v0.0.116 failed | Continue. Task 5 lists only `v0.1.2` in `openshell-versions.json`, and the ADR records the v0.0.116 failure. |
| v0.1.2 passed on `ubuntu-24.04` but failed on `ubuntu-24.04-arm` | Continue. Task 5 sets `RUNNERS = ("ubuntu-24.04",)`, and the ADR records the arm64 failure. |
| v0.1.2 failed on `ubuntu-24.04` | **STOP.** Write the ADR with the failure, push it, and hand back to the maintainer. A self-hosted fallback (spec §7.1) needs its own design. Do not start Task 3. |

"Denial logged: no" while "egress blocked: yes" does not block this plan. Record it in the ADR, because it changes how M3's must-block tests detect denials.

- [ ] **Step 8: Record the decision, remove the workflow, and merge.**

Create `docs/decisions/0001-ci-runners.md`. Fill each `yes`/`no` cell, the measured values and the date from Step 6. For the Decision section, copy exactly one of the sentences listed under "Choose one".

```markdown
# 0001: Run CI on GitHub's free hosted runners

- Status: accepted
- Date: (date of the run, YYYY-MM-DD)
- Run: https://github.com/paddockhq/paddock/actions/runs/(run id)

## Context

Spec §7.1 plans CI on free GitHub-hosted runners. OpenShell's own Docker-driver
tests run on larger runners, so it was unproven that free runners can run
OpenShell at all (spec Q4).

## Result

| Runner | OpenShell | Gateway connected | Sandbox Ready | Egress blocked | Denial logged |
|---|---|---|---|---|---|
| ubuntu-24.04 | v0.1.2 | | | | |
| ubuntu-24.04 | v0.0.116 | | | | |
| ubuntu-24.04-arm | v0.1.2 | | | | |
| ubuntu-24.04-arm | v0.0.116 | | | | |

Measured on the runners: kernel ..., LSM list ..., cgroup filesystem ..., Docker ...

## Decision

Choose one:
- Use the free `ubuntu-24.04` and `ubuntu-24.04-arm` runners for every CI job.
- Use only the free `ubuntu-24.04` runner; arm64 failed because (reason from the log).
- Test only OpenShell v0.1.2 for now; v0.0.116 failed because (reason from the log).
- Free runners cannot run OpenShell v0.1.2 because (reason from the log); a self-hosted fallback is needed before Plan 1 continues.
```

Then remove the workflow and merge:

```bash
git rm .github/workflows/m0-feasibility.yml
git add docs/decisions/0001-ci-runners.md
git commit -s -m "Record M0 result and remove the feasibility workflow"
git switch main
git merge --ff-only m0-feasibility
git push origin main
git push origin --delete m0-feasibility
```

Expected: `main` on GitHub contains `scripts/ci/lib.sh`, `scripts/ci/install-openshell.sh` and the ADR, and no `m0-feasibility.yml`.

---

### Task 3: Project scaffolding and the Python CLI entry point

**Files:**
- Create: `requirements-dev.txt`, `pyproject.toml`, `.gitignore`, `LICENSE`, `NOTICE`, `README.md`
- Create: `scripts/paddock/__init__.py`, `scripts/paddock/__main__.py`
- Test: `tests/unit/test_cli.py`

**Interfaces:**
- Produces:
  - `paddock.__main__.main(argv: list[str] | None = None) -> int`.
  - `paddock.__main__.MODULES`, a tuple of modules. Each module defines `add_commands(sub)`, where `sub` is the subparsers object from `argparse`. Every subcommand it registers sets `handler=<function(args) -> int>` with `set_defaults`.

- [ ] **Step 1: Create the branch and the dependency list.**

```bash
git switch main
git pull --ff-only
git switch -c m1-harness
```

Create `requirements-dev.txt`:

```text
PyYAML==6.0.3
jsonschema==4.26.0
pytest==9.1.1
```

Create `pyproject.toml`:

```toml
[tool.pytest.ini_options]
pythonpath = ["scripts"]
testpaths = ["tests/unit"]
```

Create the virtual environment and install:

```bash
python -m venv .venv
PATH="$PWD/.venv/Scripts:$PATH" python -m pip install -r requirements-dev.txt
```

Expected: `Successfully installed ... PyYAML-6.0.3 ... jsonschema-4.26.0 ... pytest-9.1.1`.

- [ ] **Step 2: Write the failing test.**

Create `tests/unit/test_cli.py`:

```python
import pytest

from paddock.__main__ import main


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "usage: paddock" in capsys.readouterr().out


def test_unknown_command_is_a_usage_error():
    with pytest.raises(SystemExit) as exc:
        main(["no-such-command"])
    assert exc.value.code == 2
```

- [ ] **Step 3: Run it to verify it fails.**

Run: `python -m pytest tests/unit/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paddock'`.

- [ ] **Step 4: Write the entry point.**

Create `scripts/paddock/__init__.py`:

```python
"""PadDock CI helpers."""
```

Create `scripts/paddock/__main__.py`:

```python
"""Command-line entry point: python -m paddock <command> ..."""

import argparse
import sys

MODULES = ()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="paddock", description="PadDock CI helpers")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")
    for module in MODULES:
        module.add_commands(sub)
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests to verify they pass.**

Run: `python -m pytest tests/unit/test_cli.py -v`
Expected: `2 passed`.

- [ ] **Step 6: Add the project files.**

```bash
curl -fsSL https://www.apache.org/licenses/LICENSE-2.0.txt -o LICENSE
head -n 3 LICENSE
```

Expected: the first lines contain `Apache License` and `Version 2.0, January 2004`.

Create `NOTICE`:

```text
PadDock
Copyright 2026 The PadDock Authors

This product includes files derived from NVIDIA OpenShell example provider
profiles (https://github.com/NVIDIA/OpenShell/tree/main/providers),
Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES, licensed under the
Apache License, Version 2.0. Derived files keep NVIDIA's SPDX copyright line.
```

Create `.gitignore`:

```gitignore
__pycache__/
.pytest_cache/
.venv/
results/
```

Create `README.md`:

```markdown
# PadDock

Tested, least-privilege bundles for running AI coding agents inside
[NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) sandboxes.

**Status:** early development. Not ready for use yet.

PadDock is an independent community project. It is not affiliated with or
endorsed by NVIDIA.

## Layout

- `bundles/<agent>/`: one bundle per agent (image reference, sandbox policy,
  boundary policy, provider profiles, tests).
- `scripts/paddock/`: Python helpers used by CI (`python -m paddock --help`).
- `scripts/ci/`: bash scripts that run bundles against real OpenShell gateways.
- `docs/`: design spec, plans, and decision records.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
```

- [ ] **Step 7: Commit.**

```bash
git add requirements-dev.txt pyproject.toml .gitignore LICENSE NOTICE README.md scripts/paddock tests/unit/test_cli.py
git commit -s -m "Add project scaffolding and the paddock CLI entry point"
```

---

### Task 4: Bundle schema, loader, and shell export

**Files:**
- Create: `scripts/paddock/bundle.schema.json`
- Create: `scripts/paddock/bundle.py`
- Modify: `scripts/paddock/__main__.py` (register the module)
- Test: `tests/unit/conftest.py`, `tests/unit/test_bundle.py`

**Interfaces:**
- Consumes: `paddock.__main__.MODULES` (Task 3).
- Produces:
  - `paddock.bundle.BundleError(Exception)`: the message lists every problem found.
  - `load_bundle(bundle_dir: str | Path) -> dict`: the parsed `bundle.yaml` plus the key `"dir"` (a `Path`).
  - `discover_bundles(bundles_root: str | Path) -> list[str]`: sorted names of folders that contain a `bundle.yaml`.
  - `provider_info(path: str | Path) -> dict`: `{"id": str, "credential_envs": list[str]}`, where `credential_envs` holds the first env var of each credential.
  - `shell_assignments(meta: dict) -> str`: bash assignments for these variables:
    - `PADDOCK_NAME`, `PADDOCK_IMAGE`, `PADDOCK_DISTRIBUTION`, `PADDOCK_OPENSHELL_MIN_VERSION`
    - arrays `PADDOCK_COMMAND`, `PADDOCK_VERSION_COMMAND`, `PADDOCK_ENV_ARGS`, `PADDOCK_AUTH_MODES`, `PADDOCK_PROVIDER_FILES` (the last two are parallel arrays)
  - CLI commands:
    - `python -m paddock validate [--root DIR] [NAME ...]`
    - `python -m paddock bundle-env BUNDLE_DIR`: prints `shell_assignments`
    - `python -m paddock provider-info FILE`: prints `PROFILE_ID=...` and `PROFILE_CREDENTIAL_ENVS=(...)`

- [ ] **Step 1: Write the test fixtures.**

Create `tests/unit/conftest.py`:

```python
import copy

import pytest
import yaml

VALID_META = {
    "schema": 1,
    "name": "demo",
    "agent": {
        "display_name": "Demo Agent",
        "homepage": "https://example.com/demo",
        "license": "MIT",
        "version": "1.2.3",
    },
    "distribution": "upstream",
    "image": "ghcr.io/example/demo:1.2.3@sha256:" + "a" * 64,
    "revision": 1,
    "command": ["demo"],
    "version_command": ["demo", "--version"],
    "env": {"DEMO_DISABLE_UPDATES": "1"},
    "auth": [{"mode": "api-key", "provider_file": "providers/demo-apikey.yaml"}],
}

DEFAULT_FILES = {
    "policy.yaml": "version: 1\n",
    "boundary.yaml": "version: 1\n",
    "providers/demo-apikey.yaml": "id: demo-apikey\n",
    "tests/allow.sh": "#!/usr/bin/env bash\n",
    "README.md": "# demo\n",
}


@pytest.fixture
def valid_meta():
    return copy.deepcopy(VALID_META)


@pytest.fixture
def make_bundle(tmp_path):
    """Write tmp_path/bundles/<name>/ and return its path.

    files maps relative paths to content; a value of None means "do not create".
    Files are written with newline="" so Windows does not turn LF into CRLF.
    """

    def _make(meta=None, files=None, name=None):
        meta = copy.deepcopy(VALID_META if meta is None else meta)
        bundle_dir = tmp_path / "bundles" / (name or meta.get("name", "demo"))
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "bundle.yaml").write_text(
            yaml.safe_dump(meta, sort_keys=False), encoding="utf-8", newline=""
        )
        contents = dict(DEFAULT_FILES)
        if meta.get("distribution") in ("built", "dockerfile-only"):
            contents["Dockerfile"] = "FROM scratch\n"
        contents.update(files or {})
        for rel, content in contents.items():
            if content is None:
                continue
            path = bundle_dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="")
        return bundle_dir

    return _make
```

- [ ] **Step 2: Write the failing tests.**

Create `tests/unit/test_bundle.py`:

```python
import copy

import pytest

from paddock.__main__ import main
from paddock.bundle import (
    BundleError,
    discover_bundles,
    load_bundle,
    provider_info,
    shell_assignments,
)


def test_valid_upstream_bundle_loads(make_bundle):
    bundle_dir = make_bundle()
    meta = load_bundle(bundle_dir)
    assert meta["name"] == "demo"
    assert meta["dir"] == bundle_dir


def test_missing_required_field_is_reported(make_bundle, valid_meta):
    del valid_meta["image"]
    with pytest.raises(BundleError, match="'image' is a required property"):
        load_bundle(make_bundle(valid_meta))


def test_unknown_field_is_rejected(make_bundle, valid_meta):
    valid_meta["imagee"] = "typo"
    with pytest.raises(BundleError, match="Additional properties are not allowed"):
        load_bundle(make_bundle(valid_meta))


def test_env_names_cannot_use_the_openshell_prefix(make_bundle, valid_meta):
    valid_meta["env"] = {"OPENSHELL_GATEWAY": "x"}
    with pytest.raises(BundleError, match="OPENSHELL_GATEWAY"):
        load_bundle(make_bundle(valid_meta))


def test_name_must_match_folder(make_bundle, valid_meta):
    with pytest.raises(BundleError, match="does not match folder 'other'"):
        load_bundle(make_bundle(valid_meta, name="other"))


def test_upstream_image_needs_a_digest(make_bundle, valid_meta):
    valid_meta["image"] = "ghcr.io/example/demo:1.2.3"
    with pytest.raises(BundleError, match="pinned by digest"):
        load_bundle(make_bundle(valid_meta))


def test_built_image_is_a_bare_repository(make_bundle, valid_meta):
    valid_meta["distribution"] = "built"
    valid_meta["image"] = "ghcr.io/paddockhq/demo:1.0"
    with pytest.raises(BundleError, match="without a tag or digest"):
        load_bundle(make_bundle(valid_meta))


def test_built_bundle_needs_a_dockerfile(make_bundle, valid_meta):
    valid_meta["distribution"] = "built"
    valid_meta["image"] = "ghcr.io/paddockhq/demo"
    with pytest.raises(BundleError, match="need a Dockerfile"):
        load_bundle(make_bundle(valid_meta, files={"Dockerfile": None}))


def test_upstream_bundle_must_not_have_a_dockerfile(make_bundle):
    with pytest.raises(BundleError, match="must not contain a Dockerfile"):
        load_bundle(make_bundle(files={"Dockerfile": "FROM scratch\n"}))


def test_missing_provider_file_is_named(make_bundle):
    with pytest.raises(BundleError, match="missing provider file providers/demo-apikey.yaml"):
        load_bundle(make_bundle(files={"providers/demo-apikey.yaml": None}))


@pytest.mark.parametrize("rel", ["policy.yaml", "boundary.yaml", "tests/allow.sh", "README.md"])
def test_required_files_are_checked(make_bundle, rel):
    with pytest.raises(BundleError, match=f"missing required file {rel}"):
        load_bundle(make_bundle(files={rel: None}))


def test_auth_modes_must_be_unique(make_bundle, valid_meta):
    valid_meta["auth"].append(copy.deepcopy(valid_meta["auth"][0]))
    with pytest.raises(BundleError, match="auth modes must be unique"):
        load_bundle(make_bundle(valid_meta))


def test_crlf_line_endings_are_rejected(make_bundle):
    bundle_dir = make_bundle(files={"tests/allow.sh": "#!/usr/bin/env bash\r\necho hi\r\n"})
    with pytest.raises(BundleError, match="CRLF line endings in tests/allow.sh"):
        load_bundle(bundle_dir)


def test_every_problem_is_listed(make_bundle):
    with pytest.raises(BundleError) as exc:
        load_bundle(make_bundle(files={"policy.yaml": None, "boundary.yaml": None}))
    assert "policy.yaml" in str(exc.value)
    assert "boundary.yaml" in str(exc.value)


def test_discover_bundles_is_sorted_and_skips_other_folders(make_bundle, valid_meta, tmp_path):
    for name in ("zeta", "alpha"):
        meta = copy.deepcopy(valid_meta)
        meta["name"] = name
        make_bundle(meta)
    (tmp_path / "bundles" / "notes").mkdir()
    assert discover_bundles(tmp_path / "bundles") == ["alpha", "zeta"]


def test_discover_bundles_without_a_bundles_folder(tmp_path):
    assert discover_bundles(tmp_path / "bundles") == []


def test_provider_info_reads_id_and_first_env_var(tmp_path):
    profile = tmp_path / "p.yaml"
    profile.write_text(
        "id: demo-apikey\n"
        "credentials:\n"
        "  - name: api_key\n"
        "    env_vars: [DEMO_API_KEY, DEMO_KEY]\n",
        encoding="utf-8",
    )
    assert provider_info(profile) == {"id": "demo-apikey", "credential_envs": ["DEMO_API_KEY"]}


def test_shell_assignments_quote_values(valid_meta):
    valid_meta["env"] = {"B_FLAG": "1", "A_PATH": "/sandbox/my dir"}
    out = shell_assignments(valid_meta)
    assert "PADDOCK_NAME=demo\n" in out
    assert "PADDOCK_OPENSHELL_MIN_VERSION=''\n" in out
    assert "PADDOCK_VERSION_COMMAND=(demo --version)\n" in out
    assert "PADDOCK_ENV_ARGS=(--env 'A_PATH=/sandbox/my dir' --env B_FLAG=1)\n" in out
    assert "PADDOCK_AUTH_MODES=(api-key)\n" in out
    assert "PADDOCK_PROVIDER_FILES=(providers/demo-apikey.yaml)\n" in out


def test_validate_command_reports_failures(make_bundle, tmp_path, capsys):
    make_bundle(files={"policy.yaml": None})
    assert main(["validate", "--root", str(tmp_path)]) == 1
    assert "missing required file policy.yaml" in capsys.readouterr().err


def test_validate_command_passes_valid_bundles(make_bundle, tmp_path, capsys):
    make_bundle()
    assert main(["validate", "--root", str(tmp_path)]) == 0
    assert "ok: demo" in capsys.readouterr().out


def test_validate_command_without_bundles(tmp_path, capsys):
    assert main(["validate", "--root", str(tmp_path)]) == 0
    assert "no bundles found" in capsys.readouterr().out
```

- [ ] **Step 3: Run them to verify they fail.**

Run: `python -m pytest tests/unit/test_bundle.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paddock.bundle'`.

- [ ] **Step 4: Write the schema.**

Create `scripts/paddock/bundle.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "PadDock bundle.yaml",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema", "name", "agent", "distribution", "image", "revision", "command", "version_command", "auth"],
  "properties": {
    "schema": { "const": 1 },
    "name": { "type": "string", "pattern": "^[a-z0-9][a-z0-9-]*$" },
    "agent": {
      "type": "object",
      "additionalProperties": false,
      "required": ["display_name", "homepage", "license", "version"],
      "properties": {
        "display_name": { "type": "string", "minLength": 1 },
        "homepage": { "type": "string", "pattern": "^https://" },
        "license": { "type": "string", "minLength": 1 },
        "version": { "type": "string", "pattern": "^[0-9]+\\.[0-9]+\\.[0-9]+([-+][0-9A-Za-z.-]+)?$" }
      }
    },
    "distribution": { "enum": ["upstream", "built", "dockerfile-only"] },
    "image": { "type": "string", "minLength": 1 },
    "revision": { "type": "integer", "minimum": 1 },
    "command": { "type": "array", "minItems": 1, "items": { "type": "string", "minLength": 1 } },
    "version_command": { "type": "array", "minItems": 1, "items": { "type": "string", "minLength": 1 } },
    "env": {
      "type": "object",
      "propertyNames": { "pattern": "^(?!OPENSHELL_)[A-Za-z_][A-Za-z0-9_]*$" },
      "additionalProperties": { "type": "string" }
    },
    "openshell_min_version": { "type": "string", "pattern": "^v[0-9]+\\.[0-9]+\\.[0-9]+$" },
    "auth": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["mode", "provider_file"],
        "properties": {
          "mode": { "enum": ["api-key", "subscription"] },
          "provider_file": { "type": "string", "pattern": "^providers/[a-z0-9-]+\\.yaml$" }
        }
      }
    }
  }
}
```

- [ ] **Step 5: Write the loader.**

Create `scripts/paddock/bundle.py`:

```python
"""Load and validate PadDock bundles (bundles/<name>/bundle.yaml)."""

import json
import re
import shlex
import sys
from pathlib import Path

import jsonschema
import yaml

SCHEMA_PATH = Path(__file__).with_name("bundle.schema.json")
DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}$")
REQUIRED_FILES = ("policy.yaml", "boundary.yaml", "tests/allow.sh", "README.md")
LF_ONLY_SUFFIXES = (".sh", ".yaml", ".yml")


class BundleError(Exception):
    """A bundle is invalid. The message lists every problem found."""


def load_bundle(bundle_dir):
    bundle_dir = Path(bundle_dir)
    meta_path = bundle_dir / "bundle.yaml"
    if not meta_path.is_file():
        raise BundleError(f"{bundle_dir}: bundle.yaml not found")
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = jsonschema.Draft202012Validator(schema).iter_errors(meta)
    problems = [
        f"{'.'.join(str(part) for part in error.absolute_path) or 'bundle.yaml'}: {error.message}"
        for error in sorted(errors, key=lambda e: [str(part) for part in e.absolute_path])
    ]
    if not problems:
        problems = _check_files(bundle_dir, meta)
    if problems:
        raise BundleError(f"{bundle_dir}:\n  " + "\n  ".join(problems))
    return {**meta, "dir": bundle_dir}


def _check_files(bundle_dir, meta):
    problems = []
    if meta["name"] != bundle_dir.name:
        problems.append(f"name '{meta['name']}' does not match folder '{bundle_dir.name}'")
    for rel in REQUIRED_FILES:
        if not (bundle_dir / rel).is_file():
            problems.append(f"missing required file {rel}")
    has_dockerfile = (bundle_dir / "Dockerfile").is_file()
    if meta["distribution"] == "upstream":
        if has_dockerfile:
            problems.append("upstream bundles must not contain a Dockerfile")
        if not DIGEST_RE.search(meta["image"]):
            problems.append("upstream image must be pinned by digest (@sha256:<64 hex digits>)")
    else:
        if not has_dockerfile:
            problems.append(f"{meta['distribution']} bundles need a Dockerfile")
        if "@" in meta["image"] or ":" in meta["image"].rsplit("/", 1)[-1]:
            problems.append("built and dockerfile-only images must be a repository without a tag or digest")
    modes = [entry["mode"] for entry in meta["auth"]]
    if len(modes) != len(set(modes)):
        problems.append("auth modes must be unique")
    for entry in meta["auth"]:
        if not (bundle_dir / entry["provider_file"]).is_file():
            problems.append(f"missing provider file {entry['provider_file']}")
    for path in sorted(bundle_dir.rglob("*")):
        if path.is_file() and (path.suffix in LF_ONLY_SUFFIXES or path.name == "Dockerfile"):
            if b"\r\n" in path.read_bytes():
                rel = path.relative_to(bundle_dir).as_posix()
                problems.append(f"CRLF line endings in {rel} (convert the file to LF)")
    return problems


def discover_bundles(bundles_root):
    root = Path(bundles_root)
    if not root.is_dir():
        return []
    return sorted(path.name for path in root.iterdir() if (path / "bundle.yaml").is_file())


def provider_info(path):
    profile = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    envs = [cred["env_vars"][0] for cred in profile.get("credentials", []) if cred.get("env_vars")]
    return {"id": profile["id"], "credential_envs": envs}


def shell_assignments(meta):
    def array(name, values):
        return f"{name}=(" + " ".join(shlex.quote(value) for value in values) + ")"

    env_args = [part for key, value in sorted(meta.get("env", {}).items()) for part in ("--env", f"{key}={value}")]
    lines = [
        f"PADDOCK_NAME={shlex.quote(meta['name'])}",
        f"PADDOCK_IMAGE={shlex.quote(meta['image'])}",
        f"PADDOCK_DISTRIBUTION={shlex.quote(meta['distribution'])}",
        f"PADDOCK_OPENSHELL_MIN_VERSION={shlex.quote(meta.get('openshell_min_version', ''))}",
        array("PADDOCK_COMMAND", meta["command"]),
        array("PADDOCK_VERSION_COMMAND", meta["version_command"]),
        array("PADDOCK_ENV_ARGS", env_args),
        array("PADDOCK_AUTH_MODES", [entry["mode"] for entry in meta["auth"]]),
        array("PADDOCK_PROVIDER_FILES", [entry["provider_file"] for entry in meta["auth"]]),
    ]
    return "\n".join(lines) + "\n"


def _cmd_validate(args):
    root = Path(args.root)
    names = args.names or discover_bundles(root / "bundles")
    if not names:
        print("no bundles found")
        return 0
    failed = False
    for name in names:
        try:
            load_bundle(root / "bundles" / name)
        except BundleError as err:
            failed = True
            print(err, file=sys.stderr)
        else:
            print(f"ok: {name}")
    return 1 if failed else 0


def _cmd_bundle_env(args):
    sys.stdout.write(shell_assignments(load_bundle(args.bundle_dir)))
    return 0


def _cmd_provider_info(args):
    info = provider_info(args.provider_file)
    envs = " ".join(shlex.quote(env) for env in info["credential_envs"])
    print(f"PROFILE_ID={shlex.quote(info['id'])}")
    print(f"PROFILE_CREDENTIAL_ENVS=({envs})")
    return 0


def add_commands(sub):
    cmd = sub.add_parser("validate", help="validate bundle folders")
    cmd.add_argument("--root", default=".", help="repository root that contains bundles/")
    cmd.add_argument("names", nargs="*", help="bundle names (default: every bundle)")
    cmd.set_defaults(handler=_cmd_validate)

    cmd = sub.add_parser("bundle-env", help="print bundle.yaml as bash assignments")
    cmd.add_argument("bundle_dir")
    cmd.set_defaults(handler=_cmd_bundle_env)

    cmd = sub.add_parser("provider-info", help="print a provider profile's id and credential env vars for bash")
    cmd.add_argument("provider_file")
    cmd.set_defaults(handler=_cmd_provider_info)
```

- [ ] **Step 6: Register the module.**

In `scripts/paddock/__main__.py`, replace `MODULES = ()` with these two lines:

```python
from paddock import bundle

MODULES = (bundle,)
```

- [ ] **Step 7: Run the tests to verify they pass.**

Run: `python -m pytest tests/unit -v`
Expected: every test passes (`test_cli.py` and `test_bundle.py`).

- [ ] **Step 8: Commit.**

```bash
git add scripts/paddock tests/unit
git commit -s -m "Add bundle.yaml schema, loader, and shell export"
```

---

### Task 5: Version list and CI matrix

**Files:**
- Create: `scripts/ci/openshell-versions.json`
- Create: `scripts/paddock/matrix.py`
- Modify: `scripts/paddock/__main__.py`
- Test: `tests/unit/test_matrix.py`

**Interfaces:**
- Consumes: `bundle.discover_bundles`, `bundle.load_bundle`, `bundle.BundleError` (Task 4).
- Produces:
  - `matrix.RUNNERS: tuple[str, ...]`
  - `matrix.parse_version(tag: str) -> tuple[int, int, int]`
  - `matrix.load_versions(path) -> list[str]`
  - `matrix.affected_bundles(names: list[str], changed_files: list[str] | None) -> list[str]`
  - `matrix.supports(meta: dict, version: str) -> bool`
  - `matrix.build_matrix(metas: list[dict], versions: list[str], runners=RUNNERS) -> list[dict]`. Each dict has the keys `bundle`, `openshell_version` and `runner`.
  - CLI: `python -m paddock matrix [--root DIR] [--versions-file FILE] [--changed-files FILE] [--github-output FILE]`. It prints `{"include": [...]}` and appends `matrix=` and `has_cells=` lines to the `--github-output` file.

- [ ] **Step 1: Create the version list.**

Create `scripts/ci/openshell-versions.json`. List only `v0.1.2` if ADR 0001 recorded that v0.0.116 failed.

```json
{
  "versions": ["v0.1.2", "v0.0.116"]
}
```

- [ ] **Step 2: Write the failing tests.**

Create `tests/unit/test_matrix.py`:

```python
import json

from paddock.__main__ import main
from paddock.matrix import affected_bundles, build_matrix, parse_version, supports


def test_parse_version():
    assert parse_version("v0.1.2") == (0, 1, 2)
    assert parse_version("v0.0.116") == (0, 0, 116)
    assert parse_version("v1.2.3-rc.1") == (1, 2, 3)


def test_version_order_is_numeric_not_text():
    assert parse_version("v0.0.116") < parse_version("v0.1.0")


def test_no_changed_list_means_every_bundle():
    assert affected_bundles(["b", "a"], None) == ["a", "b"]


def test_bundle_change_selects_only_that_bundle():
    assert affected_bundles(["a", "b"], ["bundles/b/policy.yaml", "README.md"]) == ["b"]


def test_shared_change_selects_every_bundle():
    assert affected_bundles(["a", "b"], ["scripts/ci/run-cell.sh"]) == ["a", "b"]


def test_windows_style_paths_are_understood():
    assert affected_bundles(["a", "b"], ["bundles\\a\\policy.yaml"]) == ["a"]


def test_docs_only_change_selects_nothing():
    assert affected_bundles(["a"], ["docs/notes.md", "bundles/README.md"]) == []


def test_min_version_floor_skips_older_releases():
    meta = {"name": "a", "openshell_min_version": "v0.1.0"}
    assert supports(meta, "v0.1.2")
    assert not supports(meta, "v0.0.116")


def test_matrix_crosses_bundles_versions_and_runners():
    metas = [{"name": "b"}, {"name": "a", "openshell_min_version": "v0.1.0"}]
    cells = build_matrix(metas, ["v0.1.2", "v0.0.116"], ["x", "y"])
    assert cells == [
        {"bundle": "a", "openshell_version": "v0.1.2", "runner": "x"},
        {"bundle": "a", "openshell_version": "v0.1.2", "runner": "y"},
        {"bundle": "b", "openshell_version": "v0.1.2", "runner": "x"},
        {"bundle": "b", "openshell_version": "v0.1.2", "runner": "y"},
        {"bundle": "b", "openshell_version": "v0.0.116", "runner": "x"},
        {"bundle": "b", "openshell_version": "v0.0.116", "runner": "y"},
    ]


def _versions_file(tmp_path):
    path = tmp_path / "versions.json"
    path.write_text('{"versions": ["v0.1.2"]}', encoding="utf-8")
    return path


def test_matrix_command_with_no_bundles_writes_empty_outputs(tmp_path, capsys):
    gh_out = tmp_path / "github_output"
    rc = main([
        "matrix", "--root", str(tmp_path),
        "--versions-file", str(_versions_file(tmp_path)),
        "--github-output", str(gh_out),
    ])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"include": []}
    assert gh_out.read_text(encoding="utf-8") == 'matrix={"include":[]}\nhas_cells=false\n'


def test_matrix_command_uses_changed_files(make_bundle, tmp_path, capsys):
    make_bundle()
    changed = tmp_path / "changed.txt"
    changed.write_text("bundles/demo/policy.yaml\n", encoding="utf-8")
    rc = main([
        "matrix", "--root", str(tmp_path),
        "--versions-file", str(_versions_file(tmp_path)),
        "--changed-files", str(changed),
    ])
    assert rc == 0
    cells = json.loads(capsys.readouterr().out)["include"]
    assert [cell["bundle"] for cell in cells] == ["demo", "demo"]
```

- [ ] **Step 3: Run them to verify they fail.**

Run: `python -m pytest tests/unit/test_matrix.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paddock.matrix'`.

- [ ] **Step 4: Write the module.**

Create `scripts/paddock/matrix.py`. If ADR 0001 recorded that arm64 failed, set `RUNNERS = ("ubuntu-24.04",)`.

```python
"""Compute the CI matrix: bundle x OpenShell version x runner."""

import json
import sys
from pathlib import Path

from paddock import bundle

RUNNERS = ("ubuntu-24.04", "ubuntu-24.04-arm")
# A change under any of these paths can affect every bundle.
SHARED_PATHS = ("scripts/", "tests/deny/", ".github/workflows/", "requirements-dev.txt")


def parse_version(tag):
    """'v0.1.2' -> (0, 1, 2). Pre-release suffixes are ignored."""
    core = tag.removeprefix("v").split("-", 1)[0]
    major, minor, patch = (int(part) for part in core.split("."))
    return major, minor, patch


def load_versions(path):
    versions = json.loads(Path(path).read_text(encoding="utf-8"))["versions"]
    if not versions:
        raise ValueError(f"{path}: the versions list is empty")
    return versions


def affected_bundles(names, changed_files):
    """Bundles to test. changed_files=None means test every bundle."""
    names = sorted(names)
    if changed_files is None:
        return names
    hit = set()
    for path in changed_files:
        path = path.replace("\\", "/")
        if path.startswith(SHARED_PATHS):
            return names
        parts = path.split("/")
        if len(parts) > 2 and parts[0] == "bundles" and parts[1] in names:
            hit.add(parts[1])
    return sorted(hit)


def supports(meta, version):
    floor = meta.get("openshell_min_version")
    return floor is None or parse_version(version) >= parse_version(floor)


def build_matrix(metas, versions, runners=RUNNERS):
    return [
        {"bundle": meta["name"], "openshell_version": version, "runner": runner}
        for meta in sorted(metas, key=lambda m: m["name"])
        for version in versions
        if supports(meta, version)
        for runner in runners
    ]


def _cmd_matrix(args):
    root = Path(args.root)
    names = bundle.discover_bundles(root / "bundles")
    try:
        metas = {name: bundle.load_bundle(root / "bundles" / name) for name in names}
    except bundle.BundleError as err:
        print(err, file=sys.stderr)
        return 1
    changed = None
    if args.changed_files:
        lines = Path(args.changed_files).read_text(encoding="utf-8").splitlines()
        changed = [line.strip() for line in lines if line.strip()]
    selected = affected_bundles(names, changed)
    cells = build_matrix([metas[name] for name in selected], load_versions(args.versions_file))
    payload = json.dumps({"include": cells}, separators=(",", ":"))
    print(payload)
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as out:
            out.write(f"matrix={payload}\n")
            out.write(f"has_cells={'true' if cells else 'false'}\n")
    return 0


def add_commands(sub):
    cmd = sub.add_parser("matrix", help="print the CI matrix as JSON")
    cmd.add_argument("--root", default=".", help="repository root that contains bundles/")
    cmd.add_argument("--versions-file", default="scripts/ci/openshell-versions.json")
    cmd.add_argument("--changed-files", help="file listing changed paths, one per line (omit to test every bundle)")
    cmd.add_argument("--github-output", help="append matrix= and has_cells= lines to this file")
    cmd.set_defaults(handler=_cmd_matrix)
```

- [ ] **Step 5: Register the module.**

In `scripts/paddock/__main__.py`, replace the two lines added in Task 4 with:

```python
from paddock import bundle, matrix

MODULES = (bundle, matrix)
```

- [ ] **Step 6: Run the tests to verify they pass.**

Run: `python -m pytest tests/unit -v`
Expected: every test passes.

- [ ] **Step 7: Commit.**

```bash
git add scripts/ci/openshell-versions.json scripts/paddock tests/unit/test_matrix.py
git commit -s -m "Add the OpenShell version list and CI matrix builder"
```

---

### Task 6: Policy event parser for `openshell logs`

**Files:**
- Create: `scripts/paddock/logs.py`
- Modify: `scripts/paddock/__main__.py`
- Test: `tests/unit/test_logs.py`

**Interfaces:**
- Produces:
  - `logs.Event`, a frozen dataclass with these fields:
    - `kind`: `"NET"` or `"HTTP"`
    - `action`: `"ALLOWED"`, `"DENIED"` or `"BLOCKED"`
    - `host: str`, `port: int | None`, `binary: str | None`, `method: str | None`
    - `line: str`: the raw log line
  - `logs.parse_events(text: str) -> list[Event]`
  - `logs.select(events, action=None, host=None) -> list[Event]`
  - CLI: `python -m paddock events --log FILE [--action ALLOWED|DENIED|BLOCKED] [--host HOST] [--format lines|count|hosts]`. With `--format hosts` it prints the unique `host:port` values, sorted, one per line.

- [ ] **Step 1: Write the failing tests.** These fixture lines are copied from OpenShell v0.1.2's docs and its OCSF formatter (`crates/openshell-ocsf/src/format/shorthand.rs`).

Create `tests/unit/test_logs.py`:

```python
from paddock.__main__ import main
from paddock.logs import parse_events, select

NET_DENIED = (
    "[1775014132.690] [sandbox] [OCSF ] [ocsf] NET:OPEN [MED] DENIED /usr/bin/curl(64) -> "
    "httpbin.org:443 [policy:- engine:opa] [reason:no matching policy]"
)
NET_ALLOWED = (
    "[1775014132.700] [sandbox] [OCSF ] [ocsf] NET:OPEN [INFO] ALLOWED /usr/bin/curl(58) -> "
    "api.github.com:443 [policy:github_api engine:opa]"
)
HTTP_DENIED = (
    "[1775014140.412] [sandbox] [OCSF ] [ocsf] HTTP:POST [MED] DENIED POST "
    "http://api.github.com:443/repos/octocat/hello-world/issues [policy:github_api engine:l7]"
)
FILE_FORMAT = (
    "2026-04-01T04:04:32.690Z OCSF NET:OPEN [MED] DENIED /usr/bin/curl(1618) -> "
    "169.254.169.254:80 [policy:- engine:ssrf] [reason:resolves to always-blocked address]"
)
REFUSE = "NET:REFUSE [MED] DENIED node(1234) -> 93.184.216.34:443/tcp [policy:bypass-detect engine:nftables]"
IPV6 = "[1.0] [sandbox] [OCSF ] [ocsf] NET:OPEN [MED] DENIED /usr/bin/curl(7) -> [2001:db8::1]:443 [policy:-]"
NOISE = "[1775014132.000] [sandbox] [INFO ] [supervisor] sandbox ready"


def test_parses_net_and_http_lines():
    events = parse_events("\n".join([NET_DENIED, NET_ALLOWED, HTTP_DENIED, NOISE]))
    assert [(e.kind, e.action, e.host, e.port) for e in events] == [
        ("NET", "DENIED", "httpbin.org", 443),
        ("NET", "ALLOWED", "api.github.com", 443),
        ("HTTP", "DENIED", "api.github.com", 443),
    ]
    assert events[0].binary == "/usr/bin/curl"
    assert events[2].method == "POST"


def test_parses_file_format_lines():
    (event,) = parse_events(FILE_FORMAT)
    assert (event.host, event.port, event.binary) == ("169.254.169.254", 80, "/usr/bin/curl")


def test_parses_ipv6_and_refuse_lines():
    refuse, ipv6 = parse_events(REFUSE + "\n" + IPV6)
    assert (refuse.host, refuse.port, refuse.binary) == ("93.184.216.34", 443, "node")
    assert (ipv6.host, ipv6.port) == ("2001:db8::1", 443)


def test_http_line_without_port():
    (event,) = parse_events("OCSF HTTP:POST [MED] DENIED POST http://api.github.com/user/repos [policy:x engine:opa]")
    assert (event.host, event.port) == ("api.github.com", None)


def test_select_filters_by_action_and_host():
    events = parse_events("\n".join([NET_DENIED, NET_ALLOWED, HTTP_DENIED]))
    assert len(select(events, action="DENIED")) == 2
    assert len(select(events, action="DENIED", host="api.github.com")) == 1


def test_events_command_formats(tmp_path, capsys):
    log = tmp_path / "sandbox.log"
    log.write_text("\n".join([NET_DENIED, NET_ALLOWED, HTTP_DENIED]) + "\n", encoding="utf-8")
    assert main(["events", "--log", str(log), "--action", "DENIED", "--format", "hosts"]) == 0
    assert capsys.readouterr().out == "api.github.com:443\nhttpbin.org:443\n"
    assert main(["events", "--log", str(log), "--host", "api.github.com", "--format", "count"]) == 0
    assert capsys.readouterr().out == "2\n"
```

- [ ] **Step 2: Run them to verify they fail.**

Run: `python -m pytest tests/unit/test_logs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paddock.logs'`.

- [ ] **Step 3: Write the module.**

Create `scripts/paddock/logs.py`:

```python
"""Read OpenShell policy events (OCSF shorthand) from `openshell logs` output."""

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

_NET = re.compile(
    r"\bNET:(?P<op>[A-Z]+) \[[A-Z]+\] (?P<action>ALLOWED|DENIED|BLOCKED) "
    r"(?P<binary>\S+?)\((?P<pid>\d+)\) -> (?P<host>\[[^\]]+\]|[^\s:/]+):(?P<port>\d+)"
)
_HTTP = re.compile(
    r"\bHTTP:(?P<method>[A-Z]+) \[[A-Z]+\] (?P<action>ALLOWED|DENIED|BLOCKED) (?P=method) (?P<url>\S+)"
)


@dataclass(frozen=True)
class Event:
    kind: str
    action: str
    host: str
    port: int | None
    binary: str | None
    method: str | None
    line: str


def parse_events(text):
    events = []
    for line in text.splitlines():
        if match := _NET.search(line):
            events.append(Event(
                "NET", match["action"], match["host"].strip("[]"), int(match["port"]),
                match["binary"], None, line,
            ))
        elif match := _HTTP.search(line):
            url = urlsplit(match["url"])
            events.append(Event("HTTP", match["action"], url.hostname or "", url.port, None, match["method"], line))
    return events


def select(events, action=None, host=None):
    return [e for e in events if (action is None or e.action == action) and (host is None or e.host == host)]


def _cmd_events(args):
    events = select(parse_events(Path(args.log).read_text(encoding="utf-8", errors="replace")), args.action, args.host)
    if args.format == "count":
        print(len(events))
    elif args.format == "hosts":
        for destination in sorted({f"{e.host}:{e.port}" if e.port else e.host for e in events}):
            print(destination)
    else:
        for event in events:
            print(event.line)
    return 0


def add_commands(sub):
    cmd = sub.add_parser("events", help="list OpenShell policy events from an `openshell logs` capture")
    cmd.add_argument("--log", required=True)
    cmd.add_argument("--action", choices=["ALLOWED", "DENIED", "BLOCKED"])
    cmd.add_argument("--host")
    cmd.add_argument("--format", choices=["lines", "count", "hosts"], default="lines")
    cmd.set_defaults(handler=_cmd_events)
```

- [ ] **Step 4: Register the module.**

In `scripts/paddock/__main__.py`, replace the two lines added in Task 5 with:

```python
from paddock import bundle, logs, matrix

MODULES = (bundle, matrix, logs)
```

- [ ] **Step 5: Run the tests to verify they pass.**

Run: `python -m pytest tests/unit -v`
Expected: every test passes.

- [ ] **Step 6: Commit.**

```bash
git add scripts/paddock tests/unit/test_logs.py
git commit -s -m "Add a parser for OpenShell policy events"
```

---

### Task 7: Result files and the compatibility report

**Files:**
- Create: `scripts/paddock/results.py`
- Modify: `scripts/paddock/__main__.py`
- Test: `tests/unit/test_results.py`

**Interfaces:**
- Consumes: `bundle.discover_bundles`, `bundle.load_bundle` (Task 4); `matrix.RUNNERS`, `matrix.supports`, `matrix.load_versions` (Task 5).
- Produces:
  - **Check file format:** each line is `name<TAB>status<TAB>detail`, where `status` is one of `pass|fail|error|skip`. Bash writes this file.
  - `results.read_checks(path) -> list[dict]`
  - `results.cell_status(checks) -> str`:
    - `"fail"` if any check failed;
    - otherwise `"error"` if any check errored or there are no checks;
    - otherwise `"pass"`.
  - `results.cell_result(bundle_name, version, runner, checks) -> dict`
  - `results.load_results(results_dir) -> list[dict]`
  - `results.render_report(metas, versions, runners, results) -> str`
  - **Result file:** `results/<bundle>--<tag>--<runner>.json`, a JSON object with the keys `bundle`, `openshell_version`, `runner`, `status` and `checks`.
  - CLI:
    - `python -m paddock result --bundle B --openshell-version V --runner R --checks FILE --out FILE`: exit code 0 if the cell passed, 1 otherwise.
    - `python -m paddock report [--root DIR] [--versions-file FILE] --results DIR`: prints Markdown.

- [ ] **Step 1: Write the failing tests.**

Create `tests/unit/test_results.py`:

```python
import json

import pytest

from paddock.__main__ import main
from paddock.results import cell_result, cell_status, read_checks, render_report

PASS = {"name": "setup", "status": "pass", "detail": ""}


def test_read_checks_parses_tab_separated_lines(tmp_path):
    path = tmp_path / "checks.tsv"
    path.write_text("setup\tpass\topenshell v0.1.2\nprover:api-key\tskip\tprimary only\nlint\tpass\n", encoding="utf-8")
    assert read_checks(path) == [
        {"name": "setup", "status": "pass", "detail": "openshell v0.1.2"},
        {"name": "prover:api-key", "status": "skip", "detail": "primary only"},
        {"name": "lint", "status": "pass", "detail": ""},
    ]


def test_read_checks_rejects_unknown_status(tmp_path):
    path = tmp_path / "checks.tsv"
    path.write_text("setup\tok\t\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown check status 'ok'"):
        read_checks(path)


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [(["pass", "skip"], "pass"), (["pass", "error"], "error"), (["error", "fail"], "fail"), ([], "error")],
)
def test_cell_status(statuses, expected):
    checks = [{"name": f"c{i}", "status": s, "detail": ""} for i, s in enumerate(statuses)]
    assert cell_status(checks) == expected


def test_report_without_bundles():
    assert "No bundles yet." in render_report([], ["v0.1.2"], ["ubuntu-24.04"], [])


def test_missing_result_is_reported_as_not_run():
    results = [cell_result("demo", "v0.1.2", "ubuntu-24.04", [PASS])]
    report = render_report([{"name": "demo"}], ["v0.1.2"], ["ubuntu-24.04", "ubuntu-24.04-arm"], results)
    assert "| Bundle | v0.1.2 x64 | v0.1.2 arm64 |" in report
    assert "| demo | pass | not run |" in report


def test_report_lists_failing_checks_and_version_floors():
    failing = {"name": "prover:api-key", "status": "fail", "detail": "exceeds boundary"}
    results = [cell_result("demo", "v0.1.2", "ubuntu-24.04", [PASS, failing])]
    metas = [{"name": "demo", "openshell_min_version": "v0.1.0"}]
    report = render_report(metas, ["v0.1.2", "v0.0.116"], ["ubuntu-24.04"], results)
    assert "| demo | fail | unsupported (needs v0.1.0) |" in report
    assert "- demo / v0.1.2 / ubuntu-24.04: `prover:api-key` fail: exceeds boundary" in report


def test_result_command_writes_the_file_and_sets_the_exit_code(tmp_path):
    checks = tmp_path / "checks.tsv"
    checks.write_text("setup\tpass\t\nallow\tfail\tboom\n", encoding="utf-8")
    out = tmp_path / "out" / "demo.json"
    rc = main([
        "result", "--bundle", "demo", "--openshell-version", "v0.1.2", "--runner", "ubuntu-24.04",
        "--checks", str(checks), "--out", str(out),
    ])
    assert rc == 1
    assert json.loads(out.read_text(encoding="utf-8"))["status"] == "fail"


def test_report_command_reads_result_files(make_bundle, tmp_path, capsys):
    make_bundle()
    versions = tmp_path / "versions.json"
    versions.write_text('{"versions": ["v0.1.2"]}', encoding="utf-8")
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "demo--v0.1.2--ubuntu-24.04.json").write_text(
        json.dumps(cell_result("demo", "v0.1.2", "ubuntu-24.04", [PASS])), encoding="utf-8"
    )
    rc = main(["report", "--root", str(tmp_path), "--versions-file", str(versions), "--results", str(results_dir)])
    assert rc == 0
    assert "| demo | pass | not run |" in capsys.readouterr().out
```

- [ ] **Step 2: Run them to verify they fail.**

Run: `python -m pytest tests/unit/test_results.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paddock.results'`.

- [ ] **Step 3: Write the module.**

Create `scripts/paddock/results.py`:

```python
"""Per-cell result files and the COMPATIBILITY.md report."""

import json
import sys
from pathlib import Path

from paddock import bundle, matrix

CHECK_STATUSES = ("pass", "fail", "error", "skip")
RUNNER_LABELS = {"ubuntu-24.04": "x64", "ubuntu-24.04-arm": "arm64"}


def read_checks(path):
    checks = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        name, status, detail = (raw.split("\t", 2) + ["", ""])[:3]
        if status not in CHECK_STATUSES:
            raise ValueError(f"unknown check status {status!r} in line: {raw}")
        checks.append({"name": name, "status": status, "detail": detail})
    return checks


def cell_status(checks):
    statuses = {check["status"] for check in checks}
    if "fail" in statuses:
        return "fail"
    if "error" in statuses or not checks:
        return "error"
    return "pass"


def cell_result(bundle_name, version, runner, checks):
    return {
        "bundle": bundle_name,
        "openshell_version": version,
        "runner": runner,
        "status": cell_status(checks),
        "checks": checks,
    }


def load_results(results_dir):
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(Path(results_dir).glob("*.json"))]


def render_report(metas, versions, runners, results):
    lines = [
        "# Compatibility",
        "",
        "Generated by CI. Each cell is one bundle tested against one OpenShell release on one runner architecture.",
        "",
    ]
    if not metas:
        return "\n".join(lines + ["No bundles yet."]) + "\n"
    by_cell = {(r["bundle"], r["openshell_version"], r["runner"]): r for r in results}
    columns = [(version, runner) for version in versions for runner in runners]
    header = " | ".join(f"{version} {RUNNER_LABELS.get(runner, runner)}" for version, runner in columns)
    lines += [f"| Bundle | {header} |", "|---" * (len(columns) + 1) + "|"]
    for meta in sorted(metas, key=lambda m: m["name"]):
        cells = []
        for version, runner in columns:
            if not matrix.supports(meta, version):
                cells.append(f"unsupported (needs {meta['openshell_min_version']})")
            else:
                result = by_cell.get((meta["name"], version, runner))
                cells.append(result["status"] if result else "not run")
        lines.append(f"| {meta['name']} | " + " | ".join(cells) + " |")
    problems = [
        f"- {r['bundle']} / {r['openshell_version']} / {r['runner']}: `{c['name']}` {c['status']}: {c['detail']}"
        for r in sorted(results, key=lambda r: (r["bundle"], r["openshell_version"], r["runner"]))
        for c in r["checks"]
        if c["status"] in ("fail", "error")
    ]
    if problems:
        lines += ["", "## Failing checks", "", *problems]
    return "\n".join(lines) + "\n"


def _cmd_result(args):
    result = cell_result(args.bundle, args.openshell_version, args.runner, read_checks(args.checks))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{args.bundle} / {args.openshell_version} / {args.runner}: {result['status']}")
    return 0 if result["status"] == "pass" else 1


def _cmd_report(args):
    root = Path(args.root)
    try:
        metas = [bundle.load_bundle(root / "bundles" / name) for name in bundle.discover_bundles(root / "bundles")]
    except bundle.BundleError as err:
        print(err, file=sys.stderr)
        return 1
    versions = matrix.load_versions(args.versions_file)
    sys.stdout.write(render_report(metas, versions, list(matrix.RUNNERS), load_results(args.results)))
    return 0


def add_commands(sub):
    cmd = sub.add_parser("result", help="turn a cell's checks file into a result JSON file")
    cmd.add_argument("--bundle", required=True)
    cmd.add_argument("--openshell-version", required=True)
    cmd.add_argument("--runner", required=True)
    cmd.add_argument("--checks", required=True)
    cmd.add_argument("--out", required=True)
    cmd.set_defaults(handler=_cmd_result)

    cmd = sub.add_parser("report", help="print the compatibility report as Markdown")
    cmd.add_argument("--root", default=".")
    cmd.add_argument("--versions-file", default="scripts/ci/openshell-versions.json")
    cmd.add_argument("--results", required=True, help="folder of result JSON files")
    cmd.set_defaults(handler=_cmd_report)
```

- [ ] **Step 4: Register the module.**

In `scripts/paddock/__main__.py`, replace the two lines added in Task 6 with:

```python
from paddock import bundle, logs, matrix, results

MODULES = (bundle, matrix, logs, results)
```

- [ ] **Step 5: Run the tests to verify they pass.**

Run: `python -m pytest tests/unit -v`
Expected: every test passes.

- [ ] **Step 6: Commit.**

```bash
git add scripts/paddock tests/unit/test_results.py
git commit -s -m "Add per-cell result files and the compatibility report"
```

---

### Task 8: The per-cell runner, prover install, and bash helper tests

**Files:**
- Modify: `scripts/ci/lib.sh` (append the helpers below)
- Create: `scripts/ci/install-prover.sh`
- Create: `scripts/ci/run-cell.sh`
- Test: `tests/unit/test_ci_lib.py`

**Interfaces:**
- Consumes:
  - From Task 2: `log`, `die`, `wait_until`, `gateway_connected` in `lib.sh`, and `scripts/ci/install-openshell.sh <tag>`.
  - From Tasks 4–7, the CLI commands `validate`, `bundle-env`, `provider-info`, `events` and `result`.
- Produces, as additions to `lib.sh`:
  - `record_check NAME STATUS [DETAIL]`: appends a line to `$PADDOCK_CHECKS_FILE`.
  - `exec_flags`: prints the supported `sandbox exec` flags (`--no-tty` and `--no-login-shell`), one per line.
  - `sb_exec SANDBOX TIMEOUT_SECONDS [EXTRA_FLAGS...] -- COMMAND...`: returns the remote exit code, or 124 on timeout.
  - `sandbox_ready NAME`
  - `paddock_py ARGS...`
- Produces `scripts/ci/install-prover.sh <tag>`, which installs `$HOME/.local/bin/openshell-prover`.
- Produces `scripts/ci/run-cell.sh <bundle> <tag> <runner> [--live]`, which:
  - writes `results/<bundle>--<tag>--<runner>.json` and `results/logs/<bundle>--<tag>--<runner>/`;
  - exits 0 only when the cell passes.
- **The `tests/allow.sh` contract.** `run-cell.sh` runs each bundle's `tests/allow.sh` with bash, once per auth mode. It exports these variables:
  - `PADDOCK_ROOT`, `PADDOCK_BUNDLE_DIR`, `PADDOCK_SANDBOX`, `PADDOCK_AUTH_MODE`
  - `PADDOCK_LIVE` (`0` or `1`)
  - `PADDOCK_LOG_DIR`, `PADDOCK_CHECKS_FILE`

  `allow.sh` records its checks with `record_check`. A non-zero exit is recorded as an `error`.

- [ ] **Step 1: Write the failing tests.** These tests need bash and jq, so they run on Linux CI and are skipped on Windows.

Create `tests/unit/test_ci_lib.py`:

```python
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "lib.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not shutil.which("bash") or not shutil.which("jq"),
    reason="bash helper tests run on Linux (CI)",
)


def run_lib(tmp_path, fake_openshell, snippet):
    """Source lib.sh with a fake `openshell` first on PATH, then run a bash snippet."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    fake = bin_dir / "openshell"
    fake.write_text("#!/usr/bin/env bash\n" + fake_openshell + "\n", encoding="utf-8")
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    return subprocess.run(
        ["bash", "-c", f'source "{LIB}"; {snippet}'],
        env=env, capture_output=True, text=True, check=False,
    )


def test_exec_flags_follow_cli_help(tmp_path):
    new = run_lib(tmp_path / "new", 'echo "  --no-tty  --no-login-shell  --timeout <T>"', "exec_flags")
    old = run_lib(tmp_path / "old", 'echo "  --tty  --no-tty  --timeout <T>"', "exec_flags")
    assert new.stdout.split() == ["--no-tty", "--no-login-shell"]
    assert old.stdout.split() == ["--no-tty"]


def test_gateway_connected_rejects_disconnected_status(tmp_path):
    result = run_lib(tmp_path, """echo '{"status":"disconnected","gateway":"openshell"}'""", "gateway_connected")
    assert result.returncode != 0


def test_gateway_connected_accepts_connected_status(tmp_path):
    result = run_lib(tmp_path, """echo '{"status":"connected"}'""", "gateway_connected")
    assert result.returncode == 0


def test_gateway_connected_falls_back_to_text_status(tmp_path):
    fake = 'if [ "${2:-}" = "-o" ]; then echo "error: unexpected argument" >&2; exit 2; fi\necho "Version: 0.0.116"'
    assert run_lib(tmp_path, fake, "gateway_connected").returncode == 0


def test_sandbox_ready_reads_the_phase(tmp_path):
    ready = run_lib(tmp_path / "a", """echo '{"phase":"Ready"}'""", "sandbox_ready demo")
    provisioning = run_lib(tmp_path / "b", """echo '{"phase":"Provisioning"}'""", "sandbox_ready demo")
    assert ready.returncode == 0
    assert provisioning.returncode != 0


def test_record_check_flattens_tabs_and_newlines(tmp_path):
    checks = tmp_path / "checks.tsv"
    snippet = f'PADDOCK_CHECKS_FILE="{checks}" record_check demo fail "$(printf "a\\tb\\nc")"'
    result = run_lib(tmp_path, "exit 0", snippet)
    assert result.returncode == 0
    assert checks.read_text(encoding="utf-8") == "demo\tfail\ta b c\n"
```

- [ ] **Step 2: Check that the tests are skipped locally on Windows.**

Run: `python -m pytest tests/unit/test_ci_lib.py -v`
Expected on Windows: `6 skipped`. They run for real in CI (Task 9). On a Linux machine the same command fails with `exec_flags: command not found`, because the helpers do not exist yet.

- [ ] **Step 3: Append the helpers to `scripts/ci/lib.sh`.**

```bash

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
```

- [ ] **Step 4: Create `scripts/ci/install-prover.sh`.**

```bash
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
```

- [ ] **Step 5: Create `scripts/ci/run-cell.sh`.**

```bash
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
  local mode="$1" provider_file="$2"
  local sandbox="paddock-${bundle}-${mode}" provider="paddock-${bundle}-${mode}"
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
      cred_args+=(--credential "$env_name=paddock-ci-dummy-credential")
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
if bash "$PADDOCK_ROOT/scripts/ci/install-openshell.sh" "$version" >"$PADDOCK_LOG_DIR/install.log" 2>&1; then
  record_check setup pass "OpenShell $version"
else
  record_check setup error "installing OpenShell $version failed; see install.log"
  exit 1
fi
XDG_RUNTIME_DIR="/run/user/$(id -u)"
export XDG_RUNTIME_DIR
if [ "$version" = "$primary" ] &&
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
  run_mode "${PADDOCK_AUTH_MODES[$i]}" "$bundle_dir/${PADDOCK_PROVIDER_FILES[$i]}"
done
```

- [ ] **Step 6: Run the linters and the tests.**

```bash
chmod +x scripts/ci/*.sh
git update-index --chmod=+x scripts/ci/install-openshell.sh scripts/ci/install-prover.sh scripts/ci/run-cell.sh
python -m pytest tests/unit -v
```

Expected: every test passes, and the six `test_ci_lib.py` tests are skipped on Windows. If shellcheck is available locally (`shellcheck --version`), also run `shellcheck -x scripts/ci/*.sh` and expect no output. CI runs shellcheck in any case (Task 9).

- [ ] **Step 7: Commit.**

```bash
git add scripts/ci tests/unit/test_ci_lib.py
git commit -s -m "Add the per-cell runner, prover install, and bash helper tests"
```

---

### Task 9: The CI workflow (M1 exit)

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `python -m paddock matrix|validate|report` (Tasks 4–7) and `scripts/ci/run-cell.sh` (Task 8).
- Produces:
  - The workflow `ci`, with the jobs `checks`, `plan`, `cell` and `report`.
  - Artifacts: `cell-<bundle>--<tag>--<runner>`, which contains the `results/` folder, and `compatibility-report`, which contains `COMPATIBILITY.md`.

- [ ] **Step 1: Create `.github/workflows/ci.yml`.**

```yaml
name: ci
on:
  pull_request:
  push:
    branches: [main]
  schedule:
    - cron: '17 3 * * *'
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  checks:
    name: unit tests and linters
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: '3.12'
      - run: python -m pip install -r requirements-dev.txt
      - run: python -m pytest -v
      - run: PYTHONPATH=scripts python -m paddock validate
      - name: shellcheck
        run: |
          mapfile -t scripts < <(git ls-files '*.sh')
          if [ "${#scripts[@]}" -gt 0 ]; then shellcheck -x "${scripts[@]}"; fi

  plan:
    needs: checks
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    outputs:
      matrix: ${{ steps.plan.outputs.matrix }}
      has_cells: ${{ steps.plan.outputs.has_cells }}
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: '3.12'
      - run: python -m pip install -r requirements-dev.txt
      - name: List the files this pull request changes
        if: github.event_name == 'pull_request'
        env:
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
          HEAD_SHA: ${{ github.event.pull_request.head.sha }}
        run: git diff --name-only "$BASE_SHA...$HEAD_SHA" | tee "$RUNNER_TEMP/changed.txt"
      - id: plan
        env:
          EVENT_NAME: ${{ github.event_name }}
        run: |
          args=(--github-output "$GITHUB_OUTPUT")
          if [ "$EVENT_NAME" = pull_request ]; then
            args+=(--changed-files "$RUNNER_TEMP/changed.txt")
          fi
          PYTHONPATH=scripts python -m paddock matrix "${args[@]}"

  cell:
    needs: plan
    if: needs.plan.outputs.has_cells == 'true'
    strategy:
      fail-fast: false
      matrix: ${{ fromJSON(needs.plan.outputs.matrix) }}
    name: ${{ matrix.bundle }} / ${{ matrix.openshell_version }} / ${{ matrix.runner }}
    runs-on: ${{ matrix.runner }}
    timeout-minutes: 45
    env:
      BUNDLE: ${{ matrix.bundle }}
      OPENSHELL_TAG: ${{ matrix.openshell_version }}
      RUNNER_LABEL: ${{ matrix.runner }}
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: '3.12'
      - run: python -m pip install -r requirements-dev.txt
      - name: Run the cell
        run: bash scripts/ci/run-cell.sh "$BUNDLE" "$OPENSHELL_TAG" "$RUNNER_LABEL"
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        if: always()
        with:
          name: cell-${{ matrix.bundle }}--${{ matrix.openshell_version }}--${{ matrix.runner }}
          path: results/
          if-no-files-found: warn
          retention-days: 14

  report:
    needs: [plan, cell]
    if: always()
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: '3.12'
      - run: python -m pip install -r requirements-dev.txt
      - uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1
        if: needs.plan.outputs.has_cells == 'true'
        with:
          pattern: cell-*
          path: results
          merge-multiple: true
      - name: Build the compatibility report
        run: |
          mkdir -p results
          PYTHONPATH=scripts python -m paddock report --results results | tee COMPATIBILITY.md >> "$GITHUB_STEP_SUMMARY"
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        with:
          name: compatibility-report
          path: COMPATIBILITY.md
          retention-days: 30
```

- [ ] **Step 2: Commit, push, and open the pull request.**

```bash
git add .github/workflows/ci.yml
git commit -s -m "Add the CI workflow: checks, matrix plan, cells, and report"
git push -u origin m1-harness
gh pr create --repo paddockhq/paddock --base main --head m1-harness \
  --title "M1: CI harness" \
  --body "Implements Plan 1 Tasks 3-9 (docs/superpowers/plans/2026-10-05-paddock-plan-1-m0-m2.md). With no bundles yet, CI should pass with an empty matrix and report 'No bundles yet.'"
```

- [ ] **Step 3: Watch the run and check the M1 exit criterion.**

```bash
gh pr checks m1-harness --repo paddockhq/paddock --watch
run_id="$(gh run list --repo paddockhq/paddock --workflow ci.yml --branch m1-harness --limit 1 --json databaseId --jq '.[0].databaseId')"
gh run view "$run_id" --repo paddockhq/paddock --json jobs --jq '.jobs[] | .name + ": " + .conclusion'
```

Expected:
- `unit tests and linters: success`. On Linux the six bash helper tests run instead of being skipped.
- `plan: success`
- the `cell` job is `skipped`, because there are no bundles yet
- `report: success`, and its job summary says `No bundles yet.`

That meets the M1 exit criterion: CI runs end to end against an empty bundle list. Q1 was resolved during research, by using `openshell sandbox get --policy-only`.

If `unit tests and linters` fails, read the log with `gh run view "$run_id" --repo paddockhq/paddock --log-failed`, fix the cause, commit with `-s`, push, and watch again.

- [ ] **Step 4: Merge.**

```bash
gh pr merge m1-harness --repo paddockhq/paddock --merge --delete-branch
git switch main
git pull --ff-only
```

---

### Task 10: The OpenCode bundle (M2 exit)

**Files:**
- Create: `bundles/opencode/bundle.yaml`
- Create: `bundles/opencode/policy.yaml`
- Create: `bundles/opencode/boundary.yaml`
- Create: `bundles/opencode/providers/opencode-openrouter.yaml`
- Create: `bundles/opencode/tests/allow.sh`
- Create: `bundles/opencode/README.md`
- Modify: `README.md` (add the bundle table)

**Interfaces:**
- Consumes:
  - the `allow.sh` contract and the `lib.sh` helpers `sb_exec`, `record_check` and `paddock_py` (Task 8);
  - the CLI `events` command (Task 6);
  - `bundle-env`, which provides `PADDOCK_ENV_ARGS` (Task 4).
- Produces:
  - the bundle `opencode`;
  - the provider profile id `paddock-opencode-openrouter`;
  - test model `openrouter/nvidia/nemotron-3.5-lightning:free`, which callers can override with the `OPENCODE_TEST_MODEL` env var.

Facts the files rely on. They come from Plan 1 research and were checked against OpenShell v0.1.2 and OpenCode v2.0.21 sources.

**The image:**
- It sets no `USER`, so OpenShell runs it as UID and GID 1000 with `HOME=/sandbox`. `/sandbox` is also the working folder.
- `/usr/local/bin/opencode` is a regular file, not a symlink. It is a Bun single executable built on Alpine with busybox, and it has no curl.

**How OpenCode behaves:**
- `opencode run --standalone -m openrouter/<model>` sends `POST https://openrouter.ai/api/v1/chat/completions`, using the key in `OPENROUTER_API_KEY`.
- With `OPENCODE_DISABLE_MODELS_FETCH=1`, it reads its bundled model catalog, which includes `nvidia/nemotron-3.5-lightning:free`, and never contacts `models.opencode.ai`.
- It also talks to its own child server over 127.0.0.1. OpenShell allows loopback inside the sandbox.
- With an invalid key, OpenRouter answers `401 {"error":{"message":"User not found.","code":401}}`. OpenCode then prints `Error: ...` and exits 1.

**How OpenShell treats the policy:**
- An endpoint's `enforcement` defaults to `audit`, so every endpoint sets `enforce`.
- The prover compares `run_as_user` and `run_as_group`; matching values pass.
- The prover returns `unsupported` when it would have to compare filesystem rules with different paths. That is why `boundary.yaml` repeats `policy.yaml`'s filesystem section exactly.

- [ ] **Step 1: Create the branch and confirm the pinned image digest.**

```bash
git switch -c m2-opencode
TOK=$(curl -fsS 'https://ghcr.io/token?scope=repository:anomalyco/opencode:pull' | python -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -fsSI -H "Authorization: Bearer $TOK" \
  -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json' \
  https://ghcr.io/v2/anomalyco/opencode/manifests/2.0.21 | grep -i docker-content-digest
```

Expected: `docker-content-digest: sha256:6d3cebbaaeed11b9dd1ea6d2ca8a3ec17eb548c5aed37e17c7ae80fd8b2f22b2`. If the digest differs, stop and tell the maintainer: a re-pushed tag is a supply-chain red flag.

- [ ] **Step 2: Create `bundles/opencode/bundle.yaml`.**

```yaml
schema: 1
name: opencode
agent:
  display_name: OpenCode
  homepage: https://github.com/anomalyco/opencode
  license: MIT
  version: "2.0.21"
distribution: upstream
image: ghcr.io/anomalyco/opencode:2.0.21@sha256:6d3cebbaaeed11b9dd1ea6d2ca8a3ec17eb548c5aed37e17c7ae80fd8b2f22b2
revision: 1
command: [opencode]
version_command: [opencode, --version]
env:
  OPENCODE_DISABLE_MODELS_FETCH: "1"
  OPENCODE_DISABLE_AUTOUPDATE: "1"
auth:
  - mode: api-key
    provider_file: providers/opencode-openrouter.yaml
```

- [ ] **Step 3: Create `bundles/opencode/policy.yaml`.**

```yaml
# PadDock sandbox policy for OpenCode 2.x (ghcr.io/anomalyco/opencode).
# Network access comes only from the attached provider profile: openrouter.ai,
# POST /api/v1/chat/completions, for /usr/local/bin/opencode and its children.
version: 1
filesystem_policy:
  include_workdir: false
  read_only:
    - /usr
    - /lib
    - /bin
    - /etc
    - /proc
    - /dev/urandom
  read_write:
    - /sandbox      # working folder and HOME for UID 1000: OpenCode state lives here
    - /tmp          # Bun extracts native code here at start-up
    - /dev/null
landlock:
  compatibility: best_effort
process:
  run_as_user: "1000"
  run_as_group: "1000"
```

- [ ] **Step 4: Create `bundles/opencode/boundary.yaml`.**

```yaml
# The most access PadDock ever accepts for the OpenCode bundle (spec §6.4).
# CI checks the gateway-composed policy against this file with openshell-prover.
# Changing this file needs maintainer review; it is never merged automatically.
version: 1
filesystem_policy:
  include_workdir: false
  read_only:
    - /usr
    - /lib
    - /bin
    - /etc
    - /proc
    - /dev/urandom
  read_write:
    - /sandbox
    - /tmp
    - /dev/null
landlock:
  compatibility: best_effort
process:
  run_as_user: "1000"
  run_as_group: "1000"
network_policies:
  openrouter_chat:
    name: openrouter-chat
    endpoints:
      - host: openrouter.ai
        port: 443
        protocol: rest
        enforcement: enforce
        rules:
          - allow:
              method: POST
              path: /api/v1/chat/completions
    binaries:
      - path: /usr/local/bin/opencode
```

- [ ] **Step 5: Create `bundles/opencode/providers/opencode-openrouter.yaml`.**

```yaml
# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026 The PadDock Authors
# SPDX-License-Identifier: Apache-2.0
#
# PadDock provider profile, derived from OpenShell v0.1.2 providers/openrouter.yaml.
# Import it with:
#   openshell provider profile lint   -f providers/opencode-openrouter.yaml
#   openshell provider profile import -f providers/opencode-openrouter.yaml
#
# Client binaries:   opencode.
# Reference layout:  ghcr.io/anomalyco/opencode 2.x, where /usr/local/bin/opencode
#                    is a regular file (not a symlink).
# Credential scope:  OPENROUTER_API_KEY, sent as "Authorization: Bearer" to the
#                    endpoint below and nowhere else.
# Endpoint access:   openrouter.ai, POST /api/v1/chat/completions only. NVIDIA's
#                    example grants read-write access to every path on the host.
# Smoke test:        opencode run --standalone -m openrouter/nvidia/nemotron-3.5-lightning:free "Reply with exactly: OK"
id: paddock-opencode-openrouter
display_name: OpenRouter for OpenCode (PadDock)
description: OpenRouter chat completions for the OpenCode CLI, least privilege
category: inference
inference_capable: true
credentials:
  - name: api_key
    description: OpenRouter API key
    env_vars: [OPENROUTER_API_KEY]
    required: true
    auth_style: bearer
    header_name: authorization
discovery:
  credentials: [api_key]
endpoints:
  - host: openrouter.ai
    port: 443
    protocol: rest
    enforcement: enforce
    rules:
      - allow:
          method: POST
          path: /api/v1/chat/completions
binaries: [/usr/local/bin/opencode]
```

- [ ] **Step 6: Create `bundles/opencode/tests/allow.sh`.**

```bash
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
```

Make it executable for Git:

```bash
git update-index --add --chmod=+x bundles/opencode/tests/allow.sh
```

- [ ] **Step 7: Create `bundles/opencode/README.md`.**

````markdown
# OpenCode bundle

Runs [OpenCode](https://github.com/anomalyco/opencode) 2.0.21 (MIT) inside an
OpenShell sandbox. The agent can reach only OpenRouter's chat completions API.

| | |
|---|---|
| Image | `ghcr.io/anomalyco/opencode:2.0.21@sha256:6d3cebbaaeed11b9dd1ea6d2ca8a3ec17eb548c5aed37e17c7ae80fd8b2f22b2` (official, pinned by digest) |
| Network | `openrouter.ai:443`, `POST /api/v1/chat/completions` only, for `/usr/local/bin/opencode` and the processes it starts |
| Writable | `/sandbox` (working folder and home), `/tmp` |
| Runs as | UID/GID 1000 |
| Auth modes | OpenRouter API key |

## Use it

```shell
git clone --depth 1 https://github.com/paddockhq/paddock
cd paddock/bundles/opencode
openshell provider profile import -f providers/opencode-openrouter.yaml
export OPENROUTER_API_KEY=...   # your key; OpenShell stores it, the sandbox only sees a placeholder
openshell provider create --name openrouter-opencode --type paddock-opencode-openrouter --credential OPENROUTER_API_KEY
openshell sandbox create --name opencode \
  --from ghcr.io/anomalyco/opencode:2.0.21@sha256:6d3cebbaaeed11b9dd1ea6d2ca8a3ec17eb548c5aed37e17c7ae80fd8b2f22b2 \
  --policy policy.yaml --provider openrouter-opencode \
  --env OPENCODE_DISABLE_MODELS_FETCH=1 --env OPENCODE_DISABLE_AUTOUPDATE=1 \
  -- opencode -m openrouter/nvidia/nemotron-3.5-lightning:free
```

## Why these settings

- `OPENCODE_DISABLE_MODELS_FETCH=1` makes OpenCode use its built-in model list
  instead of downloading one from `models.opencode.ai`. Models that OpenRouter
  added after OpenCode 2.0.21 was built are not available until the bundle moves
  to a newer OpenCode.
- `OPENCODE_DISABLE_AUTOUPDATE=1` stops update checks. OpenShell also blocks a
  self-updated binary, because it pins each binary's hash on first use.
- NVIDIA's example OpenRouter profile allows every path on `openrouter.ai`. This
  bundle allows only the chat completions endpoint, because any allowed path is
  also reachable by every tool the agent runs (spec §6.2, R2).

## Tested with

See the latest CI run's compatibility report for the OpenShell releases and
architectures this bundle passes on.
````

- [ ] **Step 8: Validate locally, then commit.**

Run: `python -m paddock validate` with `PATH="$PWD/.venv/Scripts:$PATH" PYTHONPATH=scripts` in front.
Expected: `ok: opencode`.

```bash
git add bundles/opencode
git commit -s -m "Add the OpenCode bundle"
```

- [ ] **Step 9: Add the bundle table to the root README.**

In `README.md`, insert this section above `## Layout`:

```markdown
## Bundles

| Agent | Bundle | Auth |
|---|---|---|
| OpenCode 2.0.21 | [bundles/opencode](bundles/opencode) | OpenRouter API key |
```

```bash
git add README.md
git commit -s -m "List the OpenCode bundle in the README"
```

- [ ] **Step 10: Push, open the pull request, and watch the four cells.**

```bash
git push -u origin m2-opencode
gh pr create --repo paddockhq/paddock --base main --head m2-opencode \
  --title "M2: OpenCode bundle" \
  --body "Implements Plan 1 Task 10. CI runs opencode on OpenShell v0.1.2 and v0.0.116, on x64 and arm64."
gh pr checks m2-opencode --repo paddockhq/paddock --watch
```

Then download the report and logs:

```bash
run_id="$(gh run list --repo paddockhq/paddock --workflow ci.yml --branch m2-opencode --limit 1 --json databaseId --jq '.[0].databaseId')"
rm -rf ci-out && gh run download "$run_id" --repo paddockhq/paddock --dir ci-out
cat ci-out/compatibility-report/COMPATIBILITY.md
```

- [ ] **Step 11: Fix failures, using this table.**

Read the failing check's detail in `COMPATIBILITY.md`, and its log under `ci-out/cell-*/logs/<cell>/`. Apply the matching fix, commit with `-s`, push, and repeat Step 10 until every v0.1.2 cell passes.

| Symptom | Fix |
|---|---|
| `prover:api-key` fails with a counterexample naming a filesystem path from OpenShell's baseline list (`/app`, `/var/log`), with the docs' baseline access | The gateway adds baseline paths. Add the same path, with the same access, to both `policy.yaml` and `boundary.yaml`. |
| `prover:api-key` errors with `unsupported` | Read `.reason` in `prover-api-key.json`. Change the policy shape the reason names (for example a path the boundary does not list identically), keeping `policy.yaml` and `boundary.yaml` identical outside `network_policies`. Never widen the network rule to make the prover pass. |
| `egress:api-key` fails listing `models.opencode.ai:443` | The env flags did not reach OpenCode. Check that `allow.sh` passes `"${PADDOCK_ENV_ARGS[@]}"` to `sb_exec`, and that `opencode-run-api-key.log` shows no warning about `--env`. |
| `egress:api-key` fails listing `127.0.0.1` | Loopback inside the sandbox was denied, which contradicts OpenShell's docs. Record the log lines and ask the maintainer: this is a possible upstream issue, so do not loosen the policy. |
| `version:api-key` or `opencode-run-api-key.log` shows `EACCES` or `permission denied` under `/tmp/opencode` | The image ships a root-owned `/tmp/opencode`. Add `TMPDIR: "/sandbox"` to `env` in `bundle.yaml` and to the README's `sandbox create` command. |
| `upstream-auth-error:api-key` fails, and `opencode-run-api-key.log` shows OpenRouter's 401 in different words | Add those words to the `grep -qiE` pattern in `allow.sh`. |
| `upstream-auth-error:api-key` fails, and the log shows a certificate or TLS error | This is a real failure: OpenCode does not trust OpenShell's interception CA (`/etc/openshell-tls/`). Keep `/etc` read-only but readable, record the error, and ask the maintainer before changing anything. |
| `sandbox:api-key` fails | Read `sandbox-api-key.log` and `sandbox-logs-api-key.txt`, fix the cause, and record it in the bundle README if users could hit it. |
| v0.0.116 cells fail on `profile-lint`, `provider` or `sandbox` because the release lacks a feature (for example REST `rules` in provider profiles, or `provider profile` commands) | Add `openshell_min_version: "v0.1.0"` to `bundle.yaml`. Add this line to the README, under "Tested with": "OpenShell v0.0.x is not supported: (the missing feature)." The matrix then skips v0.0.116 for this bundle. |

The M2 exit criterion is met when either of these holds:
- all four cells pass; or
- both v0.1.2 cells pass and v0.0.116 is excluded with a documented `openshell_min_version`.

- [ ] **Step 12: Merge.**

```bash
gh pr merge m2-opencode --repo paddockhq/paddock --merge --delete-branch
git switch main
git pull --ff-only
```

---

### Task 11: Weekly live smoke test

**Files:**
- Create: `.github/workflows/live-smoke.yml`

**Interfaces:**
- Consumes:
  - `scripts/ci/run-cell.sh <bundle> <tag> <runner> --live` (Task 8);
  - `allow.sh` live mode and `OPENCODE_TEST_MODEL` (Task 10);
  - the repository secret `OPENROUTER_API_KEY`.
- Produces: the workflow `live-smoke` (weekly, main branch only) and the artifact `live-smoke-opencode`.

- [ ] **Step 1 (maintainer): Add the OpenRouter key as a repository secret.**

Create an API key at https://openrouter.ai/settings/keys. A free account is enough, because the test uses a free model. Then run:

```bash
gh secret set OPENROUTER_API_KEY --repo paddockhq/paddock
```

Paste the key when prompted. Expected: `✓ Set Actions secret OPENROUTER_API_KEY for paddockhq/paddock`.

- [ ] **Step 2: Create `.github/workflows/live-smoke.yml`.**

```yaml
name: live-smoke
# Weekly real-request smoke test (spec section 7.4, step 5). Main branch only;
# pull requests never receive the secret.
on:
  schedule:
    - cron: '41 4 * * 1'
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: live-smoke
  cancel-in-progress: false

jobs:
  opencode:
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-24.04
    timeout-minutes: 45
    env:
      OPENCODE_TEST_MODEL: openrouter/nvidia/nemotron-3.5-lightning:free
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: '3.12'
      - run: python -m pip install -r requirements-dev.txt
      - name: Check that the free model is still listed
        run: |
          model="${OPENCODE_TEST_MODEL#openrouter/}"
          if ! curl -fsS https://openrouter.ai/api/v1/models | jq -e --arg m "$model" '[.data[].id] | index($m) != null' >/dev/null; then
            echo "::error::OpenRouter no longer lists $model. Pick another free model that OpenCode's bundled catalog knows and update OPENCODE_TEST_MODEL."
            exit 1
          fi
      - name: Run the OpenCode bundle with a real key
        env:
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
        run: |
          version="$(jq -r '.versions[0]' scripts/ci/openshell-versions.json)"
          bash scripts/ci/run-cell.sh opencode "$version" ubuntu-24.04 --live
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        if: always()
        with:
          name: live-smoke-opencode
          path: results/
          retention-days: 14
```

- [ ] **Step 3: Commit through a pull request, then run the smoke test on main.**

```bash
git switch -c live-smoke
git add .github/workflows/live-smoke.yml
git commit -s -m "Add the weekly live smoke test"
git push -u origin live-smoke
gh pr create --repo paddockhq/paddock --base main --head live-smoke \
  --title "Weekly live smoke test" --body "Implements Plan 1 Task 11."
gh pr checks live-smoke --repo paddockhq/paddock --watch
gh pr merge live-smoke --repo paddockhq/paddock --merge --delete-branch
git switch main
git pull --ff-only
gh workflow run live-smoke.yml --repo paddockhq/paddock --ref main
sleep 10
run_id="$(gh run list --repo paddockhq/paddock --workflow live-smoke.yml --limit 1 --json databaseId --jq '.[0].databaseId')"
gh run watch "$run_id" --repo paddockhq/paddock --exit-status
```

Expected: the run succeeds. In the artifact, `checks.tsv` lists `live-answer:api-key	pass` and `egress:api-key	pass`.

If `live-answer` fails because the free model hit its rate limit, re-run once later. If it fails again, record the error and tell the maintainer before changing the model.

- [ ] **Step 4: Update the project memory note.**

Report to the maintainer: Plan 1 is complete. Include the run links for the M0 workflow, the M1 CI run, the M2 CI run and the first live smoke run. The next step is writing Plan 2 (M3, the shared must-block suite).
