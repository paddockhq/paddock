"""Plan must-block probe requests from a provider profile (run mode 2 and the findings job)."""

import copy
import re
from pathlib import Path

import yaml

# Where CI uploads the static curl probe inside a sandbox.
PROBE_PATH = "/sandbox/.paddock/curl"
# OpenShell access presets (docs/how-it-works/policies/schema.mdx).
ACCESS_METHODS = {
    "read-only": {"GET", "HEAD", "OPTIONS"},
    "read-write": {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH"},
    "full": None,  # every method
}
METHOD_CANDIDATES = ("DELETE", "PUT", "PATCH", "POST", "GET")
PATH_CANDIDATES = ("GET", "POST")
GLOB = re.compile(r"\*\*?")


def _glob_regex(pattern):
    parts = re.split(r"(\*\*|\*)", pattern)
    body = "".join(".*" if p == "**" else "[^/]*" if p == "*" else re.escape(p) for p in parts)
    return re.compile(f"^{body}$")


def rule_allows(endpoint, method, path):
    """Whether an endpoint's L7 allow rules (or access preset) permit a request."""
    rules = endpoint.get("rules")
    if rules:
        for rule in rules:
            allow = rule.get("allow", {})
            if allow.get("method", "*") in ("*", method) and _glob_regex(allow.get("path", "**")).match(path):
                return True
        return False
    methods = ACCESS_METHODS.get(endpoint.get("access", "read-only"), set())
    return methods is None or method in methods


def _url(endpoint, path):
    port = endpoint.get("port", 443)
    authority = endpoint["host"] if port == 443 else f"{endpoint['host']}:{port}"
    return f"https://{authority}{path}"


def _control(endpoint):
    for rule in endpoint.get("rules") or []:
        allow = rule.get("allow", {})
        if allow.get("method", "*") != "*":
            path = GLOB.sub("pd", allow.get("path", "/"))
            return allow["method"], path if path.startswith("/") else f"/{path}"
    return "GET", "/"


def probe_requests(profile, nonce):
    """(kind, method, url) for each L7-inspected endpoint: one allowed control request,
    then one disallowed method on the allowed path and one disallowed path, when the
    profile's own rules leave such requests disallowed."""
    plan = []
    for endpoint in profile.get("endpoints") or []:
        if endpoint.get("protocol") != "rest" or "*" in endpoint["host"]:
            continue
        method, path = _control(endpoint)
        plan.append(("control", method, _url(endpoint, path)))
        for candidate in METHOD_CANDIDATES:
            if candidate != method and not rule_allows(endpoint, candidate, path):
                plan.append(("l7-method", candidate, _url(endpoint, path)))
                break
        for candidate in PATH_CANDIDATES:
            if not rule_allows(endpoint, candidate, f"/pd-{nonce}"):
                plan.append(("l7-path", candidate, _url(endpoint, f"/pd-{nonce}")))
                break
    return plan


def literal_header(profile):
    """(header name, value prefix) a client uses to send this profile's key, or None."""
    for credential in profile.get("credentials") or []:
        if credential.get("auth_style") == "bearer":
            return ("Authorization", "Bearer ")
        if credential.get("auth_style") == "header" and credential.get("header_name"):
            return (credential["header_name"], "")
    return None


def variant_profile(profile, probe_path):
    """Run mode 2: the same profile with the probe listed in place of the agent."""
    variant = copy.deepcopy(profile)
    variant["id"] = f"{profile['id']}-probe"
    variant["binaries"] = [probe_path]
    return variant


def probe_binary(profile):
    """A concrete path that matches the profile's first listed binary (globs filled in)."""
    for binary in profile.get("binaries") or []:
        return GLOB.sub("paddock-probe", binary)
    return None


def _load(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _cmd_variant_profile(args):
    variant = variant_profile(_load(args.provider_file), args.binary)
    Path(args.out).write_text(yaml.safe_dump(variant, sort_keys=False), encoding="utf-8")
    print(f"VARIANT_PROFILE_ID={variant['id']}")
    return 0


def _cmd_probe_plan(args):
    profile = _load(args.provider_file)
    for kind, method, url in probe_requests(profile, args.nonce):
        print(f"{kind}\t{method}\t{url}")
    seen = set()
    for endpoint in profile.get("endpoints") or []:
        key = (endpoint["host"], endpoint.get("port", 443))
        if key not in seen:
            seen.add(key)
            print(f"endpoint\t{key[0]}\t{key[1]}\t{endpoint.get('protocol', '-')}")
    header = literal_header(profile)
    if header:
        print(f"literal\t{header[0]}\t{header[1]}")
    return 0


def _cmd_probe_binary(args):
    binary = probe_binary(_load(args.provider_file))
    if binary:
        print(binary)
    return 0


def add_commands(sub):
    cmd = sub.add_parser("variant-profile", help="write the run-mode-2 copy of a provider profile")
    cmd.add_argument("provider_file")
    cmd.add_argument("--out", required=True)
    cmd.add_argument("--binary", default=PROBE_PATH)
    cmd.set_defaults(handler=_cmd_variant_profile)

    cmd = sub.add_parser("probe-plan", help="print the probe requests and endpoints for a provider profile")
    cmd.add_argument("provider_file")
    cmd.add_argument("--nonce", required=True)
    cmd.set_defaults(handler=_cmd_probe_plan)

    cmd = sub.add_parser("probe-binary", help="print a concrete path matching a profile's first binary")
    cmd.add_argument("provider_file")
    cmd.set_defaults(handler=_cmd_probe_binary)
