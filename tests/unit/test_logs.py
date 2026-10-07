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


# Real OpenShell v0.1.2 lines captured by the M0 run (docs/decisions/0001-ci-runners.md).
DNS_REFUSE = (
    "[1791294561.295] [sandbox] [OCSF ] [ocsf] NET:REFUSE [MED] DENIED example.com "
    "[reason:policy_dns_ineligible]"
)
V012_DENIED = (
    "[1791294561.297] [sandbox] [OCSF ] [ocsf] NET:OPEN [MED] DENIED /usr/bin/curl(0) -> "
    "example.com:443 [reason:transparent_tcp_policy_denied]"
)


def test_parses_real_v012_denial_lines():
    events = parse_events("\n".join([DNS_REFUSE, V012_DENIED]))
    assert [(e.kind, e.action, e.host, e.port, e.binary) for e in events] == [
        ("NET", "DENIED", "example.com", None, None),
        ("NET", "DENIED", "example.com", 443, "/usr/bin/curl"),
    ]


def test_unbracketed_ipv6_is_never_attributed_to_a_partial_host():
    line = "NET:OPEN [MED] DENIED /usr/bin/curl(7) -> 2001:4860:4860::8888:443 [policy:-]"
    events = parse_events(line)
    assert len(events) == 1
    assert events[0].action == "DENIED"
    assert events[0].host not in {"2001", "4860"}


def test_unrecognised_denial_lines_are_kept_as_unparsed_denials():
    lines = [
        "NET:OPEN [MED] DENIED /opt/my app/bin(7) -> evil.example:443 [policy:-]",
        "HTTP:GET [MED] DENIED GET http://[::1:443/x [policy:-]",
        "HTTP:GET [MED] DENIED GET http://evil.example:99999/x [policy:-]",
    ]
    events = parse_events("\n".join(lines))
    assert [(e.action, e.host) for e in events] == [("DENIED", "<unparsed>")] * 3
    assert select(events, action="DENIED")


def test_unrecognised_allowed_lines_are_ignored():
    assert parse_events("NET:OPEN [INFO] ALLOWED weird line without arrow") == []


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
