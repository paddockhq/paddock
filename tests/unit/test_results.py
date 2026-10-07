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
    # Even "fail" (a confirmed leak) versus "error" (inconclusive) is withheld:
    # publicly, every withheld must-block result is an error.
    assert result["status"] == "error"
    assert [check["name"] for check in result["checks"]] == ["version:api-key", "deny"]
    assert result["checks"][1]["status"] == "error"
    assert "2606" not in json.dumps(result)
    assert "ipv6" not in json.dumps(result)


def test_passing_must_block_checks_stay_public():
    checks = [
        {"name": "deny-m1-ipv6:api-key", "status": "pass", "detail": ""},
        {"name": "deny-m2-literal-credential:api-key", "status": "skip", "detail": "forwarded unchanged"},
    ]
    assert cell_result("demo", "v0.1.2", "ubuntu-24.04", checks)["checks"] == checks
