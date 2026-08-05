# Dofus MultiCompte Enhancer

[![Windows CI and Release](https://github.com/silverspy/Dofus-MultiCompte-Enhancer/actions/workflows/windows-build.yml/badge.svg)](https://github.com/silverspy/Dofus-MultiCompte-Enhancer/actions/workflows/windows-build.yml)
[![Latest release](https://img.shields.io/github/v/release/silverspy/Dofus-MultiCompte-Enhancer?display_name=tag)](https://github.com/silverspy/Dofus-MultiCompte-Enhancer/releases/latest)

A compact Windows companion for managing several Dofus windows from a toolbar inspired by the game's interface.

<p align="center">
  <img src="docs/images/toolbar-vertical.png" height="390" alt="Vertical toolbar with the group leader and active character" />
  &nbsp;&nbsp;&nbsp;
  <img src="docs/images/settings-window.png" height="390" alt="Dofus MultiCompte Enhancer settings window" />
</p>

## Features

- starts Ankama Launcher and opens the four expected Dofus windows;
- detects the `JOUER` and `ACCEPTER` buttons visually;
- reads the selected character names with local OCR;
- creates the group automatically through invitations;
- switches quickly between windows with configurable keyboard or mouse shortcuts;
- optionally mirrors clicks, mouse movement, scrolling, and keyboard input;
- preserves proportional click coordinates when window sizes differ;
- provides configurable orientation, position locks, scale, opacity, leader, and Play button;
- supports compact vertical and horizontal layouts with class icons and a leader crown.

## Download

Download the latest ready-to-run Windows executable from the [Releases page](https://github.com/silverspy/Dofus-MultiCompte-Enhancer/releases/latest).

No Python installation is required for the released executable. Windows may display a SmartScreen warning because the binary is not code-signed.

Application settings and detected characters are stored in:

```text
%LOCALAPPDATA%\Dofus MultiCompte Enhancer
```

## Automated builds and releases

The **Windows CI and Release** workflow runs the regression suite and builds a standalone executable for every commit and pull request targeting `main`.

- Every successful workflow run provides a downloadable executable artifact for 14 days.
- Pushing a tag such as `v0.1.0` creates a GitHub Release automatically.
- The release is created only after the tests, build, and executable validation succeed.

## Development

Requirements: Windows and Python 3.12 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m PyInstaller --noconfirm --clean Dofus-MultiCompte-Enhancer.spec
```

The executable is generated at `dist\Dofus-MultiCompte-Enhancer.exe`.

Run the application directly from source with:

```powershell
python .\app\dofus_panel.py
```

## Regression coverage

The automated tests cover, among other things:

- chat input detection;
- rejection of the gray `JOUER` loading state;
- invitation acceptance detection;
- OCR character-name validation;
- active-character highlighting after the launch workflow;
- keyboard mappings, configuration persistence, icon transparency, and required assets.

## Disclaimer

This is an unofficial community project and is not affiliated with Ankama. Users remain responsible for complying with the game's terms of service.
