from __future__ import annotations

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
