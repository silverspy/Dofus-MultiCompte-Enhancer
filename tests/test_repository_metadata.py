from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_screenshot_assets_exist() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    expected_assets = (
        "docs/images/toolbar-vertical.png",
        "docs/images/settings-window.png",
    )

    for relative_path in expected_assets:
        assert relative_path in readme
        assert (ROOT / relative_path).is_file()


def test_tagged_builds_create_a_release_from_the_executable() -> None:
    workflow = (ROOT / ".github/workflows/windows-build.yml").read_text(
        encoding="utf-8"
    )

    assert 'tags: ["v*"]' in workflow
    assert "needs: test-and-build" in workflow
    assert "gh release create" in workflow
    assert '"release/Dofus-MultiCompte-Enhancer.exe"' in workflow
    assert "--verify-tag" in workflow
