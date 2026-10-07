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
