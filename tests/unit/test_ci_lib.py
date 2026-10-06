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
