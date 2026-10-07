# PadDock Plan 2 (M3): Shared Must-Block Suite and Findings Job

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every bundle proves in CI that its sandbox blocks what it must, in both run modes of spec §7.4. A manually triggered findings job runs the same suite against NVIDIA's unmodified example profiles, and keeps the results private.

**Architecture:**
- **Probe:** one static curl, pinned by checksum, is uploaded into each sandbox.
- **Shared suite:** `tests/deny/run.sh` drives the probe. It judges each attempt by OpenShell's own log lines; where OpenShell writes no line, it judges by the sandbox broker's error text.
- **Run mode 1** reuses the bundle's sandbox after the must-work tests.
- **Run mode 2** creates a variant sandbox. Its provider profile lists the probe in place of the agent, so the probe gets exactly the agent's rules.
- **Findings job:** builds an image with the probe copied to each NVIDIA profile's binary path, runs the suite quietly, and encrypts all output to the maintainer's age key before upload.

**Tech Stack:**
- bash, GitHub Actions
- Python 3.12 (PyYAML 6.0.3, jsonschema 4.26.0, pytest 9.1.1)
- OpenShell v0.1.2
- stunnel/static-curl 8.22.0
- age 1.1.1 (Ubuntu 24.04 package)

**Spec:** `docs/superpowers/specs/2026-10-05-paddock-design.md`. Plan 1 (`docs/superpowers/plans/2026-10-05-paddock-plan-1-m0-m2.md`) is merged; this plan extends its code on `main`.

## Global Constraints

**Commits and naming**
- Sign off every commit with `git commit -s`. End each message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. End each pull request body with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- Check names stay `<check>:<auth mode>`, with statuses `pass|fail|error|skip` (`scripts/paddock/results.py`). Must-block checks are named `deny-<run>-<item>:<mode>`, where `<run>` is `m1`, `m2` or `fd`.
- Sandbox names are at most 19 characters: use `sandbox_name` from `scripts/ci/lib.sh`.

**Workflows**
- Workflows keep `permissions: contents: read`, `persist-credentials: false`, actions pinned by SHA, and matrix values passed through `env:`.
  - checkout v7.0.1 `3d3c42e5aac5ba805825da76410c181273ba90b1`
  - setup-python v7.0.0 `5fda3b95a4ea91299a34e894583c3862153e4b97`
  - upload-artifact v7.0.1 `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`
  - download-artifact v8.0.1 `3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c`

**Secrets**
- Secrets reach a sandbox only through `openshell provider create --credential`. `--env` carries non-secret values only.
- Never commit a string shaped like a real key (GitHub push protection rejects them); use the `{c*N}` template in `bundle.yaml`.

**Findings privacy**
- Findings are private until disclosed (spec §9.2). Job logs, step summaries and artifacts on this public repo are readable by any signed-in user.
- No step of the findings job may print an outcome. It uploads only the age-encrypted bundle.
- Never run the findings suite in any other workflow. The NVIDIA `github` profile is the only one whose results may appear in a public log (a harness control).
- Every other workflow withholds must-block results too (spec §7.6). A `deny-*` check that does not pass appears in the public cell result only as one `deny` line without details, and `run-cell.sh` encrypts that cell's logs to the maintainer's key and deletes the plaintext. Never paste withheld details into a public issue, pull request or commit message.

**Probe and must-block tests**
- Do not hard-code `/etc/openshell-tls`; it does not exist in v0.1.2. The CA bundle reaches curl through `CURL_CA_BUNDLE` / `SSL_CERT_FILE` in the sandbox environment (ADR 0002).
- Upload the probe before its first network use. OpenShell pins each binary's hash on first use, so a replaced binary is denied.
- A must-block check passes only on positive evidence:
  - a logged denial, or the broker's errno text, as listed in ADR 0002;
  - for mode 2, also an allowed control request in the same sandbox.
  - Anything inconclusive is `error`, never `pass`.

## Review Focus

1. **The probe is not treated as the agent in run mode 2,** for example after a profile change or because the variant failed to import.
   - *Expected:* every L7 result in that sandbox is withheld, and `deny-m2-control:<mode>` is `error`.
   - *Tests:* the control logic in `tests/deny/run.sh` (Task 6). CI Step 6.9 expects `deny-m2-control:api-key pass`, and the `github` control profile in Task 7's dry run expects the same.
2. **Log lines arrive late or out of order.** OpenShell batches log pushes (every 500 ms or 50 lines).
   - *Expected:* `await_event` polls until the matching line arrives (up to 10 s). It never judges a single snapshot.
   - *Tests:* `test_await_event_counts_matching_lines` and `test_await_event_fails_when_nothing_matches` (Task 5).
3. **A must-block or findings outcome leaks into a public log.** A future OpenShell release could stop blocking something, and PR, nightly and Renovate runs are public.
   - *Expected:* a `deny-*` check that does not pass appears publicly only as one `deny` line without details; that cell's logs are encrypted to the maintainer and deleted. The findings job prints nothing about outcomes and uploads only the encrypted file.
   - *Tests:* `test_must_block_details_are_withheld_when_a_deny_check_does_not_pass` (Task 4); `test_seal_logs_encrypts_to_the_maintainer_and_deletes_the_plaintext`, `test_seal_logs_without_a_key_still_deletes_the_plaintext` and `test_record_check_is_silent_in_quiet_mode` (Task 5). Task 7 Step 7 greps the findings run's public log and expects no outcome.
4. **NVIDIA profile shapes PadDock's own profiles never use:**
   - bare `**` paths;
   - the same host listed twice (REST and GraphQL);
   - wildcard hosts;
   - endpoints without `protocol` (L4 only);
   - profiles with no `binaries`.
   - *Expected:* the probe plan keeps a valid URL and probes each host once. It skips wildcard and L4 endpoints for L7 checks but lists them for the survey. A profile with no binaries is recorded as `skip` with the reason.
   - *Tests:* the `tests/unit/test_probe.py` cases (Task 3).
5. **A write check that passes for the wrong reason.** Root-owned folders such as `/usr` already refuse UID 1000.
   - *Expected:* the write check uses `/var/tmp`, which Unix permissions allow (mode 1777, `test -w` succeeds). A positive control must succeed first, or the check is `error`.
   - *Tests:* the `write-outside` block in `tests/deny/run.sh` (Task 6). CI Step 6.9 expects `deny-m1-write-outside:api-key pass`.

---

## Facts this plan relies on (ADR 0002, CI runs 37492005678 and 37494839500, OpenShell v0.1.2, x64 and arm64)

**Logged denials (Network)**

| Attempt | What the client sees | OpenShell log line (`openshell logs <sb> --source sandbox`) |
|---|---|---|
| HTTPS to an unlisted host | curl exit 7 | `NET:REFUSE [MED] DENIED <host> [reason:policy_dns_ineligible]` and `NET:OPEN [MED] DENIED <exe>(0) -> <host>:443 [reason:transparent_tcp_policy_denied]` |
| DNS lookup of an unlisted name | **succeeds** with a placeholder address `198.18.x.y` | `NET:REFUSE [MED] DENIED <host>`, the only proof |
| TCP to an IP (`telnet://1.1.1.1:443`, `8.8.8.8:53`) | curl exit 7 | `NET:OPEN [MED] DENIED <exe>(0) -> 1.1.1.1:443` |
| IPv6 literal | curl exit 7 | `NET:OPEN [MED] DENIED <exe>(0) -> 2606:4700:4700::1111:443` (no brackets) |

**Errno-only denials (no log line)**

| Attempt | What the client sees | Log line |
|---|---|---|
| UDP to an IP (`tftp://1.1.1.1:9999/x`, `tftp://8.8.8.8:53/x`) | curl exit 55, `Destination address required` | none |
| `nslookup x 8.8.8.8` | `Permission denied` | none |
| ICMP | `Protocol not supported` | none |

**Filesystem**

| Attempt | What the client sees | Log line |
|---|---|---|
| Write to `/var/tmp` (mode 1777, not in `read_write`) | `Permission denied`, although `test -w` succeeds | none |

**L7 and credentials, mode 2 (probe listed)**

| Attempt | What the client sees | OpenShell log line |
|---|---|---|
| POST `/api/v1/chat/completions` (the allowed rule) | the upstream answers | `HTTP:POST [INFO] ALLOWED POST http://openrouter.ai:443/api/v1/chat/completions [... engine:l7]` |
| DELETE on that path, or GET of an unlisted path | HTTP 403, JSON body with `"error":"policy_denied"` | `HTTP:<M> [MED] DENIED <M> http://openrouter.ai:443<path> [... engine:l7]` |
| Literal `Authorization: Bearer <non-placeholder>` | forwarded unchanged; OpenRouter answers `User not found.` | normal ALLOWED line |

**Other facts**

- **CA bundle:** set by OpenShell in `CURL_CA_BUNDLE` and `SSL_CERT_FILE` (`/run/openshell-supervisor-ca/material/ca-bundle.crt`).
- **Upload:** `openshell sandbox upload <sb> <file> /sandbox/.paddock/` keeps the exec bit; owner is 1000.
- **Binary matching:** a variant profile with `binaries: [/sandbox/.paddock/curl]` makes the probe match whether it runs directly or under `sh -c`.
- **Findings image:** copying the probe to a listed path in an image built `FROM` the OpenCode image works with NVIDIA's unmodified profiles. The `github` profile shows GET `/zen` ALLOWED and POST `/gists` DENIED at L7.
- **NVIDIA profiles:**
  - `pypi` and `cursor` create providers with no credentials. `aws-s3` needs `--runtime-credentials`. All 8 sampled profiles lint with exit 0.
  - v0.1.2 has no built-in profiles, so each is imported from `providers/<id>.yaml` at the release tag.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `docs/decisions/0002-must-block-observations.md` | What the M3 spike observed and how checks are judged | 1 |
| `docs/superpowers/specs/2026-10-05-paddock-design.md` | §7.4 and §7.5 refined to match the observations | 1 |
| `scripts/paddock/logs.py` | Events gain `activity` and `path`; `events` gains `--kind --activity --port --binary --path` | 2 |
| `scripts/paddock/probe.py` (new) | Probe plan from a provider profile: control, L7 denials, literal header, survey endpoints, variant profile, probe binary path | 3 |
| `scripts/paddock/__main__.py` | Register `probe` | 3 |
| `scripts/paddock/bundle.py` | CRLF check runs even when the schema fails | 4 |
| `scripts/paddock/results.py` | Public cell results withhold the details of must-block checks that do not pass | 4 |
| `scripts/ci/openshell-versions.json`, `bundles/opencode/bundle.yaml`, `bundles/opencode/README.md` | List v0.0.116; OpenCode declares `openshell_min_version: v0.1.0` | 4 |
| `.github/workflows/ci.yml` | Cell upload fails when results are missing | 4 |
| `.github/findings-recipients.txt` (new) | The maintainer's age public key, for withheld CI logs and the findings job | 1 |
| `scripts/ci/lib.sh` | Quiet mode, stricter `gateway_connected` and `sandbox_ready`, probe upload, event polling, `seal_logs` | 5 |
| `scripts/ci/install-probe.sh` (new) | Pinned static curl download | 5 |
| `tests/deny/run.sh` (new) | The shared must-block suite | 6 |
| `scripts/ci/run-cell.sh` | Runs mode 1 and mode 2; enforces the must-work check contract; resets provider info; seals the logs when a must-block check does not pass | 6 |
| `bundles/opencode/tests/allow.sh` | Waits for log lines; flags allowed hosts other than openrouter.ai | 6 |
| `README.md` | Explains the must-block suite | 6 |
| `tests/findings/profiles.tsv`, `tests/findings/policy.yaml`, `scripts/ci/findings.sh`, `.github/workflows/findings.yml` (new) | Findings job | 7 |

All tests live in `tests/unit/`:
- `test_logs.py`, `test_probe.py`, `test_bundle.py` and `test_matrix.py` run everywhere.
- `test_ci_lib.py` runs on Linux only; it is skipped on Windows.

Run the Python tests locally with `PATH="$PWD/.venv/Scripts:$PATH" python -m pytest tests/unit -q`.

---

### Task 1: Record the spike, refine the spec, add the maintainer's key, and remove the throwaway branches

**Files:**
- Create: `docs/decisions/0002-must-block-observations.md`, `.github/findings-recipients.txt`
- Modify: `docs/superpowers/specs/2026-10-05-paddock-design.md` (§7.4 step 4, §7.5, §7.6)

**Interfaces:**
- Produces:
  - ADR 0002, which Tasks 5–7 cite for every judging rule;
  - `.github/findings-recipients.txt` (one `age1…` line), used by `seal_logs` (Task 5) and the findings job (Task 7).

- [ ] **Step 0 (maintainer): Create the age key on your machine.** In PowerShell:

```powershell
winget install --id FiloSottile.age
age-keygen -o "$HOME\paddock-findings.key"
```

`age-keygen` prints `Public key: age1...`. Keep `paddock-findings.key` private and backed up: it is the only way to read withheld CI logs and findings. Send only the `age1...` line.

- [ ] **Step 1: Create the branch.**

```bash
git switch main
git pull --ff-only
git switch -c m3-deny
```

- [ ] **Step 2: Create `docs/decisions/0002-must-block-observations.md`.**

````markdown
# 0002: How must-block checks are judged

- Status: accepted
- Date: 2026-10-06
- Runs: https://github.com/paddockhq/paddock/actions/runs/37492005678 (spike),
  https://github.com/paddockhq/paddock/actions/runs/37494839500 (plan check)

## Context

Spec §7.4 says a must-block attempt passes when it fails *and* OpenShell logs a
matching `NET:OPEN ... DENIED` or `HTTP:<METHOD> ... DENIED` line. A throwaway
spike ran every catalog item in OpenShell v0.1.2 sandboxes built from the
OpenCode bundle, on `ubuntu-24.04` and `ubuntu-24.04-arm`, to see what the client
and the log actually show. Both architectures behaved identically.

## Observations

The probe is a static curl (stunnel/static-curl 8.22.0) uploaded to
`/sandbox/.paddock/curl`. `<exe>` below is the real path of the calling binary.

| Attempt | Client sees | OpenShell log (`openshell logs <sb> --source sandbox`) |
|---|---|---|
| HTTPS to an unlisted host | curl exit 7 | `NET:REFUSE [MED] DENIED <host> [reason:policy_dns_ineligible]`, then `NET:OPEN [MED] DENIED <exe>(0) -> <host>:443 [reason:transparent_tcp_policy_denied]` |
| DNS lookup of an unlisted name | succeeds, with a placeholder address `198.18.x.y` | `NET:REFUSE [MED] DENIED <host>` |
| TCP to an IP address (`1.1.1.1:443`, `8.8.8.8:53`) | curl exit 7 | `NET:OPEN [MED] DENIED <exe>(0) -> 1.1.1.1:443` |
| IPv6 address | curl exit 7 | `NET:OPEN [MED] DENIED <exe>(0) -> 2606:4700:4700::1111:443` (no brackets) |
| UDP to an IP address (curl `tftp://`) | curl exit 55, `Destination address required` | none |
| DNS query sent to 8.8.8.8 (busybox `nslookup`) | `Permission denied` | none |
| ICMP (`ping`) | `Protocol not supported` | none |
| Write to `/var/tmp` (mode 1777, not in `read_write`) | `Permission denied`, while `test -w /var/tmp` succeeds | none |
| `sentry.io` | curl exit 7 | as for an unlisted host |

With a variant provider profile that lists `/sandbox/.paddock/curl` in place of
`/usr/local/bin/opencode` (run mode 2):

| Attempt | Client sees | OpenShell log |
|---|---|---|
| `POST /api/v1/chat/completions` (the allowed rule) | the upstream answer (401 with the dummy key) | `HTTP:POST [INFO] ALLOWED POST http://openrouter.ai:443/api/v1/chat/completions [policy:_provider_<name> engine:l7]` |
| `DELETE` on that path, or `GET` of an unlisted path | HTTP 403 with JSON `"error":"policy_denied"` | `HTTP:<M> [MED] DENIED <M> http://openrouter.ai:443<path> [... engine:l7]` |
| Literal `Authorization: Bearer <non-placeholder key>` | forwarded unchanged; OpenRouter answers `User not found.` | the normal ALLOWED line |
| Credential placeholder in the request body | forwarded unrewritten | the normal ALLOWED line |

The probe matched the variant rule both when run directly and under `sh -c`.

**Other facts**
- **CA bundle:** the sandbox gets it through `CURL_CA_BUNDLE` and `SSL_CERT_FILE` (`/run/openshell-supervisor-ca/material/ca-bundle.crt`). `/etc/openshell-tls` does not exist.
- **Upload:** `openshell sandbox upload` keeps the exec bit, and the file is owned by UID 1000.
- **Process tree:** an exec'd shell is busybox, whose parent is `/.openshell/runtime/openshell-sandbox` (PID 1).
- **Log length:** `openshell logs` returns only 200 lines by default.

## Decision

- **Logged denials** pass only when the attempt fails and the matching line
  above is logged. This covers unlisted hosts, DNS of unlisted names, TCP, IPv6
  and L7 rules.
  - A DNS lookup is judged by its `NET:REFUSE` line, because the lookup itself
    succeeds.
  - A failure without the line is `error`, since the network rather than
    OpenShell may have stopped it.
- **Errno-only denials** have no log line. They pass on the broker's error text:
  - UDP and the outside-resolver query: `Destination address required` or
    `Permission denied`;
  - the write test: `Permission denied` on `/var/tmp`, after a control write to
    `/tmp` succeeds and `test -w /var/tmp` confirms Unix permissions allow it.
  - Root-owned folders such as `/usr` would refuse UID 1000 even without
    Landlock, so they prove nothing.
- **Run mode 2** lists the probe, not a shell, in the variant profile.
  - In the OpenCode image `/bin/sh` is busybox, so listing the shell would grant
    every busybox command and the exec launcher.
  - A control request on the allowed rule must log ALLOWED, or the mode-2 L7
    results are `error`.
- **The literal-credential test** records what the proxy does (`skip` with a
  detail). It never decides a cell.
- **Log polling:** read the log with `-n 20000`, and poll for up to 10 s, because
  OpenShell pushes lines in batches.
- **Publishing:** CI results on this public repository are public, and a
  must-block check that does not pass may describe an unfixed OpenShell weakness
  (spec 7.6, 9.2). The public cell result folds such checks into one line,
  `deny`, without details. `run-cell.sh` encrypts that cell's logs to the
  maintainer's age key (`.github/findings-recipients.txt`) and deletes the
  plaintext.
````

- [ ] **Step 3: Refine spec §7.4 step 4.** Replace the three bullets that start `**How a pass is judged:**`, `**Run mode 1:**` and `**Run mode 2 (worst-case child):**` with:

```markdown
   - **How a pass is judged:** every attempt must fail, and there must be positive evidence that OpenShell blocked it (ADR 0002):
     - *Logged denials:* a matching `NET:OPEN ... DENIED`, `NET:REFUSE ... DENIED` or `HTTP:<METHOD> ... DENIED` line, read with `openshell logs <sandbox> --source sandbox`. This covers unlisted hosts, DNS of unlisted names, TCP and IPv6 to IP addresses, and L7 method and path rules. A DNS lookup of an unlisted name still returns a placeholder address, so the `NET:REFUSE` line is the proof.
     - *Errno-only denials:* OpenShell v0.1.2 writes no log line for UDP, for queries sent straight to an outside resolver, or for Landlock. These pass on the sandbox broker's error (`Destination address required` or `Permission denied`). A write test targets a folder that Unix permissions allow but the policy does not list (`/var/tmp`), after a positive control.
     - An attempt that fails without that evidence is an error, not a pass.
   - **Run mode 1:** in the bundle's own sandbox, from a process outside the agent's process tree: a probe uploaded to `/sandbox/.paddock/curl`, run with `openshell sandbox exec -n <sandbox> --no-login-shell -- <test>`.
   - **Run mode 2 (worst-case child):** in a variant sandbox whose provider profile lists the probe in place of the agent binary. Child processes inherit the agent's rules (R2), so the probe stands for every tool call a prompt-injected agent could make. An allowed control request must be logged as ALLOWED in the same sandbox, or the mode-2 results are an error. (Listing the probe rather than a shell keeps unrelated tools out of the variant: in images where `/bin/sh` is busybox, listing the shell would grant every busybox command.)
```

- [ ] **Step 4: Refine spec §7.5.** Replace its one paragraph with:

```markdown
A manually triggered job, on the main branch only, runs the must-block suite against NVIDIA's unmodified example provider profiles. It also surveys which HTTP methods each endpoint lets a child process use. A findings image starts from the OpenCode bundle's image and has the probe copied to a listed binary path of each profile, so each profile's own rules apply to it. Its output feeds the disclosure process (§9.2) and is never published directly. Job logs and artifacts of a public repository are visible to any signed-in user, so the job prints no outcome and uploads only an archive encrypted with `age` to the maintainer's public key (`.github/findings-recipients.txt`).
```

- [ ] **Step 5: Refine spec §7.6.** Replace the bullet that starts `- **A must-block test passes, meaning access leaked:**` with:

```markdown
- **A must-block test passes, meaning access leaked:** this is a security issue. It is handled privately (§9.2), never as a public issue. CI results on this public repository are public, so CI withholds the details of any must-block check that does not pass: the public cell result shows one `deny` line, and the cell's logs are encrypted with `age` to the maintainer's key and the plaintext deleted.
```

- [ ] **Step 6: Add the maintainer's public key.**

```bash
printf '%s\n' 'age1...the maintainer public key from Step 0...' > .github/findings-recipients.txt
grep -qE '^age1[a-z0-9]{58}$' .github/findings-recipients.txt && echo ok
```

Expected: `ok`.

- [ ] **Step 7: Remove the throwaway branches.** `m3-spike` and `m3-plancheck` held the code that produced ADR 0002 and this plan. Nothing else uses them.

```bash
git push origin --delete m3-spike m3-plancheck
git branch -D m3-spike 2>/dev/null || true
```

Expected: `- [deleted] m3-spike` and `- [deleted] m3-plancheck`.

- [ ] **Step 8: Commit.**

```bash
git add docs/decisions/0002-must-block-observations.md docs/superpowers/specs/2026-10-05-paddock-design.md \
  .github/findings-recipients.txt
git commit -s -m "Record the M3 spike, refine how must-block checks are judged, add the maintainer's age key"
```

---

### Task 2: Log events record their activity and path

**Files:**
- Modify: `scripts/paddock/logs.py` (whole file below)
- Test: `tests/unit/test_logs.py` (append)

**Interfaces:**
- Consumes: `paddock.logs.parse_events`, `select`, the `events` command (Plan 1 Task 6, hardened in PR #4).
- Produces:
  - `Event(kind, activity, action, host, port, binary, method, path, line)`. `activity` is the NET activity (`OPEN`, `REFUSE`, …) or the HTTP method. `path` is the HTTP request path, or `None`.
  - `select(events, action=None, host=None, kind=None, activity=None, port=None, binary=None, path=None)`.
  - CLI: `python -m paddock events --log F [--action A] [--host H] [--kind NET|HTTP] [--activity X] [--port N] [--binary P] [--path /p] [--format lines|count|hosts]`.

- [ ] **Step 1: Write the failing tests.** Append to `tests/unit/test_logs.py`:

```python
# Lines captured by the M3 spike (docs/decisions/0002-must-block-observations.md).
PROBE = "/sandbox/.paddock/curl"
SPIKE_LINES = [
    "[1.0] [sandbox] [OCSF ] [ocsf] NET:REFUSE [MED] DENIED pd-1-a.example.com [reason:policy_dns_ineligible]",
    f"[1.1] [sandbox] [OCSF ] [ocsf] NET:OPEN [MED] DENIED {PROBE}(0) -> pd-1-a.example.com:443 "
    "[reason:transparent_tcp_policy_denied]",
    f"[1.2] [sandbox] [OCSF ] [ocsf] NET:OPEN [MED] DENIED {PROBE}(0) -> 2606:4700:4700::1111:443 "
    "[reason:transparent_tcp_policy_denied]",
    f"[1.3] [sandbox] [OCSF ] [ocsf] NET:OPEN [INFO] ALLOWED {PROBE}(0) -> openrouter.ai:443 "
    "[policy:_provider_x engine:opa]",
    "[1.4] [sandbox] [OCSF ] [ocsf] HTTP:POST [INFO] ALLOWED POST http://openrouter.ai:443/api/v1/chat/completions "
    "[policy:_provider_x engine:l7]",
    "[1.5] [sandbox] [OCSF ] [ocsf] HTTP:DELETE [MED] DENIED DELETE http://openrouter.ai:443/api/v1/chat/completions "
    "[policy:_provider_x engine:l7] [reason:L7_REQUEST deny DELETE openrouter.ai:443/api/v1/chat/completions]",
    "[1.6] [sandbox] [OCSF ] [ocsf] NET:OPEN [INFO] 127.0.0.1:17670",
    "[1.7] [sandbox] [OCSF ] [ocsf] SSH:OPEN [INFO] ALLOWED",
]


def test_events_record_their_activity():
    events = parse_events("\n".join(SPIKE_LINES))
    assert [(e.kind, e.activity, e.action, e.host, e.port) for e in events] == [
        ("NET", "REFUSE", "DENIED", "pd-1-a.example.com", None),
        ("NET", "OPEN", "DENIED", "pd-1-a.example.com", 443),
        ("NET", "OPEN", "DENIED", "2606:4700:4700::1111", 443),
        ("NET", "OPEN", "ALLOWED", "openrouter.ai", 443),
        ("HTTP", "POST", "ALLOWED", "openrouter.ai", 443),
        ("HTTP", "DELETE", "DENIED", "openrouter.ai", 443),
    ]


def test_select_filters_by_kind_activity_port_and_binary():
    events = parse_events("\n".join(SPIKE_LINES))
    assert len(select(events, action="DENIED", kind="NET", activity="OPEN", port=443, binary=PROBE)) == 2
    assert len(select(events, kind="NET", activity="REFUSE", host="pd-1-a.example.com")) == 1
    assert len(select(events, kind="HTTP", activity="DELETE", action="DENIED", host="openrouter.ai")) == 1
    assert select(events, binary="/usr/bin/curl") == []


def test_events_command_accepts_the_new_filters(tmp_path, capsys):
    log = tmp_path / "sandbox.log"
    log.write_text("\n".join(SPIKE_LINES) + "\n", encoding="utf-8")
    args = ["events", "--log", str(log), "--action", "DENIED", "--kind", "NET", "--activity", "OPEN",
            "--port", "443", "--binary", PROBE, "--format", "count"]
    assert main(args) == 0
    assert capsys.readouterr().out == "2\n"


def test_unparsed_denials_keep_an_unknown_activity():
    events = parse_events("HTTP:GET [MED] DENIED GET http://[::1:443/x [policy:-]")
    assert [(e.kind, e.activity, e.host) for e in events] == [("HTTP", "GET", "<unparsed>")]


def test_http_events_carry_their_path():
    events = parse_events("\n".join(SPIKE_LINES))
    assert [e.path for e in events if e.kind == "HTTP"] == ["/api/v1/chat/completions"] * 2
    assert len(select(events, kind="HTTP", path="/api/v1/chat/completions", action="DENIED")) == 1
    assert {e.path for e in events if e.kind == "NET"} == {None}
```

- [ ] **Step 2: Run them to verify they fail.**

Run: `python -m pytest tests/unit/test_logs.py -q`
Expected: `5 failed, 10 passed`. The failures are `AttributeError: 'Event' object has no attribute 'activity'` (or `'path'`), `select() got an unexpected keyword argument 'kind'`, and argparse `unrecognized arguments: --kind`.

- [ ] **Step 3: Replace `scripts/paddock/logs.py` with:**

```python
"""Read OpenShell policy events (OCSF shorthand) from `openshell logs` output."""

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

_NET = re.compile(
    r"\bNET:(?P<op>[A-Z]+) \[[A-Z]+\] (?P<action>ALLOWED|DENIED|BLOCKED) "
    r"(?P<binary>\S+?)\((?P<pid>\d+)\) -> (?P<host>\[[^\]]+\]|[^\s/]+?):(?P<port>\d+)(?=[\s/]|$)"
)
# A DNS refusal names only the host: NET:REFUSE [MED] DENIED example.com [reason:...]
_NET_HOST = re.compile(
    r"\bNET:(?P<op>[A-Z]+) \[[A-Z]+\] (?P<action>DENIED|BLOCKED) "
    r"(?P<host>[A-Za-z0-9.-]+|\[[0-9A-Fa-f:.]+\])(?=\s\[|$)"
)
_HTTP = re.compile(
    r"\bHTTP:(?P<method>[A-Z]+) \[[A-Z]+\] (?P<action>ALLOWED|DENIED|BLOCKED) (?P=method) (?P<url>\S+)"
)
# Any denial line the patterns above cannot read. It is kept, so callers fail closed.
_DENIAL = re.compile(r"\b(?P<kind>NET|HTTP):(?P<op>[A-Z]+) \[[A-Z]+\] (?P<action>DENIED|BLOCKED)\b")
UNPARSED = "<unparsed>"


@dataclass(frozen=True)
class Event:
    kind: str
    activity: str
    action: str
    host: str
    port: int | None
    binary: str | None
    method: str | None
    path: str | None
    line: str


def _http_event(match, line):
    try:
        url = urlsplit(match["url"])
        port = url.port
    except ValueError:
        return None
    if not url.hostname:
        return None
    return Event("HTTP", match["method"], match["action"], url.hostname, port, None, match["method"], url.path, line)


def parse_events(text):
    events = []
    for line in text.splitlines():
        event = None
        if match := _NET.search(line):
            event = Event(
                "NET", match["op"], match["action"], match["host"].strip("[]"), int(match["port"]),
                match["binary"], None, None, line,
            )
        elif match := _NET_HOST.search(line):
            event = Event("NET", match["op"], match["action"], match["host"].strip("[]"), None, None, None, None, line)
        elif match := _HTTP.search(line):
            event = _http_event(match, line)
        if event is None and (match := _DENIAL.search(line)):
            event = Event(match["kind"], match["op"], match["action"], UNPARSED, None, None, None, None, line)
        if event is not None:
            events.append(event)
    return events


def select(events, action=None, host=None, kind=None, activity=None, port=None, binary=None, path=None):
    wanted = {"action": action, "host": host, "kind": kind, "activity": activity, "port": port, "binary": binary,
              "path": path}
    return [e for e in events if all(value is None or getattr(e, key) == value for key, value in wanted.items())]


def _cmd_events(args):
    events = select(
        parse_events(Path(args.log).read_text(encoding="utf-8", errors="replace")),
        action=args.action, host=args.host, kind=args.kind, activity=args.activity,
        port=args.port, binary=args.binary, path=args.path,
    )
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
    cmd.add_argument("--kind", choices=["NET", "HTTP"])
    cmd.add_argument("--activity", help="NET activity (OPEN, REFUSE, ...) or HTTP method")
    cmd.add_argument("--port", type=int)
    cmd.add_argument("--binary", help="real path of the calling executable")
    cmd.add_argument("--path", help="HTTP request path")
    cmd.add_argument("--format", choices=["lines", "count", "hosts"], default="lines")
    cmd.set_defaults(handler=_cmd_events)
```

- [ ] **Step 4: Run the tests to verify they pass.**

Run: `python -m pytest tests/unit -q`
Expected: every test passes. `test_logs.py` contributes 15.

- [ ] **Step 5: Commit.**

```bash
git add scripts/paddock/logs.py tests/unit/test_logs.py
git commit -s -m "logs: record each event's activity and path, and filter on them"
```

---

### Task 3: Probe planning from a provider profile

**Files:**
- Create: `scripts/paddock/probe.py`
- Modify: `scripts/paddock/__main__.py`
- Test: `tests/unit/test_probe.py`

**Interfaces:**
- Consumes: provider profile YAML (OpenShell profile schema), and `paddock.__main__.MODULES`.
- Produces:
  - `PROBE_PATH = "/sandbox/.paddock/curl"`.
  - `rule_allows(endpoint, method, path) -> bool`: honours `rules[].allow.{method,path}` with `*` and `**` globs, else the `access` preset.
  - `probe_requests(profile, nonce) -> list[(kind, method, url)]`. `kind` is `control`, `l7-method` or `l7-path`.
  - `literal_header(profile) -> (header, prefix) | None`.
  - `variant_profile(profile, probe_path) -> dict`, with id `<id>-probe` and `binaries: [probe_path]`.
  - `probe_binary(profile) -> str | None`.
  - CLI commands:
    - `variant-profile <file> --out F [--binary P]` prints `VARIANT_PROFILE_ID=<id>`.
    - `probe-plan <file> --nonce N` prints tab-separated lines: `control|l7-method|l7-path <TAB> METHOD <TAB> URL`, then `endpoint <TAB> host <TAB> port <TAB> protocol|-` once per host and port, then `literal <TAB> Header <TAB> prefix`.
    - `probe-binary <file>` prints one path or nothing.

- [ ] **Step 1: Write the failing tests.** Create `tests/unit/test_probe.py`:

```python
import yaml

from paddock.__main__ import main
from paddock.probe import PROBE_PATH, literal_header, probe_requests, rule_allows, variant_profile

OPENROUTER = {
    "id": "paddock-opencode-openrouter",
    "credentials": [{"name": "api_key", "env_vars": ["OPENROUTER_API_KEY"], "auth_style": "bearer",
                     "header_name": "authorization"}],
    "endpoints": [{"host": "openrouter.ai", "port": 443, "protocol": "rest", "enforcement": "enforce",
                   "rules": [{"allow": {"method": "POST", "path": "/api/v1/chat/completions"}}]}],
    "binaries": ["/usr/local/bin/opencode"],
}


def test_rules_and_access_presets():
    endpoint = OPENROUTER["endpoints"][0]
    assert rule_allows(endpoint, "POST", "/api/v1/chat/completions")
    assert not rule_allows(endpoint, "GET", "/api/v1/chat/completions")
    assert not rule_allows(endpoint, "POST", "/api/v1/models")
    read_write = {"host": "x", "protocol": "rest", "access": "read-write"}
    assert rule_allows(read_write, "PUT", "/anything/at/all")
    assert not rule_allows(read_write, "DELETE", "/a")
    globbed = {"host": "x", "protocol": "rest", "rules": [{"allow": {"method": "GET", "path": "/repos/*/pulls/**"}}]}
    assert rule_allows(globbed, "GET", "/repos/o/pulls/1/files")
    assert not rule_allows(globbed, "GET", "/repos/o/r/pulls")


def test_probe_requests_for_the_opencode_profile():
    assert probe_requests(OPENROUTER, "n1") == [
        ("control", "POST", "https://openrouter.ai/api/v1/chat/completions"),
        ("l7-method", "DELETE", "https://openrouter.ai/api/v1/chat/completions"),
        ("l7-path", "GET", "https://openrouter.ai/pd-n1"),
    ]


def test_probe_requests_skip_methods_and_paths_the_profile_allows():
    profile = {"endpoints": [{"host": "api.example.com", "port": 8443, "protocol": "rest", "access": "full"}]}
    # full access allows every method and path, so there is nothing to deny.
    assert probe_requests(profile, "n1") == [("control", "GET", "https://api.example.com:8443/")]


def test_probe_requests_ignore_endpoints_without_l7_inspection():
    profile = {"endpoints": [{"host": "pypi.org", "port": 443}]}
    assert probe_requests(profile, "n1") == []


def test_variant_profile_lists_only_the_probe():
    variant = variant_profile(OPENROUTER, PROBE_PATH)
    assert variant["id"] == "paddock-opencode-openrouter-probe"
    assert variant["binaries"] == [PROBE_PATH]
    assert variant["endpoints"] == OPENROUTER["endpoints"]
    assert OPENROUTER["binaries"] == ["/usr/local/bin/opencode"]


def test_literal_header_follows_the_auth_style():
    assert literal_header(OPENROUTER) == ("Authorization", "Bearer ")
    header = {"credentials": [{"auth_style": "header", "header_name": "x-api-key"}]}
    assert literal_header(header) == ("x-api-key", "")
    assert literal_header({"credentials": [{"env_vars": ["CODEX_AUTH_ACCESS_TOKEN"]}]}) is None


def test_variant_command_writes_the_profile_and_prints_its_id(tmp_path, capsys):
    source = tmp_path / "p.yaml"
    source.write_text(yaml.safe_dump(OPENROUTER), encoding="utf-8")
    out = tmp_path / "variant.yaml"
    assert main(["variant-profile", str(source), "--out", str(out)]) == 0
    assert capsys.readouterr().out == "VARIANT_PROFILE_ID=paddock-opencode-openrouter-probe\n"
    assert yaml.safe_load(out.read_text(encoding="utf-8"))["binaries"] == [PROBE_PATH]


def test_probe_plan_command_prints_tab_separated_lines(tmp_path, capsys):
    source = tmp_path / "p.yaml"
    source.write_text(yaml.safe_dump(OPENROUTER), encoding="utf-8")
    assert main(["probe-plan", str(source), "--nonce", "n1"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "control\tPOST\thttps://openrouter.ai/api/v1/chat/completions"
    assert lines[-1] == "literal\tAuthorization\tBearer "


def test_probe_plan_lists_every_endpoint_for_the_findings_survey(tmp_path, capsys):
    profile = {"endpoints": [{"host": "pypi.org", "port": 443}, {"host": "*.s3.amazonaws.com", "port": 443}]}
    source = tmp_path / "p.yaml"
    source.write_text(yaml.safe_dump(profile), encoding="utf-8")
    assert main(["probe-plan", str(source), "--nonce", "n1"]) == 0
    # Wildcard hosts cannot be probed by name; they are listed so the survey says so.
    assert capsys.readouterr().out == "endpoint\tpypi.org\t443\t-\nendpoint\t*.s3.amazonaws.com\t443\t-\n"


def test_probe_binary_names_a_concrete_path(tmp_path, capsys):
    source = tmp_path / "p.yaml"
    source.write_text(yaml.safe_dump({"binaries": ["/usr/lib/node_modules/@openai/**", "/usr/bin/codex"]}),
                      encoding="utf-8")
    assert main(["probe-binary", str(source)]) == 0
    assert capsys.readouterr().out == "/usr/lib/node_modules/@openai/paddock-probe\n"
    source.write_text(yaml.safe_dump({"binaries": []}), encoding="utf-8")
    assert main(["probe-binary", str(source)]) == 0
    assert capsys.readouterr().out == ""


def test_control_path_from_a_bare_glob_keeps_its_leading_slash():
    # NVIDIA's github.yaml allows GET ** on github.com.
    profile = {"endpoints": [{"host": "github.com", "port": 443, "protocol": "rest",
                              "rules": [{"allow": {"method": "GET", "path": "**"}},
                                        {"allow": {"method": "POST", "path": "/**/git-upload-pack"}}]}]}
    plan = probe_requests(profile, "n1")
    assert plan[0] == ("control", "GET", "https://github.com/pd")
    assert ("l7-path", "POST", "https://github.com/pd-n1") in plan


def test_probe_plan_lists_each_host_and_port_once(tmp_path, capsys):
    # github.yaml lists api.github.com twice (REST and GraphQL); the survey probes it once.
    profile = {"endpoints": [{"host": "api.github.com", "port": 443, "protocol": "rest", "access": "read-only"},
                             {"host": "api.github.com", "port": 443, "protocol": "graphql", "path": "/graphql"}]}
    source = tmp_path / "p.yaml"
    source.write_text(yaml.safe_dump(profile), encoding="utf-8")
    assert main(["probe-plan", str(source), "--nonce", "n1"]) == 0
    assert [line for line in capsys.readouterr().out.splitlines() if line.startswith("endpoint")] == [
        "endpoint\tapi.github.com\t443\trest"]
```

- [ ] **Step 2: Run them to verify they fail.**

Run: `python -m pytest tests/unit/test_probe.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'paddock.probe'`.

- [ ] **Step 3: Create `scripts/paddock/probe.py`:**

```python
"""Plan must-block probe requests from a provider profile (run mode 2 and the findings job)."""

import copy
import re
from pathlib import Path

import yaml

# Where CI uploads the static curl probe inside a sandbox.
PROBE_PATH = "/sandbox/.paddock/curl"
# OpenShell access presets (docs/how-it-works/policies/schema.mdx).
ACCESS_METHODS = {
    "read-only": {"GET", "HEAD", "OPTIONS"},
    "read-write": {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH"},
    "full": None,  # every method
}
METHOD_CANDIDATES = ("DELETE", "PUT", "PATCH", "POST", "GET")
PATH_CANDIDATES = ("GET", "POST")
GLOB = re.compile(r"\*\*?")


def _glob_regex(pattern):
    parts = re.split(r"(\*\*|\*)", pattern)
    body = "".join(".*" if p == "**" else "[^/]*" if p == "*" else re.escape(p) for p in parts)
    return re.compile(f"^{body}$")


def rule_allows(endpoint, method, path):
    """Whether an endpoint's L7 allow rules (or access preset) permit a request."""
    rules = endpoint.get("rules")
    if rules:
        for rule in rules:
            allow = rule.get("allow", {})
            if allow.get("method", "*") in ("*", method) and _glob_regex(allow.get("path", "**")).match(path):
                return True
        return False
    methods = ACCESS_METHODS.get(endpoint.get("access", "read-only"), set())
    return methods is None or method in methods


def _url(endpoint, path):
    port = endpoint.get("port", 443)
    authority = endpoint["host"] if port == 443 else f"{endpoint['host']}:{port}"
    return f"https://{authority}{path}"


def _control(endpoint):
    for rule in endpoint.get("rules") or []:
        allow = rule.get("allow", {})
        if allow.get("method", "*") != "*":
            path = GLOB.sub("pd", allow.get("path", "/"))
            return allow["method"], path if path.startswith("/") else f"/{path}"
    return "GET", "/"


def probe_requests(profile, nonce):
    """(kind, method, url) for each L7-inspected endpoint: one allowed control request,
    then one disallowed method on the allowed path and one disallowed path, when the
    profile's own rules leave such requests disallowed."""
    plan = []
    for endpoint in profile.get("endpoints") or []:
        if endpoint.get("protocol") != "rest" or "*" in endpoint["host"]:
            continue
        method, path = _control(endpoint)
        plan.append(("control", method, _url(endpoint, path)))
        for candidate in METHOD_CANDIDATES:
            if candidate != method and not rule_allows(endpoint, candidate, path):
                plan.append(("l7-method", candidate, _url(endpoint, path)))
                break
        for candidate in PATH_CANDIDATES:
            if not rule_allows(endpoint, candidate, f"/pd-{nonce}"):
                plan.append(("l7-path", candidate, _url(endpoint, f"/pd-{nonce}")))
                break
    return plan


def literal_header(profile):
    """(header name, value prefix) a client uses to send this profile's key, or None."""
    for credential in profile.get("credentials") or []:
        if credential.get("auth_style") == "bearer":
            return ("Authorization", "Bearer ")
        if credential.get("auth_style") == "header" and credential.get("header_name"):
            return (credential["header_name"], "")
    return None


def variant_profile(profile, probe_path):
    """Run mode 2: the same profile with the probe listed in place of the agent."""
    variant = copy.deepcopy(profile)
    variant["id"] = f"{profile['id']}-probe"
    variant["binaries"] = [probe_path]
    return variant


def probe_binary(profile):
    """A concrete path that matches the profile's first listed binary (globs filled in)."""
    for binary in profile.get("binaries") or []:
        return GLOB.sub("paddock-probe", binary)
    return None


def _load(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _cmd_variant_profile(args):
    variant = variant_profile(_load(args.provider_file), args.binary)
    Path(args.out).write_text(yaml.safe_dump(variant, sort_keys=False), encoding="utf-8")
    print(f"VARIANT_PROFILE_ID={variant['id']}")
    return 0


def _cmd_probe_plan(args):
    profile = _load(args.provider_file)
    for kind, method, url in probe_requests(profile, args.nonce):
        print(f"{kind}\t{method}\t{url}")
    seen = set()
    for endpoint in profile.get("endpoints") or []:
        key = (endpoint["host"], endpoint.get("port", 443))
        if key not in seen:
            seen.add(key)
            print(f"endpoint\t{key[0]}\t{key[1]}\t{endpoint.get('protocol', '-')}")
    header = literal_header(profile)
    if header:
        print(f"literal\t{header[0]}\t{header[1]}")
    return 0


def _cmd_probe_binary(args):
    binary = probe_binary(_load(args.provider_file))
    if binary:
        print(binary)
    return 0


def add_commands(sub):
    cmd = sub.add_parser("variant-profile", help="write the run-mode-2 copy of a provider profile")
    cmd.add_argument("provider_file")
    cmd.add_argument("--out", required=True)
    cmd.add_argument("--binary", default=PROBE_PATH)
    cmd.set_defaults(handler=_cmd_variant_profile)

    cmd = sub.add_parser("probe-plan", help="print the probe requests and endpoints for a provider profile")
    cmd.add_argument("provider_file")
    cmd.add_argument("--nonce", required=True)
    cmd.set_defaults(handler=_cmd_probe_plan)

    cmd = sub.add_parser("probe-binary", help="print a concrete path matching a profile's first binary")
    cmd.add_argument("provider_file")
    cmd.set_defaults(handler=_cmd_probe_binary)
```

- [ ] **Step 4: Register the module.** In `scripts/paddock/__main__.py`, replace the two lines

```python
from paddock import bundle, logs, matrix, results

MODULES = (bundle, matrix, logs, results)
```

with

```python
from paddock import bundle, logs, matrix, probe, results

MODULES = (bundle, matrix, logs, results, probe)
```

- [ ] **Step 5: Run the tests to verify they pass.**

Run: `python -m pytest tests/unit -q`
Expected: every test passes. `test_probe.py` contributes 12.

- [ ] **Step 6: Commit.**

```bash
git add scripts/paddock/probe.py scripts/paddock/__main__.py tests/unit/test_probe.py
git commit -s -m "Plan must-block probe requests from a provider profile"
```

---

### Task 4: Withheld must-block details, and Plan 1 follow-ups (CRLF, the v0.0.116 column, missing results)

Public results withhold the details of must-block checks that do not pass (spec §7.6). This task also closes the deferred Plan 1 review minors 1, 9 and 10. The maintainer chose to show v0.0.116 as unsupported rather than hide it.

**Files:**
- Modify: `scripts/paddock/results.py`
- Modify: `scripts/paddock/bundle.py`
- Modify: `scripts/ci/openshell-versions.json`
- Modify: `bundles/opencode/bundle.yaml`
- Modify: `bundles/opencode/README.md`
- Modify: `.github/workflows/ci.yml`
- Test: `tests/unit/test_results.py`, `tests/unit/test_bundle.py`, `tests/unit/test_matrix.py` (append)

**Interfaces:**
- Consumes:
  - `matrix.load_versions`, `build_matrix` and `supports` (Plan 1 Task 5);
  - the report's `unsupported (needs X)` cell (Plan 1 Task 7).
- Produces:
  - `openshell-versions.json` = `["v0.1.2", "v0.0.116"]`. The primary version stays `versions[0]`.
  - OpenCode cells run only on v0.1.2.
  - `results.public_checks(checks)` and `results.WITHHELD`: when any `deny-*` check is neither `pass` nor `skip`, every `deny-*` check is replaced by one `{"name": "deny", "status": "fail" or "error", "detail": WITHHELD}`. `cell_result` applies it.

- [ ] **Step 1: Write the failing tests.** Append to `tests/unit/test_results.py`:

```python
def test_must_block_details_are_withheld_when_a_deny_check_does_not_pass():
    # Spec 7.6 and 9.2: a must-block check that does not pass may describe an
    # unfixed OpenShell weakness, and CI results on this public repo are public.
    checks = [
        {"name": "version:api-key", "status": "pass", "detail": "opencode v2.0.21"},
        {"name": "deny-m1-ipv6:api-key", "status": "fail", "detail": "the probe reached 2606:4700:4700::1111:443"},
        {"name": "deny-m1-tcp-ip:api-key", "status": "pass", "detail": ""},
        {"name": "deny-m2-control:api-key", "status": "error", "detail": "only 0 of 1 allowed requests"},
    ]
    result = cell_result("demo", "v0.1.2", "ubuntu-24.04", checks)
    assert result["status"] == "fail"
    assert [check["name"] for check in result["checks"]] == ["version:api-key", "deny"]
    assert result["checks"][1]["status"] == "fail"
    assert "2606" not in json.dumps(result)
    assert "ipv6" not in json.dumps(result)


def test_passing_must_block_checks_stay_public():
    checks = [
        {"name": "deny-m1-ipv6:api-key", "status": "pass", "detail": ""},
        {"name": "deny-m2-literal-credential:api-key", "status": "skip", "detail": "forwarded unchanged"},
    ]
    assert cell_result("demo", "v0.1.2", "ubuntu-24.04", checks)["checks"] == checks
```

Append to `tests/unit/test_bundle.py`:

```python
def test_crlf_is_reported_even_when_the_schema_fails(make_bundle, valid_meta):
    # One round trip shows every problem, not the schema errors first and CRLF later.
    del valid_meta["image"]
    bundle_dir = make_bundle(valid_meta, files={"tests/allow.sh": "#!/usr/bin/env bash\r\n"})
    with pytest.raises(BundleError) as exc:
        load_bundle(bundle_dir)
    assert "'image' is a required property" in str(exc.value)
    assert "CRLF line endings in tests/allow.sh" in str(exc.value)
```

Append to `tests/unit/test_matrix.py`:

```python
def test_repository_lists_v0_0_116_but_opencode_runs_only_where_supported():
    # ADR 0001: v0.0.116 cannot start Alpine-based images, so the report shows
    # "unsupported (needs v0.1.0)" for it instead of hiding the version.
    from pathlib import Path

    from paddock.bundle import load_bundle
    from paddock.matrix import load_versions

    root = Path(__file__).resolve().parents[2]
    versions = load_versions(root / "scripts" / "ci" / "openshell-versions.json")
    assert versions == ["v0.1.2", "v0.0.116"]
    cells = build_matrix([load_bundle(root / "bundles" / "opencode")], versions)
    assert {cell["openshell_version"] for cell in cells} == {"v0.1.2"}
```

- [ ] **Step 2: Run them to verify they fail.**

Run: `python -m pytest tests/unit/test_results.py tests/unit/test_bundle.py tests/unit/test_matrix.py -q`
Expected: `3 failed, 52 passed`. The deny details are still published, the CRLF message is missing, and `versions == ['v0.1.2']`.

- [ ] **Step 3: Withhold must-block details in public results.** In `scripts/paddock/results.py`, replace

```python
def cell_result(bundle_name, version, runner, checks):
    return {
```

with

```python
# Spec 7.6 and 9.2: a must-block check that does not pass may describe an unfixed
# OpenShell weakness, and CI results on this public repo are public. Such checks
# are folded into one line without details; run-cell.sh encrypts the raw logs
# for the maintainer.
WITHHELD = "one or more must-block checks did not pass; details are encrypted for the maintainer (spec 7.6)"


def public_checks(checks):
    deny = [check for check in checks if check["name"].startswith("deny-")]
    if all(check["status"] in ("pass", "skip") for check in deny):
        return checks
    status = "fail" if any(check["status"] == "fail" for check in deny) else "error"
    others = [check for check in checks if not check["name"].startswith("deny-")]
    return others + [{"name": "deny", "status": status, "detail": WITHHELD}]


def cell_result(bundle_name, version, runner, checks):
    checks = public_checks(checks)
    return {
```

- [ ] **Step 4: Run the CRLF scan on every load.** In `scripts/paddock/bundle.py`, `load_bundle`, replace

```python
    if not problems:
        problems = _check_files(bundle_dir, meta)
```

with

```python
    if not problems:
        problems = _check_files(bundle_dir, meta)
    problems += _crlf_problems(bundle_dir)
```

In `_check_files`, replace the final loop

```python
    for path in sorted(bundle_dir.rglob("*")):
```

with

```python
    return problems


def _crlf_problems(bundle_dir):
    problems = []
    for path in sorted(bundle_dir.rglob("*")):
```

That leaves the loop body and its `return problems` as the new function's body.

- [ ] **Step 5: List v0.0.116 and set OpenCode's minimum.** Replace `scripts/ci/openshell-versions.json` with:

```json
{
  "versions": ["v0.1.2", "v0.0.116"]
}
```

In `bundles/opencode/bundle.yaml`, add these lines after `revision: 1`:

```yaml
# ADR 0001: the v0.0.116 supervisor needs iproute2 inside the image, which this
# Alpine image lacks; the report shows v0.0.x as unsupported.
openshell_min_version: "v0.1.0"
```

In `bundles/opencode/README.md`, add this paragraph at the end of the "Tested with" section:

```markdown
OpenShell v0.0.x is not supported: its sandbox supervisor creates the network
namespace with `ip netns` from inside the image, and the official OpenCode image
is Alpine without iproute2 ([ADR 0001](../../docs/decisions/0001-ci-runners.md)).
```

- [ ] **Step 6: Fail a cell whose results are missing.** In `.github/workflows/ci.yml`, in the `cell` job's upload step, change `if-no-files-found: warn` to `if-no-files-found: error`.

- [ ] **Step 7: Run the tests and validate.**

Run: `python -m pytest tests/unit -q && PYTHONPATH=scripts python -m paddock validate`
Expected: every test passes, then `ok: opencode`.

Run: `mkdir -p /tmp/r && PYTHONPATH=scripts python -m paddock report --results /tmp/r | tail -1`
Expected: `| opencode | not run | not run | unsupported (needs v0.1.0) | unsupported (needs v0.1.0) |`

- [ ] **Step 8: Commit.**

```bash
git add scripts/paddock/results.py scripts/paddock/bundle.py scripts/ci/openshell-versions.json \
  bundles/opencode/bundle.yaml bundles/opencode/README.md .github/workflows/ci.yml \
  tests/unit/test_results.py tests/unit/test_bundle.py tests/unit/test_matrix.py
git commit -s -m "Withhold must-block details, show v0.0.116 as unsupported, report CRLF with schema errors"
```

---

### Task 5: CI helpers: quiet mode, probe upload, event polling and stricter gateway checks

These also close Plan 1 minors 5 (`sandbox_ready`) and 7 (`gateway_connected`). The bash tests run only on Linux, so they are watched failing in CI through a draft pull request.

**Files:**
- Modify: `scripts/ci/lib.sh` (whole file below)
- Create: `scripts/ci/install-probe.sh`
- Test: `tests/unit/test_ci_lib.py` (append)

**Interfaces:**
- Consumes: `paddock_py events` filters (Task 2).
- Produces, in `scripts/ci/lib.sh`:
  - `PADDOCK_PROBE_PATH=/sandbox/.paddock/curl`.
  - `upload_probe <sandbox> <local-file>`: uploads, runs `chmod 0755`, and checks the probe runs.
  - `fetch_events <sandbox> <file>`: `openshell logs -n 20000 --source sandbox` into the file.
  - `await_event <sandbox> <file> <events filters…>`: polls for up to `PADDOCK_EVENT_WAIT` seconds (default 10), prints the count, and succeeds when it is at least 1.
  - `record_check`: prints nothing when `PADDOCK_QUIET=1`.
  - `gateway_connected`: falls back to the text output only on a usage error, with a 15 s timeout.
  - `sandbox_ready`: accepts only `Ready` and `SANDBOX_PHASE_READY`.
  - `seal_logs <dir> <out.age>`: encrypts the folder with `age` to `.github/findings-recipients.txt` (installing `age` with apt if it is missing), then deletes the folder. Without a key it only deletes.
- Produces `scripts/ci/install-probe.sh`, which prints the installed probe path (`~/.local/share/paddock/curl`).

- [ ] **Step 1: Write the failing tests.** Append to `tests/unit/test_ci_lib.py`:

```python
ROOT = LIB.parents[2]


def test_gateway_connected_does_not_fall_back_when_json_status_fails(tmp_path):
    # A newer CLI that errors on a disconnected gateway must not read as connected
    # just because its plain-text output still has a Version: line.
    fake = 'if [ "${2:-}" = "-o" ]; then echo "error: connection refused" >&2; exit 1; fi\necho "Version: 0.1.2"'
    assert run_lib(tmp_path, fake, "gateway_connected").returncode != 0


def test_sandbox_ready_accepts_only_the_ready_phase(tmp_path):
    assert run_lib(tmp_path / "a", """echo '{"phase":"SANDBOX_PHASE_READY"}'""", "sandbox_ready demo").returncode == 0
    assert run_lib(tmp_path / "b", """echo '{"phase":"NOT_READY"}'""", "sandbox_ready demo").returncode != 0


def test_record_check_is_silent_in_quiet_mode(tmp_path):
    checks = tmp_path / "checks.tsv"
    loud = run_lib(tmp_path / "a", "exit 0", f'PADDOCK_CHECKS_FILE="{checks}" record_check demo pass "x"')
    quiet = run_lib(tmp_path / "b", "exit 0", f'PADDOCK_QUIET=1 PADDOCK_CHECKS_FILE="{checks}" record_check demo fail "x"')
    assert "check demo: pass" in loud.stderr
    assert quiet.stderr == ""
    assert checks.read_text(encoding="utf-8") == "demo\tpass\tx\ndemo\tfail\tx\n"


LOG_LINE = ("[1.0] [sandbox] [OCSF ] [ocsf] NET:OPEN [MED] DENIED /sandbox/.paddock/curl(0) -> "
            "pd-1.example.com:443 [reason:transparent_tcp_policy_denied]")


def test_await_event_counts_matching_lines(tmp_path):
    events = tmp_path / "events.log"
    fake = f'[ "$1" = logs ] && echo "{LOG_LINE}"'
    snippet = (f'PADDOCK_ROOT="{ROOT}" PADDOCK_EVENT_WAIT=1 await_event demo "{events}" '
               '--action DENIED --host pd-1.example.com --port 443')
    result = run_lib(tmp_path, fake, snippet)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1"
    assert "pd-1.example.com" in events.read_text(encoding="utf-8")


def test_await_event_fails_when_nothing_matches(tmp_path):
    fake = f'[ "$1" = logs ] && echo "{LOG_LINE}"'
    snippet = (f'PADDOCK_ROOT="{ROOT}" PADDOCK_EVENT_WAIT=1 await_event demo "{tmp_path}/e.log" '
               '--action DENIED --host other.example.com')
    result = run_lib(tmp_path, fake, snippet)
    assert result.returncode != 0
    assert result.stdout.strip() == "0"


def test_seal_logs_encrypts_to_the_maintainer_and_deletes_the_plaintext(tmp_path):
    root = tmp_path / "root"
    (root / ".github").mkdir(parents=True)
    (root / ".github" / "findings-recipients.txt").write_text("age1" + "q" * 58 + "\n", encoding="utf-8")
    logs = tmp_path / "results" / "logs" / "cell"
    logs.mkdir(parents=True)
    (logs / "checks.tsv").write_text("deny-m1-ipv6:api-key\tfail\tsecret\n", encoding="utf-8")
    out = tmp_path / "results" / "cell.private.tgz.age"
    # A stand-in for age that copies the tar stream; the real tool encrypts it.
    snippet = (f'age() {{ [ "$1" = -R ] && [ "$3" = -o ] && cat >"$4"; }}; '
               f'PADDOCK_ROOT="{root}" seal_logs "{logs}" "{out}"')
    result = run_lib(tmp_path / "x", "exit 0", snippet)
    assert result.returncode == 0, result.stderr
    assert not logs.exists()
    assert out.stat().st_size > 0


def test_seal_logs_without_a_key_still_deletes_the_plaintext(tmp_path):
    logs = tmp_path / "results" / "logs" / "cell"
    logs.mkdir(parents=True)
    (logs / "checks.tsv").write_text("deny-m1-ipv6:api-key\tfail\tsecret\n", encoding="utf-8")
    out = tmp_path / "results" / "cell.private.tgz.age"
    result = run_lib(tmp_path / "x", "exit 0", f'PADDOCK_ROOT="{tmp_path}" seal_logs "{logs}" "{out}"')
    assert result.returncode == 0, result.stderr
    assert not logs.exists()
    assert not out.exists()
```

- [ ] **Step 2: Watch them fail on Linux.** Commit the tests alone and open a draft pull request; the rest of this plan pushes to it.

```bash
git add tests/unit/test_ci_lib.py
git commit -s -m "Add failing tests for the M3 CI helpers"
git push -u origin m3-deny
gh pr create --repo paddockhq/paddock --draft --base main --head m3-deny \
  --title "M3: shared must-block suite" \
  --body "Implements Plan 2 (docs/superpowers/plans/2026-10-06-paddock-plan-2-m3.md) Tasks 1-6. Draft until the suite passes.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
gh pr checks m3-deny --repo paddockhq/paddock --watch
```

Expected: `unit tests and linters` fails. Its log (`gh run view <id> --repo paddockhq/paddock --log-failed`) shows these failures:
- `test_gateway_connected_does_not_fall_back_when_json_status_fails`
- `test_sandbox_ready_accepts_only_the_ready_phase`
- `test_record_check_is_silent_in_quiet_mode`
- `test_await_event_counts_matching_lines`
- `test_await_event_fails_when_nothing_matches`
- `test_seal_logs_encrypts_to_the_maintainer_and_deletes_the_plaintext`
- `test_seal_logs_without_a_key_still_deletes_the_plaintext`

The `await_event` and `seal_logs` tests fail with `command not found`. The OpenCode cells still pass.

- [ ] **Step 3: Replace `scripts/ci/lib.sh` with:**

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
```

- [ ] **Step 4: Create `scripts/ci/install-probe.sh`:**

```bash
#!/usr/bin/env bash
# Download the static curl that the must-block tests run inside sandboxes, verify
# it against pinned checksums, and install it to ~/.local/share/paddock/curl.
# Usage: install-probe.sh   (prints the installed path)
# Source: https://github.com/stunnel/static-curl (MIT), release 8.22.0, musl build.
# CI only downloads and runs it; PadDock never redistributes it.
set -euo pipefail
# shellcheck source=scripts/ci/lib.sh
source "$(dirname "$0")/lib.sh"

release=8.22.0
case "$(uname -m)" in
  x86_64)
    arch=x86_64
    tarball_sha=dfb02460ba2abe513087538f12a3cf79b74b64a5ea3787ce8ac0cdb11251f884
    binary_sha=b7443db66d622a27ef2152bb2032d6ada9fb29a8917f22b9521a993f8e61cd7f
    ;;
  aarch64 | arm64)
    arch=aarch64
    tarball_sha=cf94cbeaae1b3c1944a4a761ef04478f8f0b23e93a324b5ed009b2082eda11f3
    binary_sha=c392bc0ea0c7951ee170e0eb7874c9d4000397254d788552ffaa4e7ccb75ae07
    ;;
  *) die "unsupported architecture $(uname -m)" ;;
esac

work="$(mktemp -d)"
tarball="$work/curl.tar.xz"
curl -fsSL --retry 3 -o "$tarball" \
  "https://github.com/stunnel/static-curl/releases/download/${release}/curl-linux-${arch}-musl-${release}.tar.xz"
echo "$tarball_sha  $tarball" | sha256sum -c - >&2
tar -xJf "$tarball" -C "$work"
binary="$(find "$work" -type f -name curl | head -n 1)"
[ -n "$binary" ] || die "curl not found inside the static-curl tarball"
echo "$binary_sha  $binary" | sha256sum -c - >&2
dest="$HOME/.local/share/paddock/curl"
mkdir -p "${dest%/*}"
install -m 0755 "$binary" "$dest"
echo "$dest"
```

```bash
chmod +x scripts/ci/install-probe.sh
git add scripts/ci/install-probe.sh
git update-index --chmod=+x scripts/ci/install-probe.sh
```

- [ ] **Step 5: Lint.** If shellcheck is installed locally (`pip install shellcheck-py` into `.venv` works on Windows), run:

```bash
shellcheck -x scripts/ci/*.sh
```

Expected: no output.

- [ ] **Step 6: Commit, push and watch the tests pass.**

```bash
git add scripts/ci/lib.sh scripts/ci/install-probe.sh
git commit -s -m "CI helpers: quiet mode, probe upload, event polling, stricter gateway and ready checks"
git push
gh pr checks m3-deny --repo paddockhq/paddock --watch
```

Expected: every check passes. `unit tests and linters` reports 99 passed on Linux, including all 15 `test_ci_lib.py` tests.

---

### Task 6: The shared must-block suite in both run modes (M3 exit, part 1)

This task also closes Plan 1 minors 2, 3, 4, 6 and 8:
- 2: the allow.sh contract;
- 3: the log race;
- 4: other allowed hosts;
- 6: `--no-login-shell` is required;
- 8: stale provider info.

**Files:**
- Create: `tests/deny/run.sh`
- Modify: `scripts/ci/run-cell.sh` (whole file below)
- Modify: `bundles/opencode/tests/allow.sh` (egress block)
- Modify: `README.md`

**Interfaces:**
- Consumes:
  - `probe-plan`, `variant-profile` (Task 3);
  - `events` filters (Task 2);
  - `upload_probe`, `await_event`, `fetch_events`, `PADDOCK_PROBE_PATH`, `install-probe.sh` (Task 5);
  - the allow.sh contract (Plan 1 Task 8).
- Produces:
  - **`tests/deny/run.sh` contract.** Environment, in addition to allow.sh's `PADDOCK_ROOT`, `PADDOCK_LOG_DIR` and `PADDOCK_CHECKS_FILE`:
    - `PADDOCK_SANDBOX`, `PADDOCK_AUTH_MODE`
    - `PADDOCK_RUN_MODE`: `m1`, `m2` or `fd`
    - `PADDOCK_PROVIDER_FILE`, `PADDOCK_DUMMY_CREDENTIAL`
    - `PADDOCK_PROBE` (optional)
    - `PADDOCK_SURVEY=1` (optional)
    - It always exits 0, and records every result with `record_check`.
  - **Check names:**
    - `deny-<run>-{unlisted-host,dns-unlisted,dns-outside-udp,dns-outside-tcp,tcp-ip,udp-ip,ipv6,sentry}:<mode>`
    - `deny-m1-write-outside:<mode>`
    - `deny-<run>-control:<mode>`
    - `deny-<run>-l7-{method,path}-<host>:<mode>`
    - `deny-<run>-literal-credential:<mode>` (always `skip`, a record)
    - `deny-<run>-survey-<METHOD>-<host>:<mode>` (fd only)
  - **`run-cell.sh`** records:
    - `allow-contract:<mode>` errors when allow.sh skipped a must-work check (`version`, `state-writable`, `egress`, and `upstream-auth-error` or `live-answer`);
    - `deny-<run>-setup:<mode>` errors.
    - `--live` runs skip the must-block suite.
  - **`run-cell.sh` `finish`** seals `results/logs/<cell>/` into `results/<cell>.private.tgz.age` when a `deny-*` check is `fail` or `error`.

- [ ] **Step 1: Create `tests/deny/run.sh`:**

```bash
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
#   - UDP and the outside-resolver query produce no log line in OpenShell v0.1.2. They
#     pass on the broker's errno text ("Destination address required" or "Permission
#     denied"); any other failure, such as "Network is unreachable", is "error".
#   - The file-write check passes on "Permission denied" for a folder that Unix
#     permissions allow (/var/tmp), so only Landlock can be the reason.
set -uo pipefail
# shellcheck source=scripts/ci/lib.sh
source "$PADDOCK_ROOT/scripts/ci/lib.sh"

sb="$PADDOCK_SANDBOX"
mode="$PADDOCK_AUTH_MODE"
run="$PADDOCK_RUN_MODE"
probe="${PADDOCK_PROBE:-$PADDOCK_PROBE_PATH}"
nonce="$(date +%s)$$"
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

# errno_block <item> <command...>: for attempts OpenShell blocks without a log line.
errno_block() {
  local item="$1"
  shift
  attempt "$item" "$@"
  if [ "$rc" -eq 0 ]; then
    check "$item" fail "the attempt succeeded"
  elif grep -qiE 'Destination address required|Permission denied' "$out/$item.txt"; then
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

mapfile -t plan < <(paddock_py probe-plan "$PADDOCK_PROVIDER_FILE" --nonce "$nonce")
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
```

```bash
chmod +x tests/deny/run.sh
git add tests/deny/run.sh
git update-index --chmod=+x tests/deny/run.sh
```

- [ ] **Step 2: Replace `scripts/ci/run-cell.sh` with:**

```bash
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
PADDOCK_LOG_DIR="$results_dir/logs/$cell"
PADDOCK_CHECKS_FILE="$PADDOCK_LOG_DIR/checks.tsv"
export PADDOCK_LOG_DIR PADDOCK_CHECKS_FILE
mkdir -p "$PADDOCK_LOG_DIR"
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
  # OpenShell weakness. The public result withholds its details (results.py);
  # the raw logs are encrypted for the maintainer, and the plaintext is deleted.
  if grep -qE $'^deny-[^\t]*\t(fail|error)\t' "$PADDOCK_CHECKS_FILE"; then
    seal_logs "$PADDOCK_LOG_DIR" "$results_dir/$cell.private.tgz.age"
  fi
  exit "$rc"
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
# <label> names the log file: sandbox-<label>.log.
create_sandbox() {
  local sandbox="$1" provider="$2" label="$3"
  openshell sandbox create --name "$sandbox" --from "$PADDOCK_IMAGE" \
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
  if ! openshell provider profile import -f "$variant" </dev/null >"$PADDOCK_LOG_DIR/import-$mode-child.log" 2>&1 ||
    ! openshell provider create --name "$provider" --type "$VARIANT_PROFILE_ID" "${CRED_ARGS[@]}" \
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
  openshell logs "$sandbox" --source all -n 20000 </dev/null >"$PADDOCK_LOG_DIR/sandbox-logs-$mode-child.txt" 2>&1 || true
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
  credential_args "$mode" "$dummy_credential" || return
  if openshell provider create --name "$provider" --type "$PROFILE_ID" "${CRED_ARGS[@]}" \
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
  require_allow_checks "$mode"

  # Must-block run mode 1 uses the same sandbox, after the must-work tests.
  if [ "$live" != 1 ]; then
    deny_suite m1 "$sandbox" "$mode" "$provider_file" "$dummy_credential"
  fi

  openshell logs "$sandbox" --source all -n 20000 </dev/null >"$PADDOCK_LOG_DIR/sandbox-logs-$mode.txt" 2>&1 || true
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
```

- [ ] **Step 3: Make allow.sh wait for the log and flag other allowed hosts.** In `bundles/opencode/tests/allow.sh`, replace everything from the line `sleep 3` through the `fi` that closes the `egress` check with:

```bash
# OpenShell pushes log lines in batches: wait for the request's own line, then
# judge everything logged so far.
events="$PADDOCK_LOG_DIR/policy-events-$mode.log"
allowed="$(await_event "$sb" "$events" --action ALLOWED --kind HTTP --host openrouter.ai)" || true
# Read once more after a further batch interval, so a connection opencode made
# just before it exited is judged too.
sleep 2
fetch_events "$sb" "$events"
denied="$(paddock_py events --log "$events" --action DENIED --format hosts)"
others="$(paddock_py events --log "$events" --action ALLOWED --format hosts | grep -vx 'openrouter.ai:443' || true)"
if [ -n "$denied" ]; then
  record_check "egress:$mode" fail "denied destinations: $(tr '\n' ' ' <<<"$denied")"
elif [ -n "$others" ]; then
  record_check "egress:$mode" fail "allowed destinations other than openrouter.ai: $(tr '\n' ' ' <<<"$others")"
elif [ "${allowed:-0}" -lt 1 ]; then
  record_check "egress:$mode" fail "no allowed request to openrouter.ai was logged"
else
  record_check "egress:$mode" pass "openrouter.ai only"
fi
```

- [ ] **Step 4: Explain the suite in the root README.** In `README.md`, insert this section above `## Layout`:

```markdown
## What CI proves for every bundle

- **Must work:** the agent starts, writes its state, and reaches its model API.
  The sandbox sees only OpenShell's credential placeholder, never the key.
- **Must block** ([tests/deny/run.sh](tests/deny/run.sh)), from a process outside
  the agent and again from a probe given exactly the agent's rules:
  unlisted hosts, DNS of unlisted names, DNS to outside resolvers, TCP and UDP to
  IP addresses, IPv6, `sentry.io`, disallowed methods and paths on the allowed
  host, and writes outside the writable folders. A check passes only on
  OpenShell's own evidence ([ADR 0002](docs/decisions/0002-must-block-observations.md)).
- **Within bounds:** `openshell-prover` confirms the effective policy stays inside
  the bundle's `boundary.yaml`.
```

- [ ] **Step 5: Lint and run the unit tests.**

```bash
shellcheck -x scripts/ci/*.sh tests/deny/run.sh bundles/*/tests/*.sh
python -m pytest tests/unit -q
```

Expected: no shellcheck output, and every test passes.

- [ ] **Step 6: Commit and push.**

```bash
git add tests/deny/run.sh scripts/ci/run-cell.sh bundles/opencode/tests/allow.sh README.md
git commit -s -m "Add the shared must-block suite, run in both modes for every auth mode"
git push
gh pr checks m3-deny --repo paddockhq/paddock --watch
```

- [ ] **Step 7: Download the results.**

```bash
run_id="$(gh run list --repo paddockhq/paddock --workflow ci.yml --branch m3-deny --limit 1 --json databaseId --jq '.[0].databaseId')"
rm -rf ci-out && gh run download "$run_id" --repo paddockhq/paddock --dir ci-out
cat ci-out/compatibility-report/COMPATIBILITY.md
cut -f1,2 ci-out/cell-opencode--v0.1.2--ubuntu-24.04/logs/*/checks.tsv
```

- [ ] **Step 8: If a check is not `pass`,** read its detail and `ci-out/cell-*/logs/<cell>/deny-<run>-api-key/<item>.txt`, then use this table. Commit any fix with `-s` and push again.

| Symptom | Cause and fix |
|---|---|
| `deny-*-setup:api-key error` "could not upload and run the probe" | Read `sandbox-api-key.log`. Upload needs `/sandbox` writable by UID 1000 (R6). |
| `deny-m2-control:api-key error` | The variant profile was not applied. Read `import-api-key-child.log` and `provider-api-key-child.log`; the variant id is `paddock-opencode-openrouter-probe`. Never relax the control. |
| `deny-*-<item> error` "logged no denial" | A log line arrived later than 10 s, or its format changed. Compare `deny-<run>-api-key-events.log` with ADR 0002. If the format changed, update ADR 0002 and `scripts/paddock/logs.py` with a test first. Raise `PADDOCK_EVENT_WAIT` only if lines are merely slow. |
| `deny-*-udp-ip` or `dns-outside-udp error` | The error text differs from ADR 0002. Read `<item>.txt`. Add the new broker text to `errno_block` only if it names a policy refusal; `Network is unreachable` is not one. |
| The public result shows `deny` as `fail` or `error`, "details are encrypted for the maintainer" | The raw logs are in the cell artifact as `<cell>.private.tgz.age`, readable only by the maintainer (`age -d -i ~/paddock-findings.key <file> \| tar xz`). For `error`, use the rows above with the decrypted logs. For **fail**, access leaked: stop and tell the maintainer privately (spec §7.6). Do not open a public issue or paste the details anywhere public. |

- [ ] **Step 9: Check the M3 exit criterion for the OpenCode bundle.**

Expected, for both `ubuntu-24.04` and `ubuntu-24.04-arm`:
- Every check in `checks.tsv` is `pass`, except `deny-m2-literal-credential:api-key skip` (a record).
- The check list includes:
  - `deny-m1-` × 9: unlisted-host, dns-unlisted, dns-outside-udp, dns-outside-tcp, tcp-ip, udp-ip, ipv6, sentry, write-outside;
  - `deny-m2-` × 8: the same items without write-outside;
  - `deny-m2-control:api-key pass`;
  - `deny-m2-l7-method-openrouter.ai:api-key pass` and `deny-m2-l7-path-openrouter.ai:api-key pass`.
- `COMPATIBILITY.md` shows `pass | pass | unsupported (needs v0.1.0) | unsupported (needs v0.1.0)`.

- [ ] **Step 10: Merge.**

```bash
gh pr ready m3-deny --repo paddockhq/paddock
gh pr merge m3-deny --repo paddockhq/paddock --merge --delete-branch
git switch main
git pull --ff-only
```

---

### Task 7: The findings job (M3 exit, part 2)

**Files:**
- Create: `tests/findings/profiles.tsv`, `tests/findings/policy.yaml`, `scripts/ci/findings.sh`, `.github/workflows/findings.yml`

**Interfaces:**
- Consumes:
  - `tests/deny/run.sh` with `PADDOCK_RUN_MODE=fd`, `PADDOCK_PROBE`, `PADDOCK_SURVEY=1` (Task 6);
  - `probe-binary` (Task 3);
  - `PADDOCK_QUIET` and `install-probe.sh` (Task 5);
  - `PADDOCK_IMAGE` from `bundle-env bundles/opencode`;
  - `.github/findings-recipients.txt` (Task 1).
- Produces:
  - the `findings` workflow (workflow_dispatch, main only);
  - the artifact `findings`, containing only `findings.tgz.age`.

- [ ] **Step 1: Create the branch.**

```bash
git switch -c findings-job
grep -qE '^age1[a-z0-9]{58}$' .github/findings-recipients.txt && echo ok
```

Expected: `ok` (the key added in Task 1).

- [ ] **Step 2: Create `tests/findings/profiles.tsv`** (tab-separated):

```text
# NVIDIA example provider profiles the findings job tests (spec 7.5), one per line:
# <profile id><TAB><provider create arguments>. Profiles come unmodified from
# https://github.com/NVIDIA/OpenShell/tree/<release>/providers. Credentials are
# dummy values; aws-s3 mints its own, so it takes --runtime-credentials.
# github is the control: its read-only rules must block POST /gists.
github	--credential GITHUB_TOKEN=paddock-findings-dummy
claude-code	--credential ANTHROPIC_API_KEY=paddock-findings-dummy
codex	--credential CODEX_AUTH_ACCESS_TOKEN=paddock-findings-dummy --credential CODEX_AUTH_REFRESH_TOKEN=paddock-findings-dummy --credential CODEX_AUTH_ACCOUNT_ID=paddock-findings-dummy
copilot	--credential COPILOT_GITHUB_TOKEN=paddock-findings-dummy
openrouter	--credential OPENROUTER_API_KEY=paddock-findings-dummy
anthropic	--credential ANTHROPIC_API_KEY=paddock-findings-dummy
openai	--credential OPENAI_API_KEY=paddock-findings-dummy
nvidia	--credential NVIDIA_API_KEY=paddock-findings-dummy
deepinfra	--credential DEEPINFRA_API_KEY=paddock-findings-dummy
pypi
cursor
aws-s3	--runtime-credentials
```

- [ ] **Step 3: Create `tests/findings/policy.yaml`:**

```yaml
# Base sandbox policy for the findings job. It grants no network access of its
# own, so every request a probe makes is judged by the NVIDIA profile under test.
# Filesystem rules match the OpenCode bundle, whose image the findings image
# starts from (UID 1000, HOME=/sandbox).
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
    - /var/log
  read_write:
    - /sandbox
    - /tmp
    - /dev/null
landlock:
  compatibility: hard_requirement
process:
  run_as_user: "1000"
  run_as_group: "1000"
```

- [ ] **Step 4: Create `scripts/ci/findings.sh`:**

```bash
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
```

- [ ] **Step 5: Create `.github/workflows/findings.yml`:**

```yaml
name: findings
# Spec 7.5: run the must-block suite against NVIDIA's unmodified example provider
# profiles. Results stay private until disclosed (spec 9.2). Job logs, summaries
# and artifacts of a public repo are visible to any signed-in user, so every
# result is encrypted to the maintainer's age key before upload, and no step
# prints an outcome. Decrypt with:
#   gh run download <run-id> --repo paddockhq/paddock -n findings
#   age -d -i <your key file> findings.tgz.age | tar xz
on:
  workflow_dispatch:

permissions:
  contents: read

defaults:
  run:
    shell: bash

concurrency:
  group: findings
  cancel-in-progress: false

jobs:
  findings:
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-24.04
    timeout-minutes: 120
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: '3.12'
      - run: python -m pip install -r requirements-dev.txt
      - name: Check the maintainer's age recipient
        run: |
          if ! grep -qE '^age1[a-z0-9]{58}$' .github/findings-recipients.txt; then
            echo "::error::.github/findings-recipients.txt has no age public key (age1...)."
            exit 1
          fi
      - name: Install age
        run: |
          sudo apt-get update -qq
          sudo apt-get install -y -qq age >/dev/null
      - name: Run the findings suite (all output goes to files)
        run: |
          mkdir -p "$RUNNER_TEMP/findings"
          if bash scripts/ci/findings.sh "$RUNNER_TEMP/findings" >"$RUNNER_TEMP/findings/console.log" 2>&1; then
            echo "findings run finished"
          else
            echo "findings setup failed; details are in the encrypted bundle"
          fi
      - name: Encrypt the results and delete the plain copy
        run: |
          tar -C "$RUNNER_TEMP" -czf "$RUNNER_TEMP/findings.tgz" findings
          age -R .github/findings-recipients.txt -o "$RUNNER_TEMP/findings.tgz.age" "$RUNNER_TEMP/findings.tgz"
          rm -rf "$RUNNER_TEMP/findings" "$RUNNER_TEMP/findings.tgz"
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        with:
          name: findings
          path: ${{ runner.temp }}/findings.tgz.age
          if-no-files-found: error
          retention-days: 3
```

- [ ] **Step 6: Lint, commit, and merge through a pull request.**

```bash
chmod +x scripts/ci/findings.sh
shellcheck -x scripts/ci/findings.sh
git add tests/findings .github/workflows/findings.yml scripts/ci/findings.sh
git update-index --chmod=+x scripts/ci/findings.sh
git commit -s -m "Add the findings job, with results encrypted to the maintainer"
git push -u origin findings-job
gh pr create --repo paddockhq/paddock --base main --head findings-job --title "Findings job (M3)" \
  --body "Implements Plan 2 Task 7. Manually triggered; results are age-encrypted to the maintainer.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
gh pr checks findings-job --repo paddockhq/paddock --watch
gh pr merge findings-job --repo paddockhq/paddock --merge --delete-branch
git switch main
git pull --ff-only
```

Expected: every check passes. `scripts/` is a shared path, so the OpenCode cells run again and pass.

- [ ] **Step 7: Run the findings job once, and confirm nothing leaked.**

```bash
gh workflow run findings.yml --repo paddockhq/paddock --ref main
sleep 10
run_id="$(gh run list --repo paddockhq/paddock --workflow findings.yml --limit 1 --json databaseId --jq '.[0].databaseId')"
gh run watch "$run_id" --repo paddockhq/paddock --exit-status
gh run view "$run_id" --repo paddockhq/paddock --log | grep -cE 'deny-|survey-|ALLOWED|DENIED|policy_denied' || true
gh api "repos/paddockhq/paddock/actions/runs/$run_id/artifacts" --jq '.artifacts[].name'
```

Expected:
- the run succeeds;
- the grep count is `0`;
- the only artifact is `findings`.

If the count is not 0, delete the run at once with `gh run delete "$run_id" --repo paddockhq/paddock`, then find and fix the step that printed it.

- [ ] **Step 8 (maintainer): Decrypt and review privately.** In PowerShell:

```powershell
gh run download <run_id> --repo paddockhq/paddock -n findings
age -d -i "$HOME\paddock-findings.key" findings.tgz.age > findings.tgz
tar -xzf findings.tgz
```

- Read `findings/<profile>/checks.tsv`. The `github` control should show `deny-fd-control:github pass` and both `l7-*` checks `pass`.
- Every `fail` or `ALLOWED` survey line on a host the profile grants to an agent is a candidate finding. Report it to NVIDIA under its SECURITY.md (psirt@nvidia.com), not in public (spec §9.2).
- Then delete the artifact:

```bash
gh api -X DELETE "repos/paddockhq/paddock/actions/artifacts/$(gh api repos/paddockhq/paddock/actions/runs/<run_id>/artifacts --jq '.artifacts[0].id')"
```

M3 is complete when both of these hold:
- Task 6 Step 9 holds on `main`;
- Step 7's run succeeded with no leak.

The next plan is M4 (the Codex bundle).
