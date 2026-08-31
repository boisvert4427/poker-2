# Plan de travail OCR poker

Ce document sert de feuille de route pour ne pas mélanger les étapes.

## Objectif

Sur une table de taille fixe :

- reconnaître correctement les informations importantes ;
- viser au moins 95 % de précision ;
- obtenir une lecture complète en environ 1 seconde ;
- pouvoir ensuite adapter le système au multitable.

## Définitions

- **Screenshot** : image complète de la table.
- **Crop** : petite image découpée dans le screenshot, correspondant à une zone précise.
- **Référence Codex** : valeur considérée comme correcte pour un screenshot, par exemple `10h`, `125 BB` ou `dealer présent`.
- **OCR local** : lecture réalisée par le code du projet, actuellement avec Tesseract et du traitement d’image.
- **Accuracy** : proportion de valeurs correctement reconnues.

## État actuel

- 63 screenshots originaux sont conservés dans `sessions/20260412_114742/`.
- Les anciennes archives de travail ont été supprimées.
- Les références Codex des batchs 1 et 2 sont dans `data/ocr_dataset/references/`.
- Les zones à lire sont définies dans le `zone_map` des références.
- Les crops du batch 1 existent dans `data/ocr_dataset/crops/batch_01/`.
- Les crops du batch 2 ne sont pas encore générés.
- Aucun modèle PyTorch n’est entraîné pour le moment.

## Marche à suivre

### 1. Construire les données de référence

Pour chaque screenshot, noter les valeurs visibles :

- cartes du héros ;
- cartes du board, de 1 à 5 ;
- nom, stack et mise des joueurs ;
- bouton dealer ;
- pot et pot total ;
- boutons d’action si nécessaires.

Les références doivent décrire ce qui est réellement visible. Une carte cachée n’est pas une carte lisible.

### 2. Vérifier les zones de crop

Générer les crops à partir du `zone_map`, puis ouvrir quelques exemples de chaque type.

On ne mesure pas encore l’OCR à cette étape. On vérifie d’abord que chaque rectangle regarde le bon endroit.

### 3. Générer les crops des 63 screenshots

Utiliser les mêmes zones fixes pour les différents batchs. Si une zone est mauvaise, corriger la zone avant de générer les données suivantes.

### 4. Mesurer le système actuel

Faire lire les crops par le code local et comparer chaque résultat à la référence Codex.

Produire un score séparé pour :

- cartes ;
- board ;
- noms ;
- stacks ;
- mises ;
- dealer ;
- pot.

Un score global seul masque les éléments qui posent problème.

### 5. Améliorer les détecteurs dans le bon ordre

Priorité recommandée :

1. présence des cartes et bouton dealer ;
2. board et cartes du héros ;
3. pot et mises ;
4. stacks ;
5. noms des joueurs.

Pour les cartes, privilégier les zones fixes, la couleur, les formes et des templates. Pour les nombres et les noms, utiliser un OCR limité à la zone et à l’alphabet attendu.

### 6. Optimiser la vitesse

Ne lire que les zones utiles. Éviter de lancer Tesseract sur une zone vide. Mesurer le temps total après chaque modification.

Objectif intermédiaire : précision d’abord, puis réduction progressive du nombre de lectures OCR jusqu’à environ 1 seconde.

### 7. Décider s’il faut entraîner une IA

Ne pas commencer par PyTorch. Si les méthodes spécialisées atteignent déjà l’objectif, elles seront plus simples et plus rapides.

Entraîner un petit modèle local uniquement pour les éléments qui restent insuffisants après les étapes précédentes. Les crops et références Codex constitueront alors les données d’entraînement et de test.

### 8. Valider sur des screenshots jamais utilisés

Garder une partie des screenshots à l’écart pendant les améliorations. La validation finale doit utiliser ces images inconnues du système.

## Règles pour éviter de se perdre

- Une modification à la fois.
- Toujours comparer avant/après sur le même batch.
- Ne jamais utiliser la sortie OCR comme référence.
- Ne pas mélanger les anciennes archives avec le nouveau dataset.
- Ne pas entraîner un modèle avant d’avoir des références fiables.
- Ne pas passer au multitable avant que la table fixe soit stable.

## Prochaine action exacte

Générer `data/ocr_dataset/crops/batch_02/` à partir de `codex_batch_02.json`, puis vérifier quelques crops. Après cette vérification seulement, lancer la comparaison OCR du batch 2.

