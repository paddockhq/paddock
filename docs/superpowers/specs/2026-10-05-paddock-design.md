# PadDock: Design Spec

- **Status:** design approved in conversation on 2026-10-05; this document awaits review.
- **Author:** Paresh Sahoo, with Claude
- **Builds on:** NVIDIA OpenShell v0.1.2 (released 2026-09-28)

## 1. Summary

PadDock is an open-source, community-maintained collection of tested **bundles** for NVIDIA OpenShell. A bundle is everything needed to run one AI coding agent safely inside an OpenShell sandbox:

- a container image
- a least-privilege sandbox policy
- provider profiles for API-key and subscription login
- tests

Automated CI re-tests every bundle against each new OpenShell release. This keeps the collection current, which is where NVIDIA's own catalog failed.

The first bundles are OpenCode, Codex CLI and Claude Code.

## 2. Goals, success criteria, non-goals

### Goal

Build community standing in agent security by becoming the source that OpenShell's documentation and maintainers point to for ready-made, vetted agent setups.

### Success criteria

The headline criterion is that the OpenShell docs or maintainers link to or recommend PadDock. The intermediate milestones are:

1. Three bundles pass the full test suite on two consecutive OpenShell releases.
2. NVIDIA maintainers respond to the introductory GitHub Discussion.
3. The maintainer becomes a "vouched" OpenShell contributor.
4. At least one security finding is responsibly disclosed and then published.

### Constraints

- The project has one maintainer working about one day a week. Ongoing upkeep must therefore be automated: bots raise update PRs and CI decides whether they are safe.
- The maintainer develops on Windows. OpenShell supports Windows only through WSL2 (experimental), so CI is the source of truth and local runs are a convenience.

### Non-goals for version 1

- **No PadDock CLI or installer.** Users use the stock `openshell` CLI. This was "Approach B" and is deferred until users ask for it.
- **No web UI, Kubernetes operator or native Windows support.** NVIDIA, Red Hat and others are already building these.
- **No bundled access to GitHub, package registries or MCP servers.** Users who need that access attach separate provider profiles.
- **No subscription login for OpenCode.** This is deferred to phase 2; see §6.3.
- **No published images for proprietary agents.** See §5.3.

## 3. Background

- **OpenShell** is NVIDIA's runtime for running agents in sandboxes. Its main parts:
  - It is written in Rust and licensed Apache-2.0.
  - A gateway (the control plane) manages one supervisor per sandbox.
  - Kernel-level filesystem and process controls restrict what the workload can do.
  - Every outbound connection is checked against policy.
  - Credentials are substituted into requests only at approved endpoints.
  - A formal-verification prover checks policies against a boundary.
- **NVIDIA retired its community catalog** (NVIDIA/OpenShell-Community) just before GA:
  - Its README now tells teams to keep their own "workload collections": a Dockerfile, a policy, provider profiles, build and release automation, and compatibility notes.
  - `openshell sandbox create --from` no longer expands catalog names.
  - The docs now use made-up images such as `registry.example.com/your-org/claude-agent:latest`.
- **NVIDIA's example provider profiles assume old images.** The profiles in `providers/` name binary paths from reference image layouts that no longer ship. A user who imports them unchanged with a different image gets rules that do not match.
- **OpenShell is moving fast.** v0.1.0 came out on 2026-09-25 and v0.1.2 three days later, and only the latest and previous minor release lines are supported. Bundles therefore need continuous re-testing.

## 4. Users and user flow

The primary users are developers and platform or security teams who want to run a coding agent under OpenShell without writing and debugging a policy from scratch.

A user runs a bundle like this:

1. **Download the bundle's release tarball and verify its checksum.** The tarball contains the policy and provider files. `--policy` accepts only a local file, so the files must be downloaded first.
2. **Import the provider profiles:**
   ```shell
   openshell provider profile import --from providers
   ```
3. **Create a provider instance** using either an API key or subscription tokens (§6.3):
   ```shell
   openshell provider create --name <name> --type <profile-id> --credential <ENV_VAR>
   ```
4. **Start the agent:**
   ```shell
   openshell sandbox create --name <name> --from <image@sha256:digest> --policy policy.yaml --provider <name> -- <agent>
   ```
   For a Dockerfile-only bundle, the user first builds the image locally, for example `docker build https://github.com/paddockhq/paddock.git#<tag>:bundles/claude-code`.

## 5. Repository layout and bundle contract

### 5.1 Layout

```
bundles/<agent>/
  bundle.yaml       metadata (schema in 5.2)
  Dockerfile        absent when distribution is "upstream"
  policy.yaml       least-privilege sandbox policy
  boundary.yaml     maximum access ever acceptable; checked by the prover
  providers/*.yaml  provider profiles matched to this image's binary paths
  tests/allow.sh    must-work tests for this bundle
  README.md         copy-paste commands and a provider-file header (5.4)
tests/deny/         shared must-block tests, run against every bundle
scripts/            CI helpers (bundle loader, test runner, report generator)
.github/workflows/  CI, nightly, release, weekly live smoke test
COMPATIBILITY.md    generated: bundle x OpenShell version -> pass/fail
```

Each bundle has its own complete `policy.yaml`. There is no inheritance or templating, because OpenShell has no include mechanism and complete files are easier to review.

### 5.2 `bundle.yaml`

```yaml
schema: 1
name: codex                         # folder name and image name
agent:
  display_name: Codex CLI
  homepage: https://github.com/openai/codex
  license: Apache-2.0               # SPDX id of the agent itself
  version: "0.0.0"                  # managed by Renovate
distribution: built                 # upstream | built | dockerfile-only
image: ghcr.io/paddockhq/codex      # for upstream: full ref with @sha256 digest
revision: 1                         # the r<N> in tags; bump on any policy or Dockerfile change
command: [codex]                    # program started after `--`
version_command: [codex, --version]
auth:
  - mode: api-key
    provider_file: providers/codex-apikey.yaml
  - mode: subscription
    provider_file: providers/codex-subscription.yaml
```

### 5.3 Distribution modes

| Mode | Used for | What PadDock publishes |
|---|---|---|
| `upstream` | Agents with an official image (OpenCode: `ghcr.io/anomalyco/opencode`) | Nothing. The image is pinned by digest and Renovate bumps it. |
| `built` | Agents with permissive licenses (Codex CLI, Apache-2.0) | A signed multi-arch image on GHCR (§8). |
| `dockerfile-only` | Proprietary agents (Claude Code) | Only the Dockerfile. CI builds the image for testing and never pushes it. |

Claude Code's LICENSE.md reads: "© Anthropic PBC. All rights reserved. Use is subject to Anthropic's Commercial Terms of Service." Redistributing it in a public image is therefore not done.

### 5.4 File conventions

- **Provider file header.** Every provider file starts with the same comment header NVIDIA's examples use:
  - the client binaries it expects
  - the image layout it assumes
  - the credential scope
  - the endpoint access it grants
  - a smoke test command
- **Attribution.** Files derived from NVIDIA's examples keep their SPDX attribution, and the repo's NOTICE file records them.

## 6. Policy and provider design

### 6.1 How access is composed

`policy.yaml` holds:

- the filesystem rules
- the process rules
- any network rules the agent needs beyond its model API (none in v1)

The model API comes from the attached provider profile: its credential, endpoints and binaries. OpenShell composes the effective policy just in time from the base policy plus provider layers. Inside the sandbox, the credential exists only as a placeholder environment variable. The proxy swaps in the real value only on requests to the profile's endpoints.

### 6.2 Rules every bundle follows

Tests (§7) and the prover enforce these rules.

- **R1. Exact hostnames, no wildcards.**
  - OpenShell answers DNS only for hosts named in rules, using placeholder addresses.
  - A wildcard authorizes DNS queries for every matching name, which opens a DNS-label exfiltration channel.
- **R2. Every allowed host is a potential exfiltration path.**
  - A rule that lists the agent binary also covers every process the agent starts (OpenShell docs, "Binary Matching"). Any `curl`, `git` or `python` the agent runs can reach the same hosts.
  - Host lists are therefore minimal.
  - Where the protocol is `rest`, method and path rules narrow access further. For example, the model API allows only the inference paths the agent uses.
- **R3. Non-essential traffic is disabled in the image, and those hosts are dropped from the rules.** Each Dockerfile, or the bundle README for upstream images, sets:
  - **Claude Code:** `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` and `DISABLE_AUTOUPDATER=1`.
  - **OpenCode:** `OPENCODE_DISABLE_AUTOUPDATE`, `OPENCODE_DISABLE_MODELS_FETCH`, `OPENCODE_DISABLE_LSP_DOWNLOAD`, `OPENCODE_DISABLE_SHARE` and `OPENCODE_DISABLE_DEFAULT_PLUGINS`.
  - **Codex:** `check_for_update_on_startup = false` and analytics disabled in `config.toml`.

  Auto-update must be off for another reason too. OpenShell records a hash of each executable the first time it connects and denies later connections if the file changes.
- **R4. Binaries are listed by real path** (`readlink -f` inside the image), never through a symlink. Interpreted CLIs list their interpreter.
- **R5. Images run as a non-root `USER`.** The Docker and Podman drivers reject root images unless the policy sets a non-root `run_as_user`.
- **R6. Only a few folders are writable:** the working directory `/sandbox`, `/tmp`, and the agent's state directory under the image user's home (for example `.claude`, `.codex`, `.local/share/opencode`). Everything else is read-only. The allow tests confirm the exact path for each bundle.

Concrete case motivating R2 and R3: NVIDIA's example `claude-code.yaml` grants the claude binary read-write access to `sentry.io`. Under R2, any tool Claude runs can post data there, and Sentry accepts events for any project. PadDock's profile drops this host. A must-block test (§7.4) confirms whether the example profile actually leaks. If it does, that becomes the project's first disclosed finding.

### 6.3 Authentication modes

The login always happens on the user's own machine. The resulting secret is stored as an OpenShell provider credential, so no login websites are allowed and no browser runs in the sandbox.

| Agent | API key (`<agent>-apikey.yaml`) | Subscription (`<agent>-subscription.yaml`) |
|---|---|---|
| Claude Code | `ANTHROPIC_API_KEY` sent as the `x-api-key` header to `api.anthropic.com` | Pro/Max: `claude setup-token` on the host creates a long-lived token. It is delivered as the placeholder `CLAUDE_CODE_OAUTH_TOKEN` and replaced by the bearer credential only at `api.anthropic.com`. If this works as designed, the real token never enters the sandbox. |
| Codex CLI | `OPENAI_API_KEY` for `api.openai.com` | ChatGPT Plus/Pro: the tokens from the host's `~/.codex/auth.json` become `CODEX_AUTH_*` credentials, following NVIDIA's `codex.yaml`. Only Codex's API paths on `chatgpt.com` and `auth.openai.com` (token refresh) are allowed. `ab.chatgpt.com` (experiment lookups) is dropped if Codex works without it. |
| OpenCode | A provider key, for example OpenRouter | Not in v1. OpenCode offers ChatGPT and GitHub Copilot logins but no Claude Pro/Max login. This is phase 2. |

Known weak spot (Codex subscription): when Codex refreshes its login, the response returns a new short-lived access token to the CLI in plain text. A real token therefore exists inside the sandbox until it expires. This is documented in the bundle README and covered by a test that records the behavior.

### 6.4 Boundary file

`boundary.yaml` is a hand-written ceiling: the most access ever acceptable for that agent, covering all of its auth modes. CI uses the prover to check that each combined policy (base policy plus each provider profile) allows nothing beyond the boundary.

`boundary.yaml` changes require CODEOWNERS review and are never merged automatically. How CI obtains the combined policy is open question Q1.

### 6.5 Codex's built-in sandbox

Codex applies its own Landlock and seccomp sandbox on Linux. The bundle keeps it enabled, as defense in depth, unless CI shows it fails when nested inside OpenShell's sandbox. In that case the bundle runs Codex with `--sandbox danger-full-access` and the README explains why (Q3).

## 7. Testing

### 7.1 Where tests run

- **Primary:** GitHub-hosted `ubuntu-24.04` and `ubuntu-24.04-arm` runners, which are free for public repositories.
- **Feasibility is unproven.** OpenShell's own Docker-driver end-to-end tests run on larger runners (`linux-arm64-cpu8`), so Milestone 0 must establish whether the free runners can run OpenShell at all.
- **Fallback:** one small self-hosted VM that runs only scheduled jobs from the main branch, never PRs from forks.

### 7.2 Job setup

1. Install a pinned OpenShell release non-interactively:
   ```shell
   OPENSHELL_VERSION=vX.Y.Z install.sh
   ```
2. Start a local gateway with the Docker driver.
3. Download `openshell-prover-<arch>-unknown-linux-musl.tar.gz` from the same release and verify it against `openshell-prover-checksums-sha256.txt`.

### 7.3 Triggers and matrix

The matrix is every affected bundle x {latest OpenShell release, previous minor release}.

| Trigger | Scope |
|---|---|
| Pull request | Bundles changed by the PR, plus all bundles when `tests/` or `scripts/` change |
| Nightly | All bundles |
| OpenShell release (Renovate PR) | All bundles |
| Weekly, main branch only | Live smoke tests using secrets |

### 7.4 Checks per bundle, in order

1. **File checks.**
   - `openshell provider profile lint` on every provider file.
   - Policy validation: the gateway rejects invalid policies at create time.
   - `bundle.yaml` schema validation.
2. **Ceiling check.** For each auth mode, the prover checks that the combined policy stays within `boundary.yaml`. Any finding fails the job.
3. **Must-work tests** (`tests/allow.sh`). The sandbox is created with the bundle's image, policy and provider. The provider holds a dummy credential. Then:
   - **Version check:** `version_command` succeeds.
   - **Real request:** the agent makes its normal request to the model API. A pass requires two things. First, the response comes from the upstream service, for example an authentication error body with status 401. Second, the logs contain no `DENIED` line for that request. The status code alone is not enough, because OpenShell's own denials also return 403.
   - **Writable state:** the agent's state directory is writable.
4. **Must-block tests** (`tests/deny/`, shared).
   - **How a pass is judged:** every attempt must fail *and* produce a matching log line, either `NET:OPEN ... DENIED` or `HTTP:<METHOD> ... DENIED`, read with `openshell logs <sandbox> --source sandbox`. The log line proves OpenShell blocked the attempt rather than the network failing.
   - **Run mode 1:** from a process outside the agent's process tree, using `openshell sandbox exec -n <sandbox> --no-login-shell -- <test>`.
   - **Run mode 2 (worst-case child):** in a variant sandbox where the bundle's rules list the test harness shell in place of the agent binary. Child processes inherit the agent's rules (R2), so this models every tool call a prompt-injected agent could make.
   - **Initial catalog:**
     - a host that is not listed
     - a disallowed method or path on an allowed host
     - a DNS lookup of an unlisted name
     - raw TCP and UDP to an IP address
     - IPv6
     - a write outside the writable folders
     - `sentry.io` reached from a child process
     - an allowed host called with a literal attacker-supplied credential instead of the placeholder. The test records what the proxy does, for research.
5. **Live smoke test** (weekly, main branch only). A real "reply with OK" prompt for every auth mode. It uses repository secrets:
   - API keys
   - `CLAUDE_CODE_OAUTH_TOKEN`
   - the Codex `CODEX_AUTH_*` tokens
   - an OpenRouter key

   Secrets are never exposed to PR workflows from forks.

### 7.5 Findings job

A manually triggered job runs the must-block suite against NVIDIA's unmodified example provider profiles. Its output feeds the disclosure process (§9.2); it is never published directly.

### 7.6 Failure handling

- **A new OpenShell version breaks a bundle:**
  - The nightly run marks the bundle as broken for that version in `COMPATIBILITY.md`.
  - It opens an issue labelled with the bundle.
  - Other bundles are unaffected.
- **A must-block test passes, meaning access leaked:** this is a security issue. It is handled privately (§9.2), never as a public issue.

## 8. Releases and supply chain

- **Built images** (Codex in v1):
  - built for amd64 and arm64 and pushed to `ghcr.io/paddockhq/<bundle>:<agent-version>-r<N>`
  - signed keylessly with cosign using GitHub's OIDC identity
  - shipped with an SBOM attached as an attestation
  - shipped with build provenance from `actions/attest-build-provenance`

  Users verify with `cosign verify` or `gh attestation verify`.
- **Upstream images:** pinned by digest in `bundle.yaml`. Renovate bumps the digest.
- **Dockerfile-only bundles:** built in CI for testing only.
- **Renovate keeps three things current:**
  - agent versions, through `# renovate:` comments in Dockerfiles
  - base image digests
  - the OpenShell versions used by CI

  Updates merge automatically when the full matrix passes. Changes to `boundary.yaml` never merge automatically.
- **Release artifacts:**
  - Each bundle is tagged `<bundle>/v<agent-version>-r<N>`.
  - Each GitHub release carries `<bundle>-<tag>.tar.gz` (policy, providers, README) plus a SHA-256 checksum, so policy and image are versioned together.
  - The nightly run regenerates `COMPATIBILITY.md`.

## 9. Governance, security process, outreach

### 9.1 Project basics

- **Name:** PadDock.
- **Home:** GitHub organization `paddockhq` (unregistered as of 2026-10-05; to be registered by the maintainer) and repository `paddockhq/paddock`.
- **License:** Apache-2.0, matching OpenShell, with a NOTICE file for derived NVIDIA example files.
- **Process files:** DCO sign-off (matching OpenShell's contribution rules), CODEOWNERS, CONTRIBUTING.md.

### 9.2 Security process

- `SECURITY.md` routes reports through GitHub private vulnerability reporting.
- Weaknesses in OpenShell itself, or in NVIDIA's example profiles, are reported to NVIDIA under their SECURITY.md and kept private until fixed or until a disclosure window agreed with NVIDIA ends.
- Findings are published only after disclosure.

### 9.3 Outreach

1. **Week 1, after Milestone 0:** open a GitHub Discussion on NVIDIA/OpenShell. Introduce PadDock and ask what bar a collection must meet for the docs to link to it.
2. **Get vouched:** submit small upstream PRs, such as documentation fixes, so the maintainer becomes a vouched contributor. OpenShell auto-closes PRs from unvouched first-time contributors.
3. **Propose a docs page:** once three bundles have passed on two OpenShell releases, send a PR proposing a "community workloads" page in the OpenShell docs.
4. **Publish findings** in a write-up after disclosure.

### 9.4 Weekly time budget

| Share | Activity |
|---|---|
| About half | Reviewing bot PRs and CI failures |
| About a quarter | New bundles and tests |
| About a quarter | Outreach |

## 10. Milestones

Each milestone ends with its exit criterion met.

| # | Milestone | Exit criterion |
|---|---|---|
| M0 | **Feasibility check (throwaway code):** on free GitHub runners (x64 and arm), install OpenShell v0.1.2, start a gateway, create a sandbox, run `exec`, and see a `DENIED` log line | Either works on free runners, or a fallback decision is recorded |
| M1 | **Repo skeleton and CI harness:** LICENSE, NOTICE, README stub, `bundle.yaml` loader and schema check, test runner, matrix workflow, prover install, `COMPATIBILITY.md` generator | CI runs end to end against an empty bundle list; Q1 resolved |
| M2 | **OpenCode bundle:** upstream image, OpenRouter API-key profile, must-work tests | All checks pass on both OpenShell versions |
| M3 | **Shared must-block suite:** both run modes, plus the `sentry.io` and literal-credential research tests; the findings job | OpenCode passes every must-block test; findings job runs |
| M4 | **Codex bundle:** built image, API-key and subscription profiles | All checks pass; Q3 resolved; live smoke test passes |
| M5 | **Claude Code bundle:** Dockerfile-only, API-key and subscription profiles | All checks pass; Q2 resolved; live smoke test passes |
| M6 | **Releases and supply chain:** GHCR publishing, cosign, SBOM, provenance, Renovate with automerge, per-bundle tags and tarballs | A signed Codex image verifies with `cosign verify` and `gh attestation verify` |
| M7 | **Launch:** SECURITY.md, CODEOWNERS, CONTRIBUTING.md, full README, outreach steps 1–2, first disclosure filed if M3 found anything | Discussion posted; repository public |

## 11. Risks and open questions

| ID | Question or risk | How it is resolved |
|---|---|---|
| Q1 | How does CI get the combined (effective) policy for the prover: exported from the gateway, or assembled by a script from the policy plus provider endpoints and binaries? | Settled in M1 |
| Q2 | Does Claude Code accept a placeholder `CLAUDE_CODE_OAUTH_TOKEN`, with no client-side format check and no extra hosts for its account check? | M5 tests. If it fails, the token is delivered differently and the README states the trade-off. |
| Q3 | Does Codex's own sandbox work nested inside OpenShell's? | M4 tests (§6.5) |
| Q4 | Can free GitHub runners run OpenShell (kernel features, Docker driver)? | M0. Fallback: a self-hosted VM for scheduled jobs. |
| Q5 | Exact wording of Anthropic's terms on using subscription OAuth with Claude Code in a container | Checked before the Claude Code bundle's first release |
| R1 | OpenShell API and CLI churn during 0.x | Matrix testing on two versions plus nightly runs. PadDock depends only on the CLI, YAML formats and the prover. |
| R2 | Maintainer capacity: one day a week | Automation-first design; new bundles only when existing ones are green |
| R3 | Name confusion: several small GitHub projects named "Paddock" exist in the agent space (racecraft-lab/Paddock, 12 stars, an agent control plane; ViktorWelbers/paddock, 2 stars, a governance plane) | Use the distinct `paddockhq` org and the "PadDock" styling, with a clear tagline: "tested OpenShell bundles" |
| R4 | NVIDIA or the agent vendors change licensing or terms | Distribution modes (§5.3) are set per bundle and can be changed without restructuring |

## 12. References

- **OpenShell repository** (v0.1.2, commit 7caff12): https://github.com/NVIDIA/OpenShell
  - Binary matching and DNS behavior: `docs/how-it-works/policies/network-rules.mdx`
  - Baseline filesystem paths and process identity: `docs/how-it-works/policies/default-policy.mdx`
  - Provider policy layers and credential binding: `docs/how-it-works/providers/profiles.mdx`
  - Prover: `docs/how-it-works/policies/prover.mdx`
  - Denial log format: `docs/observability/accessing-logs.mdx`
  - Example profiles: `providers/claude-code.yaml`, `providers/codex.yaml`
- **Retired catalog:** https://github.com/NVIDIA/OpenShell-Community (README)
- **Claude Code:** https://github.com/anthropics/claude-code (LICENSE.md; CHANGELOG entries for `claude setup-token` and `CLAUDE_CODE_OAUTH_TOKEN`)
- **Codex CLI:** https://github.com/openai/codex (Apache-2.0; `check_for_update_on_startup`, `[analytics]`)
- **OpenCode:** https://github.com/anomalyco/opencode (MIT; `OPENCODE_DISABLE_*` flags in `packages/core/src/flag/flag.ts`)
