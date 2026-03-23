# Workflow Git

## Branche principale

- `main` doit rester dans un etat propre et relancable.

## Facon de travailler

Pour chaque sujet, creer une branche courte :

- `feature/calibration-ui`
- `feature/live-turn-detection`
- `feature/winamax-parser`
- `fix/ocr-encoding`

Commande type :

```powershell
git checkout main
git pull
git checkout -b feature/nom-court
```

## Commits

Faire des commits petits et lisibles :

- `Add calibration config loading`
- `Improve Winamax history detection`
- `Prototype action button visual detection`

## Cycle recommande

1. partir de `main`
2. creer une branche
3. coder une etape coherente
4. tester localement
5. commit
6. push
7. merger vers `main`

## Commandes utiles

Voir l'etat :

```powershell
git status
```

Voir les branches :

```powershell
git branch
```

Creer une branche :

```powershell
git checkout -b feature/nom-court
```

Pousser une branche :

```powershell
git push -u origin feature/nom-court
```

Revenir sur `main` :

```powershell
git checkout main
git pull
```

## Regle simple pour ce projet

- une branche par bloc de travail ;
- pas de gros commit fourre-tout ;
- toujours verifier que l'app se lance avant de pousser.
