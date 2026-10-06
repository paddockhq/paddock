import copy

import pytest
import yaml

VALID_META = {
    "schema": 1,
    "name": "demo",
    "agent": {
        "display_name": "Demo Agent",
        "homepage": "https://example.com/demo",
        "license": "MIT",
        "version": "1.2.3",
    },
    "distribution": "upstream",
    "image": "ghcr.io/example/demo:1.2.3@sha256:" + "a" * 64,
    "revision": 1,
    "command": ["demo"],
    "version_command": ["demo", "--version"],
    "env": {"DEMO_DISABLE_UPDATES": "1"},
    "auth": [{"mode": "api-key", "provider_file": "providers/demo-apikey.yaml"}],
}

DEFAULT_FILES = {
    "policy.yaml": "version: 1\n",
    "boundary.yaml": "version: 1\n",
    "providers/demo-apikey.yaml": "id: demo-apikey\n",
    "tests/allow.sh": "#!/usr/bin/env bash\n",
    "README.md": "# demo\n",
}


@pytest.fixture
def valid_meta():
    return copy.deepcopy(VALID_META)


@pytest.fixture
def make_bundle(tmp_path):
    """Write tmp_path/bundles/<name>/ and return its path.

    files maps relative paths to content; a value of None means "do not create".
    Files are written with newline="" so Windows does not turn LF into CRLF.
    """

    def _make(meta=None, files=None, name=None):
        meta = copy.deepcopy(VALID_META if meta is None else meta)
        bundle_dir = tmp_path / "bundles" / (name or meta.get("name", "demo"))
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "bundle.yaml").write_text(
            yaml.safe_dump(meta, sort_keys=False), encoding="utf-8", newline=""
        )
        contents = dict(DEFAULT_FILES)
        if meta.get("distribution") in ("built", "dockerfile-only"):
            contents["Dockerfile"] = "FROM scratch\n"
        contents.update(files or {})
        for rel, content in contents.items():
            if content is None:
                continue
            path = bundle_dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="")
        return bundle_dir

    return _make
