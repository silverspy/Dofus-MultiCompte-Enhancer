# Dofus MultiCompte Enhancer

[![Windows CI and Release](https://github.com/silverspy/Dofus-MultiCompte-Enhancer/actions/workflows/windows-build.yml/badge.svg)](https://github.com/silverspy/Dofus-MultiCompte-Enhancer/actions/workflows/windows-build.yml)
[![Latest release](https://img.shields.io/github/v/release/silverspy/Dofus-MultiCompte-Enhancer?display_name=tag)](https://github.com/silverspy/Dofus-MultiCompte-Enhancer/releases/latest)

[Français](#français) · [English](#english)

<p align="center">
  <img src="docs/images/dofus-integration.jpg" width="820" alt="Dofus MultiCompte Enhancer intégré à l'interface de Dofus" />
</p>

## Français

Pilotez vos comptes Dofus depuis une seule barre compacte, pensée pour rester discrète à côté de l'interface du jeu. **Dofus MultiCompte Enhancer** automatise les manipulations répétitives et vous laisse vous concentrer sur votre partie : lancez votre équipe, formez votre groupe, changez de personnage et répliquez vos actions sans jongler manuellement entre quatre fenêtres.

### Trois fonctions pour gagner du temps à chaque session

#### 🚀 1. Auto-connect et invitations automatiques

Appuyez sur Play et laissez l'outil préparer votre session. Il ouvre Ankama Launcher si nécessaire, démarre les quatre clients, attend que chaque bouton `JOUER` soit réellement disponible, reconnaît vos personnages puis entre en jeu. Votre chef invite ensuite automatiquement les trois autres personnages, chaque invitation est acceptée et vous revenez directement sur la fenêtre du chef.

#### 🪞 2. Répliquez vos actions sur toutes les fenêtres

Activez le mode réplication avec le raccourci de votre choix. Vos clics, leur position proportionnelle, les boutons de souris, la molette et vos frappes clavier sont immédiatement reproduits sur les autres clients. Appuyez de nouveau sur le raccourci pour reprendre un contrôle individuel.

#### ⚡ 3. Changez de fenêtre avec un retour visuel instantané

Passez au personnage précédent ou suivant avec une touche clavier, un bouton de souris ou la molette. La barre met d'abord en évidence le personnage sélectionné, puis affiche sa fenêtre : vous voyez immédiatement où vous allez, sans hésitation ni recherche dans la barre des tâches.

### Une interface faite pour rester à portée de main

| | Vous pouvez… |
|:--:|---|
| 👑 | **Repérer immédiatement votre chef et votre fenêtre active** grâce à la couronne, aux icônes de classe et à la surbrillance instantanée. |
| ↔️ | **Choisir une barre verticale ou horizontale** selon la place disponible autour de votre interface Dofus. |
| 🎨 | **Ajuster l'échelle et la transparence** pour garder l'outil visible sans masquer votre jeu. |
| 🔒 | **Verrouiller la barre ou les icônes** afin d'éviter les déplacements involontaires en pleine partie. |
| 🎛️ | **Configurer chaque raccourci** avec votre clavier, vos boutons de souris ou votre molette. |
| 🌍 | **Utiliser l'application en français ou en anglais** depuis le menu des paramètres. |

<p align="center">
  <img src="docs/images/toolbar-vertical.png" height="390" alt="Barre verticale avec chef de groupe et personnage actif" />
  &nbsp;&nbsp;&nbsp;
  <img src="docs/images/settings-window.png" height="390" alt="Fenêtre des paramètres de Dofus MultiCompte Enhancer" />
</p>

### Télécharger

Téléchargez l'exécutable Windows prêt à l'emploi depuis la [dernière Release](https://github.com/silverspy/Dofus-MultiCompte-Enhancer/releases/latest).

Aucune installation de Python n'est nécessaire. Windows peut afficher un avertissement SmartScreen, car l'exécutable n'est pas signé numériquement.

Les réglages et les personnages détectés sont enregistrés dans :

```text
%LOCALAPPDATA%\Dofus MultiCompte Enhancer
```

### Développement et publication

Prérequis : Windows et Python 3.12 ou plus récent.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m PyInstaller --noconfirm --clean Dofus-MultiCompte-Enhancer.spec
```

L'exécutable est généré dans `dist\Dofus-MultiCompte-Enhancer.exe`. La pipeline Windows construit également un artefact à chaque changement ciblant `main` et publie automatiquement une Release lors de l'envoi d'un tag `v*`.

---

## English

Control your Dofus accounts from one compact toolbar designed to sit discreetly beside the game interface. **Dofus MultiCompte Enhancer** handles repetitive setup so you can focus on playing: launch your team, build the group, switch characters, and mirror actions without manually juggling four windows.

### Three features that save time in every session

#### 🚀 1. Auto-connect and automatic invitations

Press Play and let the tool prepare your session. It opens Ankama Launcher when needed, starts all four clients, waits until every `PLAY` button is genuinely ready, recognizes your characters, and enters the game. Your leader then invites the other three characters automatically, each invitation is accepted, and you return directly to the leader's window.

#### 🪞 2. Mirror your actions across every window

Enable replication with your chosen shortcut. Your clicks, proportional positions, mouse buttons, scrolling, and keyboard input are immediately reproduced in the other clients. Press the shortcut again whenever you want to return to individual control.

#### ⚡ 3. Switch windows with instant visual feedback

Move to the previous or next character with a keyboard key, mouse button, or the wheel. The toolbar highlights your selection before bringing its window forward, so you always know where you are going without searching through the Windows taskbar.

### An interface that stays within reach

| | You can… |
|:--:|---|
| 👑 | **Spot your leader and active window instantly** through the crown, class icons, and immediate highlighting. |
| ↔️ | **Choose a vertical or horizontal toolbar** to fit the available space around your Dofus interface. |
| 🎨 | **Adjust scale and opacity** to keep the tool visible without covering the game. |
| 🔒 | **Lock the toolbar or character icons** to prevent accidental movement while playing. |
| 🎛️ | **Configure every shortcut** using your keyboard, mouse buttons, or wheel. |
| 🌍 | **Use the application in French or English** from the settings panel. |

### Download

Download the ready-to-run Windows executable from the [latest Release](https://github.com/silverspy/Dofus-MultiCompte-Enhancer/releases/latest).

Python is not required for the released executable. Windows may display a SmartScreen warning because the binary is not code-signed.

Settings and detected characters are stored in:

```text
%LOCALAPPDATA%\Dofus MultiCompte Enhancer
```

### Development and releases

Requirements: Windows and Python 3.12 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m PyInstaller --noconfirm --clean Dofus-MultiCompte-Enhancer.spec
```

The executable is generated at `dist\Dofus-MultiCompte-Enhancer.exe`. The Windows pipeline also builds an artifact for every change targeting `main` and automatically publishes a Release when a `v*` tag is pushed.

## Avertissement / Disclaimer

Projet communautaire non affilié à Ankama. L'utilisateur reste responsable du respect des conditions d'utilisation du jeu.

This is an unofficial community project and is not affiliated with Ankama. Users remain responsible for complying with the game's terms of service.
