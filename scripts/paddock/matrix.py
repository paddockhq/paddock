"""Compute the CI matrix: bundle x OpenShell version x runner."""

import json
import sys
from pathlib import Path

from paddock import bundle

RUNNERS = ("ubuntu-24.04", "ubuntu-24.04-arm")
# A change under any of these paths can affect every bundle.
SHARED_PATHS = ("scripts/", "tests/deny/", ".github/workflows/", "requirements-dev.txt")


def parse_version(tag):
    """'v0.1.2' -> (0, 1, 2). Pre-release suffixes are ignored."""
    core = tag.removeprefix("v").split("-", 1)[0]
    major, minor, patch = (int(part) for part in core.split("."))
    return major, minor, patch


def load_versions(path):
    versions = json.loads(Path(path).read_text(encoding="utf-8"))["versions"]
    if not versions:
        raise ValueError(f"{path}: the versions list is empty")
    return versions


def affected_bundles(names, changed_files):
    """Bundles to test. None or an empty list (a failed diff) means every bundle."""
    names = sorted(names)
    if not changed_files:
        return names
    hit = set()
    for path in changed_files:
        path = path.replace("\\", "/")
        if path.startswith(SHARED_PATHS):
            return names
        parts = path.split("/")
        if len(parts) > 2 and parts[0] == "bundles" and parts[1] in names:
            hit.add(parts[1])
    return sorted(hit)


def supports(meta, version):
    floor = meta.get("openshell_min_version")
    return floor is None or parse_version(version) >= parse_version(floor)


def build_matrix(metas, versions, runners=RUNNERS):
    return [
        {"bundle": meta["name"], "openshell_version": version, "runner": runner}
        for meta in sorted(metas, key=lambda m: m["name"])
        for version in versions
        if supports(meta, version)
        for runner in runners
    ]


def _cmd_matrix(args):
    root = Path(args.root)
    names = bundle.discover_bundles(root / "bundles")
    try:
        metas = {name: bundle.load_bundle(root / "bundles" / name) for name in names}
    except bundle.BundleError as err:
        print(err, file=sys.stderr)
        return 1
    changed = None
    if args.changed_files:
        lines = Path(args.changed_files).read_text(encoding="utf-8").splitlines()
        changed = [line.strip() for line in lines if line.strip()]
    selected = affected_bundles(names, changed)
    cells = build_matrix([metas[name] for name in selected], load_versions(args.versions_file))
    payload = json.dumps({"include": cells}, separators=(",", ":"))
    print(payload)
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as out:
            out.write(f"matrix={payload}\n")
            out.write(f"has_cells={'true' if cells else 'false'}\n")
    return 0


def add_commands(sub):
    cmd = sub.add_parser("matrix", help="print the CI matrix as JSON")
    cmd.add_argument("--root", default=".", help="repository root that contains bundles/")
    cmd.add_argument("--versions-file", default="scripts/ci/openshell-versions.json")
    cmd.add_argument("--changed-files", help="file listing changed paths, one per line (omit to test every bundle)")
    cmd.add_argument("--github-output", help="append matrix= and has_cells= lines to this file")
    cmd.set_defaults(handler=_cmd_matrix)
