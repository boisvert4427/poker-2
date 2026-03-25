# Winamax Poker Tracker

Prototype Python desktop pour Winamax sous Windows.

Le projet sert a :

- detecter les fenetres Winamax ;
- localiser et lire les hand histories ;
- capturer la table en local ;
- faire une premiere fusion `hand history + OCR + signaux visuels` ;
- preparer un futur assistant live plus robuste.

## Etat actuel

Le prototype sait deja :

- detecter les processus Winamax ;
- detecter les fenetres de table visibles ;
- trouver les historiques Winamax, y compris sous `AppData\\Roaming\\winamax\\documents` ;
- lire la derniere main disponible ;
- parser une main Winamax minimale ;
- afficher une vue desktop Tkinter ;
- faire un auto-refresh ;
- capturer la fenetre de table ;
- lancer un OCR local avec Tesseract ;
- afficher une premiere vue `Main en cours` ;
- charger des zones de calibration depuis `config/calibration.json`.

## Limites actuelles

Le prototype ne fait pas encore :

- de recommendations de jeu fiables ;
- de HUD overlay final ;
- de parsing complet preflop/postflop ;
- de detection parfaitement stable du tour de parole ;
- de calibration graphique guidee sur image.

## Prerequis

- Windows
- Python 3.11+
- Winamax installe
- Tesseract OCR installe

Tesseract est attendu ici :

```text
C:\Program Files\Tesseract-OCR\tesseract.exe
```

## Installation

Depuis le dossier du projet :

```powershell
cd C:\Users\leona\Documents\python\poker
pip install -e .
```

## Lancer l'application

Option la plus simple :

```powershell
python main.py
```

Ou via le module :

```powershell
python -m poker_tracker
```

Ou via l'entree console apres installation editable :

```powershell
poker-tracker
```

## Utilisation actuelle

1. Ouvrir Winamax et afficher une table.
2. Lancer l'application.
3. Verifier les onglets `Fenetres detectees`, `Derniere main`, `Main en cours` et `OCR live`.
4. Utiliser l'onglet `Calibration` pour ajuster les zones si necessaire.

## Annotation OpenAI des sessions

Le projet peut aussi annoter une session de screenshots avec l'API OpenAI pour accelerer l'entrainement du detecteur local.

Preparer la cle API dans `.env` a la racine du projet :

```text
OPENAI_API_KEY=sk-...
```

Un modele vide et ignore par Git est deja cree dans :

- `.env`
- `.env.example`

Traiter la derniere session :

```powershell
python scripts\annotate_session_with_openai.py
```

Traiter une session precise :

```powershell
python scripts\annotate_session_with_openai.py --session .\sessions\20260324_204813
```

Le script :

- cree un fichier `.openai.json` par screenshot ;
- remplit ou enrichit le `.review.json` avec les valeurs attendues venant de l'IA ;
- calcule `openai_calibration.suggested.json` pour proposer des zones moyennes issues des boxes renvoyees.

Pour appliquer directement la calibration suggeree :

```powershell
python scripts\annotate_session_with_openai.py --apply-calibration
```

## Fichiers importants

- `main.py` : point d'entree simple
- `src/poker_tracker/app.py` : interface desktop
- `src/poker_tracker/detection.py` : detection Winamax
- `src/poker_tracker/history.py` : lecture des historiques
- `src/poker_tracker/parser.py` : parsing minimal Winamax
- `src/poker_tracker/ocr.py` : capture et OCR local
- `src/poker_tracker/live_state.py` : fusion live `history + OCR`
- `src/poker_tracker/visual.py` : signaux visuels sur les boutons
- `config/calibration.json` : zones de calibration sauvegardees
- `docs/cadrage-projet.md` : cadrage produit initial

## Workflow Git

Le workflow de travail conseille est documente ici :

- [docs/workflow-git.md](C:\Users\leona\Documents\python\poker\docs\workflow-git.md)
