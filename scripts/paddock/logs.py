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
_DENIAL = re.compile(r"\b(?P<kind>NET|HTTP):[A-Z]+ \[[A-Z]+\] (?P<action>DENIED|BLOCKED)\b")
UNPARSED = "<unparsed>"


@dataclass(frozen=True)
class Event:
    kind: str
    action: str
    host: str
    port: int | None
    binary: str | None
    method: str | None
    line: str


def _http_event(match, line):
    try:
        url = urlsplit(match["url"])
        port = url.port
    except ValueError:
        return None
    if not url.hostname:
        return None
    return Event("HTTP", match["action"], url.hostname, port, None, match["method"], line)


def parse_events(text):
    events = []
    for line in text.splitlines():
        event = None
        if match := _NET.search(line):
            event = Event(
                "NET", match["action"], match["host"].strip("[]"), int(match["port"]),
                match["binary"], None, line,
            )
        elif match := _NET_HOST.search(line):
            event = Event("NET", match["action"], match["host"].strip("[]"), None, None, None, line)
        elif match := _HTTP.search(line):
            event = _http_event(match, line)
        if event is None and (match := _DENIAL.search(line)):
            event = Event(match["kind"], match["action"], UNPARSED, None, None, None, line)
        if event is not None:
            events.append(event)
    return events


def select(events, action=None, host=None):
    return [e for e in events if (action is None or e.action == action) and (host is None or e.host == host)]


def _cmd_events(args):
    events = select(parse_events(Path(args.log).read_text(encoding="utf-8", errors="replace")), args.action, args.host)
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
    cmd.add_argument("--format", choices=["lines", "count", "hosts"], default="lines")
    cmd.set_defaults(handler=_cmd_events)
