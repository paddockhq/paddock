"""Verdicts of tests/deny/run.sh, driven by a stand-in for the openshell CLI."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "tests" / "deny" / "run.sh"
PROVIDER = ROOT / "bundles" / "opencode" / "providers" / "opencode-openrouter.yaml"
PROBE = "/sandbox/.paddock/curl"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not shutil.which("bash"),
    reason="bash suite tests run on Linux (CI)",
)

# `sandbox exec` answers from a scenario file (the first line whose pattern is a
# substring of the command wins); `logs` prints a prepared log.
FAKE_OPENSHELL = r"""#!/usr/bin/env bash
if [ "$1" = sandbox ] && [ "$2" = exec ]; then
  if [ "${3:-}" = --help ]; then echo "  --no-tty  --no-login-shell"; exit 0; fi
  while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do shift; done
  shift
  cmd="$*"
  while IFS=$'\t' read -r pattern rc output; do
    if [ -n "$pattern" ] && [[ "$cmd" == *"$pattern"* ]]; then
      printf '%b\n' "$output"
      exit "$rc"
    fi
  done <"$FAKE_EXEC"
  echo "fake openshell: no scenario for: $cmd" >&2
  exit 99
fi
if [ "$1" = logs ]; then cat "$FAKE_LOG"; fi
exit 0
"""

REFUSED = "curl: (7) Failed to connect"
BLOCKED_EXEC = [
    ("Authorization: Bearer", 0, '{"error":{"message":"User not found.","code":401}}\\nhttp=401'),
    ("-X DELETE", 0, '{"error":"policy_denied","layer":"l7"}\\nhttp=403'),
    ("https://openrouter.ai/pd-42", 0, '{"error":"policy_denied","layer":"l7"}\\nhttp=403'),
    ("-d {} https://openrouter.ai/api/v1/chat/completions", 0, '{"error":{"code":401}}\\nhttp=401'),
    ("pd-42-host.example.com", 7, REFUSED),
    ("pd-42-dns.example.com", 7, REFUSED),
    ("tftp://8.8.8.8:53", 55, "curl: (55) Destination address required"),
    ("telnet://8.8.8.8:53", 7, REFUSED),
    ("telnet://1.1.1.1:443", 7, REFUSED),
    ("tftp://1.1.1.1:9999", 55, "curl: (55) Destination address required"),
    ("2606:4700:4700::1111", 7, REFUSED),
    ("sentry.io", 7, REFUSED),
    ("test -d /var/tmp", 0, "ok"),
    ("echo x >/var/tmp/pd-42", 1, "sh: can't create /var/tmp/pd-42: Permission denied"),
]


def net(action, host, port=None):
    if port is None:
        return f"[1.0] [sandbox] [OCSF ] [ocsf] NET:REFUSE [MED] {action} {host} [reason:policy_dns_ineligible]"
    return (f"[1.0] [sandbox] [OCSF ] [ocsf] NET:OPEN [MED] {action} {PROBE}(0) -> {host}:{port} "
            "[reason:transparent_tcp_policy_denied]")


def http(action, method, path):
    return (f"[1.0] [sandbox] [OCSF ] [ocsf] HTTP:{method} [MED] {action} {method} "
            f"http://openrouter.ai:443{path} [policy:_provider_x engine:l7]")


BLOCKED_LOG = [
    net("DENIED", "pd-42-host.example.com"), net("DENIED", "pd-42-host.example.com", 443),
    net("DENIED", "pd-42-dns.example.com"),
    net("DENIED", "8.8.8.8", 53), net("DENIED", "1.1.1.1", 443), net("DENIED", "2606:4700:4700::1111", 443),
    net("DENIED", "sentry.io"), net("DENIED", "sentry.io", 443),
    http("ALLOWED", "POST", "/api/v1/chat/completions"),
    http("DENIED", "DELETE", "/api/v1/chat/completions"),
    http("DENIED", "GET", "/pd-42"),
]


def run_suite(tmp_path, exec_lines=BLOCKED_EXEC, log_lines=BLOCKED_LOG, run="m2", provider=PROVIDER):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    fake = bin_dir / "openshell"
    fake.write_text(FAKE_OPENSHELL, encoding="utf-8")
    fake.chmod(0o755)
    (tmp_path / "exec.tsv").write_text(
        "".join(f"{pattern}\t{rc}\t{output}\n" for pattern, rc, output in exec_lines), encoding="utf-8")
    (tmp_path / "log.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()
    checks = tmp_path / "checks.tsv"
    checks.write_text("", encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_EXEC": str(tmp_path / "exec.tsv"),
        "FAKE_LOG": str(tmp_path / "log.txt"),
        "PADDOCK_ROOT": str(ROOT),
        "PADDOCK_LOG_DIR": str(logs),
        "PADDOCK_CHECKS_FILE": str(checks),
        "PADDOCK_SANDBOX": "sb",
        "PADDOCK_AUTH_MODE": "api-key",
        "PADDOCK_RUN_MODE": run,
        "PADDOCK_PROVIDER_FILE": str(provider),
        "PADDOCK_DUMMY_CREDENTIAL": "sk-or-v1-0000",
        "PADDOCK_NONCE": "42",
        "PADDOCK_EVENT_WAIT": "1",
    }
    result = subprocess.run(["bash", str(RUN)], env=env, capture_output=True, text=True, timeout=600, check=False)
    assert result.returncode == 0, result.stderr
    return {line.split("\t")[0]: line.split("\t")[1] for line in checks.read_text(encoding="utf-8").splitlines()}


def replace(exec_lines, pattern, rc, output):
    return [(p, rc, output) if p == pattern else (p, r, o) for p, r, o in exec_lines]


def test_every_check_passes_when_openshell_blocks_everything(tmp_path):
    verdicts = run_suite(tmp_path)
    assert verdicts == {
        "deny-m2-unlisted-host:api-key": "pass",
        "deny-m2-dns-unlisted:api-key": "pass",
        "deny-m2-dns-outside-udp:api-key": "pass",
        "deny-m2-dns-outside-tcp:api-key": "pass",
        "deny-m2-tcp-ip:api-key": "pass",
        "deny-m2-udp-ip:api-key": "pass",
        "deny-m2-ipv6:api-key": "pass",
        "deny-m2-sentry:api-key": "pass",
        "deny-m2-control:api-key": "pass",
        "deny-m2-l7-method-openrouter.ai:api-key": "pass",
        "deny-m2-l7-path-openrouter.ai:api-key": "pass",
        "deny-m2-literal-credential:api-key": "skip",
    }


def test_a_host_the_probe_reaches_is_a_fail(tmp_path):
    verdicts = run_suite(tmp_path, replace(BLOCKED_EXEC, "pd-42-host.example.com", 0, "<html>"))
    assert verdicts["deny-m2-unlisted-host:api-key"] == "fail"


def test_a_blocked_attempt_without_a_log_line_is_an_error(tmp_path):
    log = [line for line in BLOCKED_LOG if "1.1.1.1:443" not in line]
    assert run_suite(tmp_path, log_lines=log)["deny-m2-tcp-ip:api-key"] == "error"


def test_udp_needs_the_brokers_error_not_any_permission_denied(tmp_path):
    # A probe that cannot even run must not count as a blocked UDP send.
    broken = replace(BLOCKED_EXEC, "tftp://1.1.1.1:9999", 126, "sh: /sandbox/.paddock/curl: Permission denied")
    assert run_suite(tmp_path, broken)["deny-m2-udp-ip:api-key"] == "error"


def test_l7_checks_need_an_allowed_control_request(tmp_path):
    log = [line for line in BLOCKED_LOG if "ALLOWED" not in line]
    verdicts = run_suite(tmp_path, log_lines=log)
    assert verdicts["deny-m2-control:api-key"] == "error"
    assert not any("l7-" in name for name in verdicts)


def test_an_l7_403_without_a_log_line_is_an_error(tmp_path):
    log = [line for line in BLOCKED_LOG if "HTTP:DELETE" not in line]
    assert run_suite(tmp_path, log_lines=log)["deny-m2-l7-method-openrouter.ai:api-key"] == "error"


def test_a_broken_provider_profile_is_an_error_not_a_skip(tmp_path):
    broken = tmp_path / "broken.yaml"
    broken.write_text("endpoints: [\n", encoding="utf-8")
    verdicts = run_suite(tmp_path, provider=broken)
    assert verdicts["deny-m2-plan:api-key"] == "error"
    assert "deny-m2-l7:api-key" not in verdicts


def test_write_outside_passes_only_on_permission_denied_after_the_control(tmp_path):
    assert run_suite(tmp_path / "a", run="m1")["deny-m1-write-outside:api-key"] == "pass"
    wrote = replace(BLOCKED_EXEC, "echo x >/var/tmp/pd-42", 0, "")
    assert run_suite(tmp_path / "b", wrote, run="m1")["deny-m1-write-outside:api-key"] == "fail"
    no_control = replace(BLOCKED_EXEC, "test -d /var/tmp", 1, "")
    assert run_suite(tmp_path / "c", no_control, run="m1")["deny-m1-write-outside:api-key"] == "error"
