from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_screenshot_assets_exist() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    expected_assets = (
        "docs/images/dofus-integration.jpg",
        "docs/images/toolbar-vertical.png",
        "docs/images/settings-window.png",
    )

    for relative_path in expected_assets:
        assert relative_path in readme
        assert (ROOT / relative_path).is_file()

    assert readme.index("## Français") < readme.index("## English")
    assert "## Regression coverage" not in readme


def test_tagged_builds_create_a_release_from_the_executable() -> None:
    workflow = (ROOT / ".github/workflows/windows-build.yml").read_text(
        encoding="utf-8"
    )

    assert 'tags: ["v*"]' in workflow
    assert "needs: test-and-build" in workflow
    assert "gh release create" in workflow
    assert '"release/Dofus-MultiCompte-Enhancer.exe"' in workflow
    assert '"release/Dofus-MultiCompte-Enhancer-Portable.zip"' in workflow
    assert '"release/Dofus-MultiCompte-Enhancer-Setup.exe"' in workflow
    assert '"release/SHA256SUMS.txt"' in workflow
    assert "--verify-tag" in workflow


def test_release_packages_have_checksums_and_github_attestations() -> None:
    workflow = (ROOT / ".github/workflows/windows-build.yml").read_text(
        encoding="utf-8"
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Get-FileHash" in workflow
    assert "SHA256SUMS.txt" in workflow
    assert "uses: actions/attest@v4" in workflow
    assert "id-token: write" in workflow
    assert "attestations: write" in workflow
    assert "artifact-metadata: write" in workflow
    assert "gh attestation verify" in readme


def test_installer_creates_shortcuts_and_an_uninstaller() -> None:
    installer = (ROOT / "installer/Dofus-MultiCompte-Enhancer.iss").read_text(
        encoding="utf-8"
    )

    assert "Uninstallable=yes" in installer
    assert "DefaultDirName={localappdata}\\Programs\\{#MyAppName}" in installer
    assert "{group}\\{#MyAppName}" in installer
    assert "{autodesktop}\\{#MyAppName}" in installer
    assert "{uninstallexe}" in installer
    assert "SignTool=dmce" in installer
    assert "SignedUninstaller=yes" in installer


def test_release_workflow_supports_optional_authenticode_signing() -> None:
    workflow = (ROOT / ".github/workflows/windows-build.yml").read_text(
        encoding="utf-8"
    )

    assert "WINDOWS_CERTIFICATE_BASE64" in workflow
    assert "WINDOWS_CERTIFICATE_PASSWORD" in workflow
    assert "/fd SHA256" in workflow
    assert "/td SHA256" in workflow
    assert "signtool.exe" in workflow.casefold()
    assert "verify /pa /all" in workflow


def test_development_certificate_script_does_not_publish_private_keys() -> None:
    script = ROOT / "scripts/New-DevelopmentCodeSigningCertificate.ps1"
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert script.is_file()
    assert "New-SelfSignedCertificate" in script.read_text(encoding="utf-8")
    assert "certificates/" in gitignore
    assert "*.pfx" in gitignore


def test_character_workflow_has_no_fixed_four_account_requirement() -> None:
    source = (ROOT / "app/dofus_character_login.py").read_text(encoding="utf-8")

    assert "wait_for_exactly_four_windows" not in source
    assert "len(windows) < 4" not in source
    assert '"account_count": len(players)' in source
