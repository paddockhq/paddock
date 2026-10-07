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
