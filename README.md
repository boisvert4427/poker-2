# Winamax Poker Tracker

Prototype Python desktop pour detecter Winamax sur Windows, localiser les historiques de mains et preparer le futur socle d'analyse live.

## Lancer

```powershell
python -m poker_tracker
```

Ou apres installation editable :

```powershell
pip install -e .
poker-tracker
```

## Etat actuel

- detection des processus Winamax ;
- detection des fenetres Winamax visibles ;
- recherche des dossiers d'historiques connus ;
- affichage desktop simple sous Tkinter ;
- auto-refresh ;
- capture locale de la fenetre de table ;
- OCR local optionnel si Tesseract est installe.

## Limites actuelles

- pas encore d'analyse de main ;
- pas encore de HUD overlay ;
- pas encore de parsing de hand histories ;
- pas encore de recommandations live.
