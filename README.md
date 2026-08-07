# Dofus MultiCompte Enhancer

[![Windows CI and Release](https://github.com/silverspy/Dofus-MultiCompte-Enhancer/actions/workflows/windows-build.yml/badge.svg)](https://github.com/silverspy/Dofus-MultiCompte-Enhancer/actions/workflows/windows-build.yml)
[![Latest release](https://img.shields.io/github/v/release/silverspy/Dofus-MultiCompte-Enhancer?display_name=tag)](https://github.com/silverspy/Dofus-MultiCompte-Enhancer/releases/latest)

[Français](#français) · [English](#english)

<p align="center">
  <img src="docs/images/dofus-integration.jpg" width="820" alt="Dofus MultiCompte Enhancer intégré à l'interface de Dofus" />
</p>

## Français

Pilotez vos comptes Dofus depuis une seule barre compacte, pensée pour rester discrète à côté de l'interface du jeu. **Dofus MultiCompte Enhancer** automatise les manipulations répétitives et vous laisse vous concentrer sur votre partie : lancez votre équipe, formez votre groupe, changez de personnage et répliquez vos actions sans jongler manuellement entre vos fenêtres.

### Trois fonctions pour gagner du temps à chaque session

#### 🚀 1. Auto-connect et invitations automatiques

Appuyez sur Play et laissez l'outil préparer votre session. Il ouvre Ankama Launcher si nécessaire, détecte automatiquement le nombre de comptes sélectionnés, attend que chaque bouton `JOUER` soit réellement disponible, reconnaît vos personnages puis entre en jeu. Votre chef invite ensuite automatiquement tous les autres personnages, chaque invitation est acceptée où que son panneau apparaisse et vous revenez directement sur la fenêtre du chef.

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
| 🔄 | **Être averti des nouvelles versions et les installer automatiquement** sans rechercher ni remplacer manuellement l'exécutable. |
| 🖥️ | **Réduire, restaurer ou quitter clairement l'application** depuis les paramètres ou par clic droit sur son icône dans la zone de notification Windows. |

<p align="center">
  <img src="docs/images/toolbar-vertical.png" height="390" alt="Barre verticale avec chef de groupe et personnage actif" />
  &nbsp;&nbsp;&nbsp;
  <img src="docs/images/settings-window.png" height="390" alt="Fenêtre des paramètres de Dofus MultiCompte Enhancer" />
</p>

### Télécharger : portable ou installateur

Choisissez votre format depuis la [dernière Release](https://github.com/silverspy/Dofus-MultiCompte-Enhancer/releases/latest) :

| Version | Pour quel usage ? |
|---|---|
| **`Dofus-MultiCompte-Enhancer-Setup.exe`** | Installation Windows classique dans votre profil, raccourcis dans le menu Démarrer et sur le Bureau, mises à jour intégrées et désinstalleur propre. |
| **`Dofus-MultiCompte-Enhancer-Portable.zip`** | Aucun installateur : décompressez l'archive où vous le souhaitez et lancez directement l'EXE. La mise à jour portable remplace et relance automatiquement l'application. |

Aucune installation de Python n'est nécessaire. Les versions publiées sont signées avec Authenticode lorsque le certificat de publication est configuré dans GitHub Actions. Une nouvelle identité de signature peut malgré tout afficher temporairement SmartScreen pendant que sa réputation se construit.

La version `0.3.0` est distribuée sans signature Authenticode publique et Windows peut donc afficher un avertissement SmartScreen. Chaque Release fournit néanmoins `SHA256SUMS.txt` et une attestation GitHub générée par la pipeline officielle. Vous pouvez vérifier l'origine d'un fichier téléchargé avec :

```powershell
Get-FileHash .\Dofus-MultiCompte-Enhancer-Setup.exe -Algorithm SHA256
gh attestation verify .\Dofus-MultiCompte-Enhancer-Setup.exe --repo silverspy/Dofus-MultiCompte-Enhancer
```

Comparez la première empreinte avec celle de `SHA256SUMS.txt`. L'attestation confirme la provenance du build GitHub ; elle ne constitue pas à elle seule une garantie d'absence de logiciel malveillant.

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

L'exécutable est généré dans `dist\Dofus-MultiCompte-Enhancer.exe`. La pipeline Windows construit l'EXE brut, l'archive portable et l'installateur à chaque changement ciblant `main`, puis publie automatiquement les trois fichiers lors de l'envoi d'un tag `v*`.

#### Signature Windows hors Store

La pipeline accepte un certificat Authenticode OV, EV ou Microsoft Artifact Signing exporté au format PFX. Configurez les secrets GitHub Actions `WINDOWS_CERTIFICATE_BASE64` et `WINDOWS_CERTIFICATE_PASSWORD` : l'EXE, l'installateur et le désinstalleur seront signés en SHA-256 et horodatés. Sans ces secrets, le build reste disponible mais non signé.

Pour tester localement le processus avec un certificat auto-signé :

```powershell
.\scripts\New-DevelopmentCodeSigningCertificate.ps1
```

Le PFX est créé dans le dossier ignoré `certificates`. Ce certificat de développement ne donne aucune confiance publique à SmartScreen et ne doit jamais être publié.

---

## English

Control your Dofus accounts from one compact toolbar designed to sit discreetly beside the game interface. **Dofus MultiCompte Enhancer** handles repetitive setup so you can focus on playing: launch your team, build the group, switch characters, and mirror actions without manually juggling your windows.

### Three features that save time in every session

#### 🚀 1. Auto-connect and automatic invitations

Press Play and let the tool prepare your session. It opens Ankama Launcher when needed, automatically detects how many accounts are selected, waits until every `PLAY` button is genuinely ready, recognizes your characters, and enters the game. Your leader then invites every other character automatically, each invitation is accepted wherever its panel appears, and you return directly to the leader's window.

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
| 🔄 | **Get notified about new releases and install them automatically** without manually finding or replacing the executable. |
| 🖥️ | **Minimize, restore, or clearly quit the application** from Settings or by right-clicking its Windows notification-area icon. |

### Download: portable or installer

Choose a package from the [latest Release](https://github.com/silverspy/Dofus-MultiCompte-Enhancer/releases/latest):

| Package | Best for |
|---|---|
| **`Dofus-MultiCompte-Enhancer-Setup.exe`** | A standard per-user Windows installation with Start Menu and Desktop shortcuts, integrated updates, and a clean uninstaller. |
| **`Dofus-MultiCompte-Enhancer-Portable.zip`** | No installer: extract it anywhere and run the EXE directly. Portable updates replace and restart the application automatically. |

Python is not required for the released executable. Published builds use Authenticode when the release certificate is configured in GitHub Actions. A new signing identity can still trigger SmartScreen temporarily while its reputation develops.

Version `0.3.0` is distributed without a publicly trusted Authenticode signature, so Windows may display a SmartScreen warning. Every Release still includes `SHA256SUMS.txt` and a GitHub attestation produced by the official workflow. Verify a downloaded file with:

```powershell
Get-FileHash .\Dofus-MultiCompte-Enhancer-Setup.exe -Algorithm SHA256
gh attestation verify .\Dofus-MultiCompte-Enhancer-Setup.exe --repo silverspy/Dofus-MultiCompte-Enhancer
```

Compare the first hash with `SHA256SUMS.txt`. The attestation establishes GitHub build provenance; by itself, it does not guarantee that software is free from malicious behavior.

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

The executable is generated at `dist\Dofus-MultiCompte-Enhancer.exe`. The Windows pipeline builds the raw EXE, portable archive, and installer for every change targeting `main`, then publishes all three files automatically when a `v*` tag is pushed.

#### Windows signing for non-Store distribution

The pipeline accepts an OV, EV, or Microsoft Artifact Signing Authenticode certificate exported as a PFX. Configure the GitHub Actions secrets `WINDOWS_CERTIFICATE_BASE64` and `WINDOWS_CERTIFICATE_PASSWORD`; the application EXE, installer, and uninstaller are then SHA-256 signed and timestamped. Builds remain available but unsigned when those secrets are absent.

For a local signing-flow test with a self-signed certificate:

```powershell
.\scripts\New-DevelopmentCodeSigningCertificate.ps1
```

The PFX is created in the ignored `certificates` directory. This development certificate provides no public SmartScreen trust and must never be published.

## Avertissement / Disclaimer

Projet communautaire non affilié à Ankama. L'utilisateur reste responsable du respect des conditions d'utilisation du jeu.

This is an unofficial community project and is not affiliated with Ankama. Users remain responsible for complying with the game's terms of service.
