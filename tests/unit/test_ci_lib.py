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


def test_sandbox_name_fits_openshell_limit(tmp_path):
    # OpenShell v0.1.2 rejects sandbox names longer than 19 characters (DNS-1123 label).
    names = {}
    for bundle, mode in [("opencode", "api-key"), ("opencode", "subscription"),
                         ("claude-code", "subscription"), ("a" * 40, "api-key")]:
        result = run_lib(tmp_path / f"{len(names)}", "", f"sandbox_name {bundle} {mode}")
        assert result.returncode == 0, result.stderr
        name = result.stdout.strip()
        assert 0 < len(name) <= 19
        assert name[0].isalnum() and name[-1].isalnum()
        assert all(c.islower() or c.isdigit() or c == "-" for c in name)
        names[(bundle, mode)] = name
    assert len(set(names.values())) == len(names)
    assert names[("opencode", "api-key")].startswith("opencode-")


def test_openshell_is_matches_only_the_exact_release(tmp_path):
    fake = 'echo "openshell 0.1.2"'
    assert run_lib(tmp_path / "a", fake, "openshell_is v0.1.2").returncode == 0
    assert run_lib(tmp_path / "b", fake, "openshell_is v0.1.20").returncode != 0
    assert run_lib(tmp_path / "c", 'echo "openshell 0.1.20"', "openshell_is v0.1.2").returncode != 0
    assert run_lib(tmp_path / "d", "exit 1", "openshell_is v0.1.2").returncode != 0


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


def test_fetch_events_gives_up_on_a_hung_cli(tmp_path):
    # Every openshell call is bounded, so one hung call cannot eat the job timeout.
    import time

    start = time.monotonic()
    result = run_lib(tmp_path, 'if [ "$1" = logs ]; then sleep 30; fi',
                     f'PADDOCK_CLI_TIMEOUT=2 fetch_events sb "{tmp_path}/events.log"')
    assert result.returncode == 0, result.stderr
    assert time.monotonic() - start < 15


def test_publish_logs_moves_passing_logs_into_the_results(tmp_path):
    logs = tmp_path / "work" / "cell"
    logs.mkdir(parents=True)
    (logs / "checks.tsv").write_text("deny-m1-ipv6:api-key\tpass\t\nversion:api-key\tpass\tx\n", encoding="utf-8")
    results = tmp_path / "results"
    results.mkdir()
    result = run_lib(tmp_path / "x", "exit 0", f'PADDOCK_ROOT="{tmp_path}" publish_logs "{logs}" "{results}" cell')
    assert result.returncode == 0, result.stderr
    assert (results / "logs" / "cell" / "checks.tsv").is_file()
    assert not logs.exists()


def test_publish_logs_seals_them_when_a_must_block_check_did_not_pass(tmp_path):
    root = tmp_path / "root"
    (root / ".github").mkdir(parents=True)
    (root / ".github" / "findings-recipients.txt").write_text("age1" + "q" * 58 + "\n", encoding="utf-8")
    logs = tmp_path / "work" / "cell"
    logs.mkdir(parents=True)
    (logs / "checks.tsv").write_text("deny-m1-ipv6:api-key\tfail\tthe probe reached it\n", encoding="utf-8")
    results = tmp_path / "results"
    results.mkdir()
    snippet = (f'age() {{ [ "$1" = -R ] && [ "$3" = -o ] && cat >"$4"; }}; '
               f'PADDOCK_ROOT="{root}" publish_logs "{logs}" "{results}" cell')
    result = run_lib(tmp_path / "x", "exit 0", snippet)
    assert result.returncode == 0, result.stderr
    assert (results / "cell.private.tgz.age").stat().st_size > 0
    assert not (results / "logs").exists()
    assert not logs.exists()
