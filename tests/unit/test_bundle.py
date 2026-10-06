import copy

import pytest

from paddock.__main__ import main
from paddock.bundle import (
    BundleError,
    discover_bundles,
    load_bundle,
    provider_info,
    shell_assignments,
)


def test_valid_upstream_bundle_loads(make_bundle):
    bundle_dir = make_bundle()
    meta = load_bundle(bundle_dir)
    assert meta["name"] == "demo"
    assert meta["dir"] == bundle_dir


def test_missing_required_field_is_reported(make_bundle, valid_meta):
    del valid_meta["image"]
    with pytest.raises(BundleError, match="'image' is a required property"):
        load_bundle(make_bundle(valid_meta))


def test_unknown_field_is_rejected(make_bundle, valid_meta):
    valid_meta["imagee"] = "typo"
    with pytest.raises(BundleError, match="Additional properties are not allowed"):
        load_bundle(make_bundle(valid_meta))


def test_env_names_cannot_use_the_openshell_prefix(make_bundle, valid_meta):
    valid_meta["env"] = {"OPENSHELL_GATEWAY": "x"}
    with pytest.raises(BundleError, match="OPENSHELL_GATEWAY"):
        load_bundle(make_bundle(valid_meta))


def test_name_must_match_folder(make_bundle, valid_meta):
    with pytest.raises(BundleError, match="does not match folder 'other'"):
        load_bundle(make_bundle(valid_meta, name="other"))


def test_upstream_image_needs_a_digest(make_bundle, valid_meta):
    valid_meta["image"] = "ghcr.io/example/demo:1.2.3"
    with pytest.raises(BundleError, match="pinned by digest"):
        load_bundle(make_bundle(valid_meta))


def test_built_image_is_a_bare_repository(make_bundle, valid_meta):
    valid_meta["distribution"] = "built"
    valid_meta["image"] = "ghcr.io/paddockhq/demo:1.0"
    with pytest.raises(BundleError, match="without a tag or digest"):
        load_bundle(make_bundle(valid_meta))


def test_built_bundle_needs_a_dockerfile(make_bundle, valid_meta):
    valid_meta["distribution"] = "built"
    valid_meta["image"] = "ghcr.io/paddockhq/demo"
    with pytest.raises(BundleError, match="need a Dockerfile"):
        load_bundle(make_bundle(valid_meta, files={"Dockerfile": None}))


def test_upstream_bundle_must_not_have_a_dockerfile(make_bundle):
    with pytest.raises(BundleError, match="must not contain a Dockerfile"):
        load_bundle(make_bundle(files={"Dockerfile": "FROM scratch\n"}))


def test_missing_provider_file_is_named(make_bundle):
    with pytest.raises(BundleError, match="missing provider file providers/demo-apikey.yaml"):
        load_bundle(make_bundle(files={"providers/demo-apikey.yaml": None}))


@pytest.mark.parametrize("rel", ["policy.yaml", "boundary.yaml", "tests/allow.sh", "README.md"])
def test_required_files_are_checked(make_bundle, rel):
    with pytest.raises(BundleError, match=f"missing required file {rel}"):
        load_bundle(make_bundle(files={rel: None}))


def test_auth_modes_must_be_unique(make_bundle, valid_meta):
    valid_meta["auth"].append(copy.deepcopy(valid_meta["auth"][0]))
    with pytest.raises(BundleError, match="auth modes must be unique"):
        load_bundle(make_bundle(valid_meta))


def test_crlf_line_endings_are_rejected(make_bundle):
    bundle_dir = make_bundle(files={"tests/allow.sh": "#!/usr/bin/env bash\r\necho hi\r\n"})
    with pytest.raises(BundleError, match="CRLF line endings in tests/allow.sh"):
        load_bundle(bundle_dir)


def test_every_problem_is_listed(make_bundle):
    with pytest.raises(BundleError) as exc:
        load_bundle(make_bundle(files={"policy.yaml": None, "boundary.yaml": None}))
    assert "policy.yaml" in str(exc.value)
    assert "boundary.yaml" in str(exc.value)


def test_discover_bundles_is_sorted_and_skips_other_folders(make_bundle, valid_meta, tmp_path):
    for name in ("zeta", "alpha"):
        meta = copy.deepcopy(valid_meta)
        meta["name"] = name
        make_bundle(meta)
    (tmp_path / "bundles" / "notes").mkdir()
    assert discover_bundles(tmp_path / "bundles") == ["alpha", "zeta"]


def test_discover_bundles_without_a_bundles_folder(tmp_path):
    assert discover_bundles(tmp_path / "bundles") == []


def test_provider_info_reads_id_and_first_env_var(tmp_path):
    profile = tmp_path / "p.yaml"
    profile.write_text(
        "id: demo-apikey\n"
        "credentials:\n"
        "  - name: api_key\n"
        "    env_vars: [DEMO_API_KEY, DEMO_KEY]\n",
        encoding="utf-8",
    )
    assert provider_info(profile) == {"id": "demo-apikey", "credential_envs": ["DEMO_API_KEY"]}


def test_shell_assignments_quote_values(valid_meta):
    valid_meta["env"] = {"B_FLAG": "1", "A_PATH": "/sandbox/my dir"}
    out = shell_assignments(valid_meta)
    assert "PADDOCK_NAME=demo\n" in out
    assert "PADDOCK_OPENSHELL_MIN_VERSION=''\n" in out
    assert "PADDOCK_VERSION_COMMAND=(demo --version)\n" in out
    assert "PADDOCK_ENV_ARGS=(--env 'A_PATH=/sandbox/my dir' --env B_FLAG=1)\n" in out
    assert "PADDOCK_AUTH_MODES=(api-key)\n" in out
    assert "PADDOCK_PROVIDER_FILES=(providers/demo-apikey.yaml)\n" in out


def test_validate_command_reports_failures(make_bundle, tmp_path, capsys):
    make_bundle(files={"policy.yaml": None})
    assert main(["validate", "--root", str(tmp_path)]) == 1
    assert "missing required file policy.yaml" in capsys.readouterr().err


def test_validate_command_passes_valid_bundles(make_bundle, tmp_path, capsys):
    make_bundle()
    assert main(["validate", "--root", str(tmp_path)]) == 0
    assert "ok: demo" in capsys.readouterr().out


def test_validate_command_without_bundles(tmp_path, capsys):
    assert main(["validate", "--root", str(tmp_path)]) == 0
    assert "no bundles found" in capsys.readouterr().out


@pytest.mark.parametrize("policy", [
    "version: 1\nlandlock:\n  compatibility: best_effort\n",
    "version: 1\n",
])
def test_landlock_must_be_a_hard_requirement(make_bundle, policy):
    # best_effort lets a sandbox start with filesystem rules silently skipped.
    with pytest.raises(BundleError, match="policy.yaml: landlock.compatibility must be hard_requirement"):
        load_bundle(make_bundle(files={"policy.yaml": policy}))


def test_dummy_credential_is_exported_per_auth_mode(valid_meta):
    # Some upstreams answer a badly shaped key as if no key were sent, so a bundle
    # can give CI a fake key in the provider's own format.
    valid_meta["auth"] = [
        {"mode": "api-key", "provider_file": "providers/demo-apikey.yaml", "dummy_credential": "sk-demo-{0*4}x"},
        {"mode": "subscription", "provider_file": "providers/demo-sub.yaml"},
    ]
    out = shell_assignments(valid_meta)
    # {c*N} repeats c N times, so no key-shaped string has to be committed.
    assert "PADDOCK_DUMMY_CREDENTIALS=(sk-demo-0000x paddock-ci-dummy-credential)\n" in out


def test_dummy_credential_rejects_shell_and_space_characters(make_bundle, valid_meta):
    valid_meta["auth"][0]["dummy_credential"] = "sk $(id)"
    with pytest.raises(BundleError, match="dummy_credential"):
        load_bundle(make_bundle(valid_meta))
