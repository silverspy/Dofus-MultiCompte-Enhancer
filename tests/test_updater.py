from __future__ import annotations

from pathlib import Path

import updater


def release_with_assets(version: str = "1.2.0") -> updater.ReleaseInfo:
    return updater.ReleaseInfo(
        version=version,
        page_url="https://example.invalid/release",
        assets=(
            updater.ReleaseAsset(updater.SETUP_ASSET, "https://example.invalid/setup", 10),
            updater.ReleaseAsset(updater.PORTABLE_ASSET, "https://example.invalid/portable", 20),
        ),
    )


def test_semantic_versions_are_compared_numerically() -> None:
    assert updater.version_tuple("v1.10.2") > updater.version_tuple("1.9.9")
    assert updater.is_newer_release("1.1.9", release_with_assets("1.2.0")) is True
    assert updater.is_newer_release("1.2.0", release_with_assets("1.2.0")) is False


def test_update_asset_matches_distribution_mode() -> None:
    release = release_with_assets()

    assert updater.select_update_asset(release, installed=True).name == updater.SETUP_ASSET
    assert updater.select_update_asset(release, installed=False).name == updater.PORTABLE_ASSET


def test_distribution_mode_recognizes_installer_and_onedir_layouts(tmp_path: Path) -> None:
    portable_directory = tmp_path / "portable"
    portable_directory.mkdir()
    portable_executable = portable_directory / "app.exe"
    portable_executable.touch()

    installed_directory = tmp_path / "installed"
    installed_directory.mkdir()
    installed_executable = installed_directory / "app.exe"
    installed_executable.touch()
    (installed_directory / "unins000.exe").touch()

    onedir_directory = tmp_path / "onedir"
    onedir_directory.mkdir()
    onedir_executable = onedir_directory / "app.exe"
    onedir_executable.touch()
    (onedir_directory / "_internal").mkdir()

    assert updater.is_installed(portable_executable) is False
    assert updater.is_installed(installed_executable) is True
    assert updater.is_installed(onedir_executable) is True


def test_distribution_mode_recognizes_transparent_installed_runtime(tmp_path: Path) -> None:
    executable = tmp_path / "runtime" / "pythonw.exe"
    executable.parent.mkdir()
    executable.touch()
    (tmp_path / "installed.marker").touch()

    assert updater.is_installed(executable) is True


def test_update_environment_removes_inherited_pyinstaller_state() -> None:
    environment = {
        "PATH": "C:/Windows",
        "__PYI_APPLICATION_HOME_DIR": "old-bundle",
        "_PYI_ARCHIVE_FILE": "old.exe",
        "_PYI_PARENT_PROCESS_LEVEL": "1",
        "_MEIPASS2": "legacy-bundle",
        "PYINSTALLER_RESET_ENVIRONMENT": "0",
    }

    cleaned = updater.update_subprocess_environment(environment)

    assert cleaned == {
        "PATH": "C:/Windows",
        "PYINSTALLER_RESET_ENVIRONMENT": "1",
    }


def test_installed_update_launches_setup_with_clean_environment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "installed" / "app.exe"
    executable.parent.mkdir()
    executable.touch()
    (executable.parent / "_internal").mkdir()
    setup = tmp_path / updater.SETUP_ASSET
    setup.touch()
    launches: list[tuple[list[str], dict[str, object]]] = []

    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(updater, "download_asset", lambda _asset, _destination: setup)
    monkeypatch.setattr(
        updater.subprocess,
        "Popen",
        lambda command, **kwargs: launches.append((command, kwargs)),
    )
    monkeypatch.setattr(
        updater.os,
        "environ",
        {"PATH": "C:/Windows", "__PYI_APPLICATION_HOME_DIR": "stale"},
    )

    updater.launch_update(release_with_assets(), executable=executable)

    command, options = launches[0]
    assert command[0] == str(setup)
    assert "/CLOSEAPPLICATIONS" in command
    assert "/RESTARTAPPLICATIONS" not in command
    assert options["env"] == {
        "PATH": "C:/Windows",
        "PYINSTALLER_RESET_ENVIRONMENT": "1",
    }


def test_portable_update_launches_powershell_with_clean_environment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "portable" / "app.exe"
    executable.parent.mkdir()
    executable.touch()
    package = tmp_path / updater.PORTABLE_ASSET
    package.touch()
    launches: list[tuple[list[str], dict[str, object]]] = []

    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(updater, "download_asset", lambda _asset, _destination: package)
    monkeypatch.setattr(
        updater.subprocess,
        "Popen",
        lambda command, **kwargs: launches.append((command, kwargs)),
    )
    monkeypatch.setattr(
        updater.os,
        "environ",
        {"PATH": "C:/Windows", "_PYI_PARENT_PROCESS_LEVEL": "1"},
    )

    updater.launch_update(release_with_assets(), executable=executable)

    command, options = launches[0]
    assert command[0] == "powershell.exe"
    assert options["env"] == {
        "PATH": "C:/Windows",
        "PYINSTALLER_RESET_ENVIRONMENT": "1",
    }


def test_portable_update_replaces_the_executable_without_an_archive(tmp_path: Path) -> None:
    script_path = tmp_path / "portable-update.ps1"

    updater._write_portable_update_script(script_path)
    script = script_path.read_text(encoding="utf-8-sig")

    assert "[string]$Package" in script
    assert "Copy-Item -LiteralPath $Package" in script
    assert "Expand-Archive" not in script
