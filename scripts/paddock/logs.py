"""Read OpenShell policy events (OCSF shorthand) from `openshell logs` output."""

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

_NET = re.compile(
    r"\bNET:(?P<op>[A-Z]+) \[[A-Z]+\] (?P<action>ALLOWED|DENIED|BLOCKED) "
    r"(?P<binary>\S+?)\((?P<pid>\d+)\) -> (?P<host>\[[^\]]+\]|[^\s:/]+):(?P<port>\d+)"
)
_HTTP = re.compile(
    r"\bHTTP:(?P<method>[A-Z]+) \[[A-Z]+\] (?P<action>ALLOWED|DENIED|BLOCKED) (?P=method) (?P<url>\S+)"
)


@dataclass(frozen=True)
class Event:
    kind: str
    action: str
    host: str
    port: int | None
    binary: str | None
    method: str | None
    line: str


def parse_events(text):
    events = []
    for line in text.splitlines():
        if match := _NET.search(line):
            events.append(Event(
                "NET", match["action"], match["host"].strip("[]"), int(match["port"]),
                match["binary"], None, line,
            ))
        elif match := _HTTP.search(line):
            url = urlsplit(match["url"])
            events.append(Event("HTTP", match["action"], url.hostname or "", url.port, None, match["method"], line))
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
