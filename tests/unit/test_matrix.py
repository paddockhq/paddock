import json

from paddock.__main__ import main
from paddock.matrix import affected_bundles, build_matrix, parse_version, supports


def test_parse_version():
    assert parse_version("v0.1.2") == (0, 1, 2)
    assert parse_version("v0.0.116") == (0, 0, 116)
    assert parse_version("v1.2.3-rc.1") == (1, 2, 3)


def test_version_order_is_numeric_not_text():
    assert parse_version("v0.0.116") < parse_version("v0.1.0")


def test_no_changed_list_means_every_bundle():
    assert affected_bundles(["b", "a"], None) == ["a", "b"]


def test_bundle_change_selects_only_that_bundle():
    assert affected_bundles(["a", "b"], ["bundles/b/policy.yaml", "README.md"]) == ["b"]


def test_shared_change_selects_every_bundle():
    assert affected_bundles(["a", "b"], ["scripts/ci/run-cell.sh"]) == ["a", "b"]


def test_windows_style_paths_are_understood():
    assert affected_bundles(["a", "b"], ["bundles\\a\\policy.yaml"]) == ["a"]


def test_docs_only_change_selects_nothing():
    assert affected_bundles(["a"], ["docs/notes.md", "bundles/README.md"]) == []


def test_min_version_floor_skips_older_releases():
    meta = {"name": "a", "openshell_min_version": "v0.1.0"}
    assert supports(meta, "v0.1.2")
    assert not supports(meta, "v0.0.116")


def test_matrix_crosses_bundles_versions_and_runners():
    metas = [{"name": "b"}, {"name": "a", "openshell_min_version": "v0.1.0"}]
    cells = build_matrix(metas, ["v0.1.2", "v0.0.116"], ["x", "y"])
    assert cells == [
        {"bundle": "a", "openshell_version": "v0.1.2", "runner": "x"},
        {"bundle": "a", "openshell_version": "v0.1.2", "runner": "y"},
        {"bundle": "b", "openshell_version": "v0.1.2", "runner": "x"},
        {"bundle": "b", "openshell_version": "v0.1.2", "runner": "y"},
        {"bundle": "b", "openshell_version": "v0.0.116", "runner": "x"},
        {"bundle": "b", "openshell_version": "v0.0.116", "runner": "y"},
    ]


def _versions_file(tmp_path):
    path = tmp_path / "versions.json"
    path.write_text('{"versions": ["v0.1.2"]}', encoding="utf-8")
    return path


def test_matrix_command_with_no_bundles_writes_empty_outputs(tmp_path, capsys):
    gh_out = tmp_path / "github_output"
    rc = main([
        "matrix", "--root", str(tmp_path),
        "--versions-file", str(_versions_file(tmp_path)),
        "--github-output", str(gh_out),
    ])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"include": []}
    assert gh_out.read_text(encoding="utf-8") == 'matrix={"include":[]}\nhas_cells=false\n'


def test_matrix_command_uses_changed_files(make_bundle, tmp_path, capsys):
    make_bundle()
    changed = tmp_path / "changed.txt"
    changed.write_text("bundles/demo/policy.yaml\n", encoding="utf-8")
    rc = main([
        "matrix", "--root", str(tmp_path),
        "--versions-file", str(_versions_file(tmp_path)),
        "--changed-files", str(changed),
    ])
    assert rc == 0
    cells = json.loads(capsys.readouterr().out)["include"]
    assert [cell["bundle"] for cell in cells] == ["demo", "demo"]
