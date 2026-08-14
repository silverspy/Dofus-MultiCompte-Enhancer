"""GitHub Release update discovery and installation helpers."""

from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tempfile
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path


REPOSITORY = "silverspy/Dofus-MultiCompte-Enhancer"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
SETUP_ASSET = "Dofus-MultiCompte-Enhancer-Setup.exe"
PORTABLE_ASSET = "Dofus-MultiCompte-Enhancer-Portable.exe"


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int
    digest: str = ""


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    page_url: str
    assets: tuple[ReleaseAsset, ...]


def version_tuple(value: str) -> tuple[int, int, int]:
    """Convert a semantic release tag into a comparable numeric tuple."""
    clean = value.strip().lower().removeprefix("v").split("+", 1)[0]
    clean = clean.split("-", 1)[0]
    parts = clean.split(".")
    numbers: list[int] = []
    for part in parts[:3]:
        digits = "".join(character for character in part if character.isdigit())
        numbers.append(int(digits or 0))
    return tuple((numbers + [0, 0, 0])[:3])


def fetch_latest_release(timeout: float = 8.0) -> ReleaseInfo:
    """Read the latest published, non-prerelease release from GitHub."""
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Dofus-MultiCompte-Enhancer",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    assets = tuple(
        ReleaseAsset(
            name=str(item["name"]),
            download_url=str(item["browser_download_url"]),
            size=int(item.get("size", 0)),
            digest=str(item.get("digest", "")),
        )
        for item in payload.get("assets", [])
        if item.get("name") and item.get("browser_download_url")
    )
    return ReleaseInfo(
        version=str(payload["tag_name"]).removeprefix("v"),
        page_url=str(payload["html_url"]),
        assets=assets,
    )


def is_newer_release(current_version: str, release: ReleaseInfo) -> bool:
    return version_tuple(release.version) > version_tuple(current_version)


def is_installed(executable: Path | None = None) -> bool:
    target = executable or Path(sys.executable)
    application_directory = target.resolve().parent
    return (
        (application_directory / "unins000.exe").is_file()
        or (application_directory / "_internal").is_dir()
        or (application_directory.parent / "installed.marker").is_file()
    )


def update_subprocess_environment(
    environment: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return an environment safe for starting another frozen application.

    PyInstaller's private variables describe the currently running bundle. If
    PowerShell or Inno Setup inherits them and then starts the new executable,
    its bootloader can mistake itself for a child of the old bundle.
    """
    source = os.environ if environment is None else environment
    cleaned = {
        key: value
        for key, value in source.items()
        if not key.lstrip("_").upper().startswith("PYI_")
        and key.upper() != "_MEIPASS2"
    }
    cleaned["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return cleaned


def select_update_asset(
    release: ReleaseInfo,
    *,
    installed: bool,
) -> ReleaseAsset:
    expected_name = SETUP_ASSET if installed else PORTABLE_ASSET
    asset = next((item for item in release.assets if item.name == expected_name), None)
    if asset is None:
        raise RuntimeError(f"Release asset is missing: {expected_name}")
    return asset


def download_asset(asset: ReleaseAsset, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        asset.download_url,
        headers={"User-Agent": "Dofus-MultiCompte-Enhancer"},
    )
    hasher = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=60.0) as response:
        with destination.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                hasher.update(chunk)
    if asset.size and destination.stat().st_size != asset.size:
        destination.unlink(missing_ok=True)
        raise RuntimeError("The downloaded update size does not match the release asset.")
    if asset.digest:
        algorithm, _, expected = asset.digest.partition(":")
        if algorithm.casefold() == "sha256" and hasher.hexdigest().casefold() != expected.casefold():
            destination.unlink(missing_ok=True)
            raise RuntimeError("The downloaded update checksum does not match GitHub.")
    return destination


def _write_portable_update_script(path: Path) -> None:
    script = r'''param(
    [int]$ProcessId,
    [string]$Package,
    [string]$Destination,
    [string]$ExecutableName
)
$ErrorActionPreference = "Stop"
Wait-Process -Id $ProcessId -ErrorAction SilentlyContinue
$target = Join-Path $Destination $ExecutableName
Copy-Item -LiteralPath $Package -Destination $target -Force
Start-Process -FilePath $target -WorkingDirectory $Destination
Remove-Item -LiteralPath $Package -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
'''
    path.write_text(script, encoding="utf-8-sig")


def launch_update(
    release: ReleaseInfo,
    *,
    executable: Path | None = None,
) -> None:
    """Download and launch the correct unattended update path.

    Installed copies run the Inno Setup package silently. Portable copies use a
    short-lived PowerShell helper that replaces the executable after this
    process exits, then restarts it.
    """
    current_executable = (executable or Path(sys.executable)).resolve()
    installed = is_installed(current_executable)
    asset = select_update_asset(release, installed=installed)
    child_environment = update_subprocess_environment()
    update_directory = Path(tempfile.gettempdir()) / "DofusMultiCompteEnhancer"
    update_directory.mkdir(parents=True, exist_ok=True)
    package = download_asset(asset, update_directory / asset.name)

    if installed:
        subprocess.Popen(
            [
                str(package),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/CLOSEAPPLICATIONS",
            ],
            close_fds=True,
            env=child_environment,
        )
        return

    script_path = update_directory / f"portable-update-{uuid.uuid4().hex}.ps1"
    _write_portable_update_script(script_path)
    startup_info = subprocess.STARTUPINFO()
    startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-ProcessId",
            str(os.getpid()),
            "-Package",
            str(package),
            "-Destination",
            str(current_executable.parent),
            "-ExecutableName",
            current_executable.name,
        ],
        startupinfo=startup_info,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        close_fds=True,
        env=child_environment,
    )
