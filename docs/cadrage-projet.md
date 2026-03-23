# Poker Tracker Winamax - Cadrage Initial

## Objectif

Construire une application Python orientee Winamax capable de :

- suivre et historiser les sessions de jeu ;
- exploiter les donnees disponibles apres ou pendant la session ;
- fournir une aide a la decision clairement definie ;
- rester dans un cadre legal, technique et pratique acceptable.

Ce document sert a cadrer le projet avant toute implementation.

## Decision actuelle

Le projet vise en priorite une application personnelle sous Windows pour le cash game No-Limit Hold'em sur Winamax, avec analyse en direct de la main, HUD, profilage adversaire et aide a la decision.

L'outil doit toutefois etre pense des le depart pour rester evolutif :

- extension a d'autres formats de poker plus tard ;
- extension a d'autres plateformes potentiellement plus tard ;
- ajout futur de fonctions semi-automatiques ;
- possible ouverture a une diffusion plus large a long terme.

## Vision produit

L'application pourrait combiner trois briques :

1. un tracker de sessions et de performances ;
2. un analyseur de mains / spots ;
3. un moteur d'aide a la decision.

Le point le plus sensible du projet est la troisieme brique. Selon la forme retenue, elle peut devenir techniquement complexe et potentiellement incompatible avec les regles de la room.

## Reponses de cadrage deja validees

### 1. Format de jeu

- priorite immediate : cash game ;
- objectif long terme : gerer aussi les autres formats.

### 2. Variante

- priorite immediate : No-Limit Hold'em ;
- autres variantes possibles plus tard ;
- l'architecture devra donc eviter de figer toute la logique sur un seul type de jeu.

### 3. Usage

- l'outil doit fonctionner a la fois :
  - en direct pendant la session ;
  - en analyse hors ligne.

### 4. Aide a la decision

- l'aide doit combiner des usages differents, pas un seul :
  - affichage de stats ;
  - signalement de leaks ;
  - suggestions d'action ;
  - ranges et conseils pedagogiques.

### 5. HUD

- un HUD est souhaite des la vision cible ;
- il doit afficher :
  - des stats ;
  - des recommandations visibles en direct.

### 6. Sources de donnees

- les hand histories Winamax sont deja disponibles ;
- la collecte en direct devra idealement s'appuyer sur :
  - les historiques de mains ;
  - la lecture d'ecran / overlay si necessaire.

### 7. Cible d'analyse

- suivre :
  - les propres stats du joueur ;
  - les profils adverses.

### 8. Distribution

- usage personnel prioritaire ;
- structure a garder evolutive pour une diffusion potentielle plus tard.

### 9. Interface

- choix valide : application desktop ;
- l'option web locale est ecartee pour le moment.

### 10. Priorite MVP

- priorite fonctionnelle : analyse de la main en direct ;
- l'objectif n'est pas un simple tracker passif.

### 11. Nature de la recommandation live

- l'application doit :
  - afficher des stats et conseils en direct ;
  - recommander une action.

### 12. Base strategique

- il faudra permettre de travailler avec :
  - des ranges / regles personnelles ;
  - des ranges de reference plus theoriques ;
  - un mecanisme pour changer cette base avec le temps.

### 13. Nombre de tables

- depart : une seule table ;
- cible plus tard : multitabling.

### 14. Detection du contexte

- le contexte de table doit etre detecte automatiquement quand c'est possible ;
- l'utilisateur ne veut pas devoir saisir a la main les blindes en usage normal.

### 15. Systeme d'exploitation

- Windows prioritaire ;
- autres plateformes pas exclues mais hors priorite.

### 16. Niveau d'automatisation

- phase initiale : assistant avec validation humaine ;
- cible future : semi-automatisation possible.

### 17. Explicabilite

- deux modes doivent exister :
  - mode explicatif avec raisons detaillees ;
  - mode rapide / minimal.

### 18. Stockage

- stockage local prioritaire ;
- architecture a preparer pour un cloud plus tard.

### 19. Formats de table

- l'application devra a terme gerer :
  - 6-max ;
  - heads-up ;
  - full ring ;
  - autres formats de table pertinents.

### 20. Profil adversaire

- les profils adverses devront combiner :
  - les stats observees ;
  - les notes manuelles.

### 21. Historisation

- au debut, priorite aux stats agregees ;
- pas besoin de replayer ou d'historique complet des mains dans le premier perimetre.

### 22. Analyse hors session

- l'application devra aussi detecter automatiquement les leaks personnels apres session.

### 23. Mode entrainement

- non prioritaire ;
- exclu du premier perimetre.

### 24. Mode conforme limite

- non retenu au cadrage actuel ;
- la vision assume un mode avance plutot qu'un double mode distinct.

### 25. Extensibilite technique

- pas besoin d'un systeme de plugins des le debut ;
- un socle propre, modulaire et evolutif suffit.

## Perimetre v1 recommande

Pour coller a ton objectif sans coder trop tot des couches secondaires, la v1 pourrait viser :

- ingestion des hand histories Winamax ;
- moteur de detection d'etat de table en direct ;
- HUD desktop ;
- profilage des adversaires a partir des stats agregees ;
- moteur de recommandations live explicable ;
- tableau de bord de sessions et de leaks personnels ;
- stockage local robuste.

Cette v1 reste deja ambitieuse. Elle devra probablement etre decoupee en plusieurs jalons.

## Fonctions candidates

### Bloc A - Tracking

- import automatique d'un dossier de hand histories ;
- detection des sessions ;
- bankroll et resultats par jour / semaine / mois ;
- filtres par limite, format, position, stack depth ;
- indicateurs standards : VPIP, PFR, 3-bet, fold to 3-bet, c-bet, WTSD, WWSF.

### Bloc B - Analyse

- classification des spots preflop et postflop ;
- detection de leaks recurrents ;
- comparaison a des ranges de reference ;
- export de rapports.

### Bloc C - Aide a la decision

- assistant preflop et postflop base sur ranges / regles ;
- suggestions contextuelles explicables ;
- score de confiance ou niveau d'alerte ;
- mode rapide ;
- mode explicatif ;
- mode "review apres session".

### Bloc D - HUD et lecture live

- affichage overlay desktop ;
- identification de la table et du contexte ;
- consolidation des informations hand history + lecture ecran ;
- support initial une table, extensible multi-tables.

## Contraintes et risques

### Reglementaires / plateforme

- certaines formes d'assistance en temps reel peuvent etre interdites ou sensibles ;
- un HUD ou une recommandation live doivent etre valides tres prudemment ;
- l'orientation choisie ici est volontairement un mode avance, donc ce point est critique.

### Techniques

- les formats d'historique peuvent etre heterogenes ;
- le parsing des mains demande une structure de donnees propre ;
- le temps reel ajoute des contraintes d'observation fichier, latence et robustesse ;
- la lecture d'ecran / OCR / overlay peut etre fragile ;
- l'analyse postflop avancee peut vite devenir un gros projet ;
- l'absence d'historique complet dans le MVP oblige a bien penser les agregations.

### Produit

- trop de perimetre au debut risque de ralentir tout ;
- une aide a la decision peu explicable serait difficile a faire confiance ;
- l'ambition live + HUD + recommandation + profiling est deja un gros produit ;
- il faudra ordonner les livrables par couches.

## Architecture cible envisageable

Si on part plus tard en implementation, une separation simple serait :

- `core/` : modeles de donnees poker, parsing, calculs ;
- `ingestion/` : import Winamax, surveillance dossier ;
- `analytics/` : stats, agregations, leaks ;
- `advice/` : moteur de recommandations ;
- `storage/` : base locale SQLite ;
- `capture/` : lecture d'ecran, OCR, detection de contexte ;
- `ui/` : interface desktop et HUD overlay.

## Choix techniques a trancher plus tard

- stack desktop Python precise ;
- SQLite seule au debut ou base plus evolutive ;
- moteur de regles simple ou IA / modeles plus tard ;
- bibliotheques poker existantes a reutiliser ou parser maison ;
- application offline uniquement ou synchronisation cloud.

## Questions encore ouvertes pour la prochaine iteration

1. A quel emplacement exact Winamax ecrit les hand histories sur ta machine ?
2. Le HUD doit-il etre discret ou tres riche visuellement ?
3. Quel niveau de latence est acceptable pour une recommandation live ?
4. Quels spots doivent etre couverts en premier : preflop seulement ou aussi postflop ?
5. Quelles stats HUD sont indispensables sur la premiere version ?
6. Quel style de recommandation veux-tu voir en priorite : action unique, options classees, ou commentaire strategique ?
7. Jusqu'ou veux-tu aller dans l'analyse adversaire avec peu d'echantillons ?
8. Quelle stack desktop Python on privilegie plus tard ?

## Proposition de prochaine etape

Une fois tes reponses recues, on pourra produire :

- une specification fonctionnelle v1 detaillee ;
- un decoupage en phases realistes ;
- les user stories prioritaires ;
- une architecture detaillee sans encore coder.
