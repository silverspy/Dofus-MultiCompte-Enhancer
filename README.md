# Dofus MultiCompte Enhancer

Interface Windows compacte pour piloter plusieurs fenêtres Dofus depuis une barre inspirée de l’interface du jeu.

## Fonctionnalités

- lancement d’Ankama Launcher et ouverture des quatre fenêtres Dofus ;
- détection visuelle des boutons `JOUER` et `ACCEPTER` ;
- lecture OCR des personnages sélectionnés ;
- création automatique du groupe par invitations ;
- navigation rapide entre les fenêtres avec raccourcis clavier ou souris ;
- réplication optionnelle des clics, déplacements de souris et frappes clavier ;
- position, échelle, transparence, orientation et contrôles personnalisables ;
- interface verticale ou horizontale avec icônes de classes et chef de groupe.

## Télécharger l’EXE

Chaque commit déclenche la workflow **Tests et EXE Windows**. Une fois terminée, l’exécutable est disponible dans l’artefact `Dofus-MultiCompte-Enhancer-Windows-<commit>` de l’exécution GitHub Actions.

Les réglages et les personnages détectés sont conservés dans :

```text
%LOCALAPPDATA%\Dofus MultiCompte Enhancer
```

## Développement

Prérequis : Windows et Python 3.12 ou plus récent.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m PyInstaller --noconfirm --clean Dofus-MultiCompte-Enhancer.spec
```

L’exécutable est alors créé dans `dist\Dofus-MultiCompte-Enhancer.exe`.

Pour lancer directement les sources :

```powershell
python .\app\dofus_panel.py
```

## Tests de non-régression

Les tests couvrent notamment :

- la détection de la barre de chat ;
- le refus du bouton `JOUER` gris pendant le chargement ;
- la détection du bouton d’acceptation des invitations ;
- la validation OCR des pseudonymes ;
- les raccourcis, la configuration, la transparence des icônes et les ressources requises.

## Avertissement

Projet communautaire non affilié à Ankama. L’utilisateur reste responsable du respect des conditions d’utilisation du jeu.
