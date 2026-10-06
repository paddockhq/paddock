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
