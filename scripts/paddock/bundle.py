"""Load and validate PadDock bundles (bundles/<name>/bundle.yaml)."""

import json
import re
import shlex
import sys
from pathlib import Path

import jsonschema
import yaml

SCHEMA_PATH = Path(__file__).with_name("bundle.schema.json")
DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}$")
REQUIRED_FILES = ("policy.yaml", "boundary.yaml", "tests/allow.sh", "README.md")
LF_ONLY_SUFFIXES = (".sh", ".yaml", ".yml")
# Credential value CI gives the provider when it runs without real keys.
DEFAULT_DUMMY_CREDENTIAL = "paddock-ci-dummy-credential"
# In dummy_credential, {c*N} stands for N copies of c, so a fake key in a
# provider's real format never has to be committed (push protection flags it).
REPEAT_RE = re.compile(r"\{([A-Za-z0-9])\*([0-9]{1,3})\}")


def dummy_credential(entry):
    template = entry.get("dummy_credential", DEFAULT_DUMMY_CREDENTIAL)
    return REPEAT_RE.sub(lambda m: m[1] * int(m[2]), template)


class BundleError(Exception):
    """A bundle is invalid. The message lists every problem found."""


def load_bundle(bundle_dir):
    bundle_dir = Path(bundle_dir)
    meta_path = bundle_dir / "bundle.yaml"
    if not meta_path.is_file():
        raise BundleError(f"{bundle_dir}: bundle.yaml not found")
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = jsonschema.Draft202012Validator(schema).iter_errors(meta)
    problems = [
        f"{'.'.join(str(part) for part in error.absolute_path) or 'bundle.yaml'}: {error.message}"
        for error in sorted(errors, key=lambda e: [str(part) for part in e.absolute_path])
    ]
    if not problems:
        problems = _check_files(bundle_dir, meta)
    problems += _crlf_problems(bundle_dir)
    if problems:
        raise BundleError(f"{bundle_dir}:\n  " + "\n  ".join(problems))
    return {**meta, "dir": bundle_dir}


def _check_files(bundle_dir, meta):
    problems = []
    if meta["name"] != bundle_dir.name:
        problems.append(f"name '{meta['name']}' does not match folder '{bundle_dir.name}'")
    for rel in REQUIRED_FILES:
        if not (bundle_dir / rel).is_file():
            problems.append(f"missing required file {rel}")
    has_dockerfile = (bundle_dir / "Dockerfile").is_file()
    if meta["distribution"] == "upstream":
        if has_dockerfile:
            problems.append("upstream bundles must not contain a Dockerfile")
        if not DIGEST_RE.search(meta["image"]):
            problems.append("upstream image must be pinned by digest (@sha256:<64 hex digits>)")
    else:
        if not has_dockerfile:
            problems.append(f"{meta['distribution']} bundles need a Dockerfile")
        if "@" in meta["image"] or ":" in meta["image"].rsplit("/", 1)[-1]:
            problems.append("built and dockerfile-only images must be a repository without a tag or digest")
    modes = [entry["mode"] for entry in meta["auth"]]
    if len(modes) != len(set(modes)):
        problems.append("auth modes must be unique")
    for entry in meta["auth"]:
        if not (bundle_dir / entry["provider_file"]).is_file():
            problems.append(f"missing provider file {entry['provider_file']}")
    for rel in ("policy.yaml", "boundary.yaml"):
        path = bundle_dir / rel
        if path.is_file():
            policy = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if (policy.get("landlock") or {}).get("compatibility") != "hard_requirement":
                # best_effort lets a sandbox start with filesystem rules silently skipped.
                problems.append(f"{rel}: landlock.compatibility must be hard_requirement")
    return problems


def _crlf_problems(bundle_dir):
    problems = []
    for path in sorted(bundle_dir.rglob("*")):
        if path.is_file() and (path.suffix in LF_ONLY_SUFFIXES or path.name == "Dockerfile"):
            if b"\r\n" in path.read_bytes():
                rel = path.relative_to(bundle_dir).as_posix()
                problems.append(f"CRLF line endings in {rel} (convert the file to LF)")
    return problems


def discover_bundles(bundles_root):
    root = Path(bundles_root)
    if not root.is_dir():
        return []
    return sorted(path.name for path in root.iterdir() if (path / "bundle.yaml").is_file())


def provider_info(path):
    profile = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    envs = [cred["env_vars"][0] for cred in profile.get("credentials", []) if cred.get("env_vars")]
    return {"id": profile["id"], "credential_envs": envs}


def shell_assignments(meta):
    def array(name, values):
        return f"{name}=(" + " ".join(shlex.quote(value) for value in values) + ")"

    env_args = [part for key, value in sorted(meta.get("env", {}).items()) for part in ("--env", f"{key}={value}")]
    lines = [
        f"PADDOCK_NAME={shlex.quote(meta['name'])}",
        f"PADDOCK_IMAGE={shlex.quote(meta['image'])}",
        f"PADDOCK_DISTRIBUTION={shlex.quote(meta['distribution'])}",
        f"PADDOCK_OPENSHELL_MIN_VERSION={shlex.quote(meta.get('openshell_min_version', ''))}",
        array("PADDOCK_COMMAND", meta["command"]),
        array("PADDOCK_VERSION_COMMAND", meta["version_command"]),
        array("PADDOCK_ENV_ARGS", env_args),
        array("PADDOCK_AUTH_MODES", [entry["mode"] for entry in meta["auth"]]),
        array("PADDOCK_PROVIDER_FILES", [entry["provider_file"] for entry in meta["auth"]]),
        array("PADDOCK_DUMMY_CREDENTIALS", [dummy_credential(entry) for entry in meta["auth"]]),
    ]
    return "\n".join(lines) + "\n"


def _cmd_validate(args):
    root = Path(args.root)
    names = args.names or discover_bundles(root / "bundles")
    if not names:
        print("no bundles found")
        return 0
    failed = False
    for name in names:
        try:
            load_bundle(root / "bundles" / name)
        except BundleError as err:
            failed = True
            print(err, file=sys.stderr)
        else:
            print(f"ok: {name}")
    return 1 if failed else 0


def _cmd_bundle_env(args):
    sys.stdout.write(shell_assignments(load_bundle(args.bundle_dir)))
    return 0


def _cmd_provider_info(args):
    info = provider_info(args.provider_file)
    envs = " ".join(shlex.quote(env) for env in info["credential_envs"])
    print(f"PROFILE_ID={shlex.quote(info['id'])}")
    print(f"PROFILE_CREDENTIAL_ENVS=({envs})")
    return 0


def add_commands(sub):
    cmd = sub.add_parser("validate", help="validate bundle folders")
    cmd.add_argument("--root", default=".", help="repository root that contains bundles/")
    cmd.add_argument("names", nargs="*", help="bundle names (default: every bundle)")
    cmd.set_defaults(handler=_cmd_validate)

    cmd = sub.add_parser("bundle-env", help="print bundle.yaml as bash assignments")
    cmd.add_argument("bundle_dir")
    cmd.set_defaults(handler=_cmd_bundle_env)

    cmd = sub.add_parser("provider-info", help="print a provider profile's id and credential env vars for bash")
    cmd.add_argument("provider_file")
    cmd.set_defaults(handler=_cmd_provider_info)
