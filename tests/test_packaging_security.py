from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SPEC_FILES = (
    REPOSITORY_ROOT / "Dofus-MultiCompte-Enhancer.spec",
    REPOSITORY_ROOT / "Dofus-MultiCompte-Enhancer-Onedir.spec",
)


def test_pyinstaller_builds_do_not_use_executable_packing() -> None:
    for spec_file in SPEC_FILES:
        content = spec_file.read_text(encoding="utf-8")
        assert "upx=True" not in content, f"UPX is enabled in {spec_file.name}"
        assert "upx=False" in content, f"UPX is not explicitly disabled in {spec_file.name}"


def test_windows_build_scans_both_application_editions() -> None:
    workflow = (REPOSITORY_ROOT / ".github/workflows/windows-build.yml").read_text(
        encoding="utf-8"
    )
    assert "Scan application executables with Microsoft Defender" in workflow
    assert "dist/Dofus-MultiCompte-Enhancer.exe" in workflow
    assert (
        "dist-installed/Dofus-MultiCompte-Enhancer/"
        "Dofus-MultiCompte-Enhancer.exe"
    ) in workflow
    assert "-DisableRemediation" in workflow
