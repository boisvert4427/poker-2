# Suivi des corrections live et strategie

Etat au 24 septembre 2026. Ce document complete l'[ordre de marche](decision-engine-roadmap.md).
Il ne certifie ni une strategie optimale, ni une precision OCR de 100 %.

## 1. Ranges : distinguer relanceur et payeur

Dans `src/poker_tracker/decision_support.py`, `_effective_villain_range` :

- l'action est rattachee au nom normalise complet du joueur, pas a une
  sous-chaine : Ann ne doit pas heriter des actions d'Anna ;
- la derniere action explicite reconnue est prioritaire sur l'indicateur
  d'agression deduit des mises visibles ;
- `calls ... all-in` est un call, pas une relance ;
- un call recent n'est plus masque par une ancienne relance du meme joueur.

Dans `src/poker_tracker/live_state.py`, `_aggressive_villain_seats` : plusieurs
joueurs au meme montant maximal ne sont plus tous classes relanceurs.
Une mise maximale unique reste un indice, pas une preuve de la sequence.

La range choisie depend toujours des branches existantes : participation,
raise preflop, limp, call ou bet postflop et profil adverse. Cette correction
evite surtout de choisir la mauvaise branche ; elle n'ajoute pas de solveur.

### Validation

`tests/test_range_action_identity.py` couvre cinq cas : call mal classe comme
agression, call all-in, call apres raise, collision de noms et mises ex aequo.
La suite complete compte 106 tests passes lors de la derniere execution.

Sur les donnees enregistrees de `sessions/20260924_205715`, neuf cas joueur/frame
conservent leur classification call meme en forcant l'indicateur d'agression.
C'est une verification de branche sur des actions enregistrees, pas neuf
decisions prouvees mauvaises auparavant, ni un taux de precision strategique.

### Limites

- Les actions textuelles recentes peuvent couvrir plusieurs streets : il reste
  a exploiter leur version structuree pour isoler le contexte exact.
- Selectionner une range de profil n'est pas reponderer progressivement toutes
  ses combinaisons selon board, sizing et sequence d'actions.
- La normalisation de noms ici ne garantit pas la resolution des erreurs OCR.
- L'EV de toutes les actions et tailles de mise n'est pas exhaustivement comparee.

## 2. Reprises live et memoire de main

Dans `src/poker_tracker/app.py` :

- `_snapshot_needs_retry` identifie les etats sans conseil exploitable ; une
  signature visuelle identique ne doit pas figer un etat `ATTENDRE` ;
- `_live_tick` ne doit pas emprunter le traitement de disparition du tour tant
  que le signal rapide indique encore que hero doit jouer ;
- seules deux cartes hero completes peuvent etre reutilisees ; un board
  incomplet/invalide ne doit pas etre considere comme deja resolu ;
- `_stabilize_board_cards` ne restaure pas un ancien rang sans couleur a la
  place d'une carte complete nouvellement lue.

Les tests de `tests/test_live_board_stability.py` verifient notamment la remise
en file de l'OCR apres un blocage et la conservation de la carte complete.
Ce sont des tests de controle de flux, pas une preuve de disparition de tous
les blocages pendant une nouvelle session reelle.

## 3. Montant a payer

`src/poker_tracker/live_state.py` exploite d'abord le texte du bouton central.
Si CALL est identifie sans montant fiable, `read_call_amount_retry` dans
`src/poker_tracker/ocr.py` relit la partie haute du bouton : 58 % de sa hauteur,
agrandissement, contraste et OCR numerique. Une seconde variante utilise le
bouton complet. Le texte de reprise est expose dans `call_retry_text`.

Cette reprise est conditionnee au contexte CALL ; elle ne doit pas transformer
un nombre quelconque de l'image en montant a payer. Les cas reels 8 BB et
6 BB de la session du 24 septembre sont redevenus lisibles.

## 4. Explication et cartes bloquees par hero

`DecisionRecommendation.explanation` et `_decision_explanation` dans
`decision_support.py` fournissent une phrase affichable avec le conseil.
Elle reprend notamment equite, cote du pot et certaines probabilites adverses.
L'explication CALL/FOLD accompagne la regle existante de marge de deux points
d'equite ; cette marge est heuristique, pas une garantie de rentabilite.

Les blockers etaient deja pris en compte dans `src/poker_tracker/equity.py` :
`range_hand_distribution` exclut les cartes de hero et du board ;
`multiway_hand_distributions` exclut aussi les chevauchements entre adversaires.
Un test verifie que posseder un as reduit les combinaisons adverses donnant
top paire sur un flop hauteur as. Cela ne rend pas les ranges supposees exactes.

Limite : la phrase mathematique doit encore etre mieux conditionnee a la
fiabilite des montants ; elle ne suffit pas a prouver la qualite du conseil.

## 5. Mesures sur les sessions

### Session 20260924_205715

- 91 captures, 41 mains distinctes rattachees a l'historique.
- 26 recommandations `ATTENDRE` dans les enregistrements initiaux.
- Rejeu cible de ces 26 cas : neuf blocages, puis sept apres les deux
  corrections supplementaires de lecture du montant CALL.
- Le fichier `data/session_audits/20260924_205715_wait_replay.json` conserve
  l'etape intermediaire a neuf. Le resultat a sept vient du retest terminal ;
  ce fichier n'est donc pas un rapport final a sept.

Les cas restants incluent distribution/animation, cartes teintees ou
incompletes et une capture hors tour hero. Ne pas supprimer les controles de
coherence pour afficher artificiellement zero `ATTENDRE` : il faut obtenir une
nouvelle capture exploitable. La reussite de cette reprise reste a mesurer en live.

### Session 20260922_205456

Rejeu independant de 110 captures : 32 blocages initiaux contre 11 apres rejeu,
21 resolus, aucun nouveau blocage dans ce test. OCR complet moyen : 4,77 s.
Rapport : `data/session_audits/20260922_205456_retry_replay/summary.json`.

Ce temps n'est pas celui de la boucle live avec caches. Le rejeu independant
n'utilise pas toute sa memoire temporelle et peut employer les profils actuels.
Un conseil different n'est pas necessairement un meilleur conseil.

## 6. Reproduire et poursuivre

Depuis la racine du projet, sous PowerShell :

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -q
```

Le script `scripts/replay_live_audit.py` sert aux relectures hors ligne.
Attention : il reprend les resultats existants par nom de capture, sans
empreinte du code. Un rapport reutilise ne prouve donc pas une execution du
nouveau code ; utiliser une sortie vierge apres avoir preserve l'ancien rapport.

Ordre de suite, sans declarer les etapes terminees :

1. Verifier en nouvelle session que les reprises debloquent effectivement le
   conseil, et mesurer latence, donnees manquantes et erreurs de lecture.
2. Confronter les actions reconstruites a l'historique une fois la main terminee.
3. Affiner les ranges par street/action/sizing avec tests de non-regression.
4. Comparer ensuite les choix strategiques et leurs hypotheses d'EV.

L'historique de fin de main sert a la verification retrospective ; ses actions
futures ne doivent pas etre injectees dans une decision live rejouee.
Ni le profit d'une main ni son resultat au showdown ne suffisent a valider un conseil.

## Complement du 29 septembre 2026

Session `20260929_203255` : 73 captures, 68 rattachees a 22 mains,
20 ATTENDRE dont 15 mentionnent un montant call/pot non fiable.
Temps enregistre moyen 4,05 s, maximum 7,91 s. Ces nombres sont anterieurs
aux corrections ci-dessous.

- Reprise CALL : conserver les lettres BB et exiger l'unite avant d'accepter
  le montant. Le filtre numerique seul transformait 4 BB en 46. Six captures
  de cette session donnent maintenant 4, 2, 2, 2, 18 et 4 BB lors du test cible.
- Libelles adverses : masque jaune/orange et deplacement vertical des crops
  lateraux de 8 pixels a hauteur 1048 (proportionnel a la resolution).
  La capture 20-36-04-567 donne maintenant FOLD et BETS 4 BB.
- Un libelle FOLD exact sans cartes visibles est exploitable meme sans nom
  lisible ; un nom contenu dans celui d'un autre joueur ne suffit plus.
- Une contribution preflop de 1 BB n'est plus inferree comme une relance.
  Une mise postflop de 1 BB reste eligible a l'inference d'agression.
- L'explication nomme le joueur dont elle cite la distribution individuelle
  et distingue explicitement la ligne conjointe multiway. Les probabilites
  individuelles ne sont pas additionnees pour inventer une probabilite collective.

Validation : 111 tests passes, dont les nouvelles regressions dans
`tests/test_session_0929_fixes.py` et `tests/test_range_action_identity.py`.
Pas encore de rejeu sequentiel complet ni de nouvelle validation live ; ne pas
assimiler ces tests cibles a la resolution de tous les ATTENDRE de la session.

### Rejeu complet du 30 septembre

Les 73 captures ont maintenant ete rejouees avec le script, sans reutiliser
de rapport existant et sans injecter l'historique futur dans la reconnaissance.
Rapport : `data/session_audits/20260929_203255_retry_replay/summary.json`.

- ATTENDRE : 20 auparavant, 5 au rejeu ; 15 resolus, aucun nouveau blocage.
- Restants : quatre boards incomplets et une capture avec cartes hero/joueurs
  incertains. La capture 20-35-31-880 montre une carte encore teintee en animation.
- Temps moyen OCR complet + analyse : 4,21 s ; ce n'est pas la latence du live
  optimise avec memoire. Aucun gain de vitesse n'est revendique ici.
- Les changements FOLD/CALL ne constituent pas une preuve de meilleure strategie :
  les profils et le contexte temporel peuvent differer des enregistrements.

Correction supplementaire dans `app.py`, `_stabilize_players_in_hand` :
les folds explicites sont memorises des la premiere observation d'une nouvelle
main, sans retour anticipe qui les ignorait. Un test sequentiel verifie qu'une
observation bruitee suivante ne reactive pas le joueur couche.
Cette correction de memoire est couverte par le test, pas par le rejeu independant.
Suite complete : 112 tests passes.

### Captures pendant les animations : prevention avant OCR

`capture_has_card_animation` dans `local_snapshot_analysis.py` examine les
fonds colores des crops de valeurs hero/board. Il ne devine aucune carte.
Dans `_live_tick`, ce signal pendant le tour hero reporte l'OCR complet,
masque l'ancien conseil sur la table et programme une nouvelle capture.
`_defer_card_animation` borne ce report a une seconde par signal continu ;
ensuite l'OCR et ses garde-fous habituels reprennent. La cadence effective
inclut aussi le temps du scan rapide, pas seulement les 200 ms programmes.

Verification hors ligne : les cinq images encore bloquees sont signalees,
ainsi qu'une sixieme image teintee (20-44-52-079). La capture archivee suivante
de chacun des cinq cas n'est plus signalee, mais les archives espacees ne
prouvent pas qu'une nouvelle image sera stable en moins d'une seconde.
Controle des 73 images : 1,75 s au total, environ 24 ms/image avec ouverture PNG.

114 tests passent : report avant OCR, absence de lancement pendant ce report,
masquage du conseil, borne temporelle, reinitialisation du signal et exclusion
des fonds blancs/slots verts sombres. Aucun taux zero ATTENDRE n'est revendique :
le rejeu fixe conserve ses cinq blocages ; cette correction vise la capture live
avant analyse et doit encore etre validee dans une nouvelle session.

### Actions et joueurs actifs : separation des phases

Le worker live transmet maintenant les evenements structures a
`build_live_snapshot`. `_actions_for_street` filtre la pression courante par
street : une mise du flop ne devient pas une mise de turn. La liste complete
reste disponible dans `local_action_events`, sans lecture d'actions futures.
Les anciens appels sans evenements structures gardent leur interface textuelle.

La reconstruction conserve les contributions d'un joueur couche dans l'etat
des mises, mais ne les emet plus comme un nouveau bet/call quand un libelle
FOLD est present sans cartes visibles. Un libelle FOLD contredit par des dos
de cartes visibles n'est pas confirme.

Sur les JSON de la session du 29 septembre : trois captures possedent des
evenements de streets anterieures ; six occurrences joueur/capture associent
un fold reconstruit a une mise toujours visible. Ce sont des cas de contexte,
pas six decisions prouvees erronees ni six mains distinctes.

118 tests passent, dont `tests/test_action_street_context.py`. Limite importante :
le filtrage des actions ne constitue pas encore une range cumulative. Sans action
sur la nouvelle street, la branche de participation peut encore etre utilisee ;
il reste a propager les contraintes des streets precedentes plutot que pretendre
que le seul filtrage realise cette inference. Aucun changement des statistiques
BDD, des pots annexes ou des sizings dans cette correction.

### Ranges cumulatives : premiere version heuristique

`decision_support._cumulative_villain_range` utilise le journal structure
de la main, transmis aux deux chemins de calcul de conseil dans `live_state`.
Chaque bet/raise/call du siege concerne fournit un filtre provenant des regles
de profil existantes. La premiere action initialise la range ; les suivantes
conservent l'intersection des classes de mains via `equity.intersect_range_texts`.
Un check ne reinitialise pas cette hypothese. Les filtres vides/incompatibles
sont signales dans la raison et la derniere range valide est conservee.

Les evenements d'autres sieges, de streets futures ou de confiance inferieure
a 0,8 ne sont pas appliques. Sans journal exploitable, les regles precedentes
restent utilisees. Le journal est celui de la main courante, pas celui des
historiques futurs. Les blockers hero/board restent appliques au calcul d'equite.

Validation : 125 tests passes, notamment raise puis check, raise puis call,
nouvelle main, actions futures/autres sieges, confiance faible, intersections
suited/offsuit et repetitions. Sur les JSON de la session du 29 septembre,
124 contextes joueur actif/capture parcourus, dont 20 avec cumul ; parcours et
calcul des ranges seuls en 0,031 s, sans OCR ni simulation d'equite.
Ce chiffre n'est ni une latence live complete ni une mesure de qualite strategique.

Limites : intersections rigides de ranges heuristiques, pas de probabilites
par combinaison ni de ponderation selon sizing/texture. Un filtre de profil
peut exclure a tort un draw ou un bluff ; ce modele ne doit donc pas etre
presente comme une range certaine ou optimale. La validation strategique en
live et l'affinement par texture/sizing restent a faire.

### Filtre postflop sensible au board

`equity.filter_range_on_board` remplace l'intersection generique postflop :
une classe deja dans la range precedente est conservee si elle correspond au
filtre de profil OU possede une combinaison compatible donnant une paire,
une main faite forte, un tirage couleur ou un tirage quinte. Les tirages ne
sont actifs qu'au flop/turn. Les cartes hero et board sont exclues des combos.
Pour une action ancienne, seul le prefixe du board de cette street est utilise.

Un brelan de 2 ou un tirage 65s sur 782 ne sont donc plus supprimes uniquement
par un filtre generique premium. Aucune classe absente de la range precedente
n'est ajoutee. Sans journal exploitable, le filtre peut partir de la range
de participation du profil. Cache borne a 256 resultats pour limiter le cout.

Limites : representation par classes (par exemple QJs), pas par combinaisons
ponderees ; une seule combinaison de tirage conserve toute sa classe. C'est
une precaution contre les exclusions abusives, pas une probabilite de call,
bet ou bluff. Les petites paires peuvent rester dans la range sans certitude
qu'elles poursuivent contre une grosse mise. Les sizings historiques ne sont
pas exploites faute de pot avant action systematiquement fiable.

129 tests passent. Parcours des 124 contextes joueur/capture de la session :
0,111 s pour lecture JSON et calcul des ranges seuls, sans OCR/equite.
Pas de preuve de gain de rentabilite ni de validation live complete a ce stade.

### Optimisation du filtre de ranges

Le filtre cesse d'evaluer les autres combinaisons d'une classe deja retenue.
Il accepte directement les classes presentes dans le filtre candidat ou ayant
une paire, et precalcule les fenetres de quinte. Le cache reste borne a 256.
Aucune regle strategique ni aucun nombre de simulations d'equite ne change.

`tests/test_range_filter_optimization.py` conserve une reference lente et compare
les sorties sur 36 scenarios deterministes flop/turn/river, cache desactive.
131 tests passent. Trois passages du lot : mediane 0,446 s avant, 0,364 s apres,
soit environ 18 % de reduction du temps de ce filtre. Cette mesure locale ne
represente pas un gain equivalent sur l'OCR ou la boucle live complete.

## Support separe des tables 3-max et 5-max

Ajout le 5 octobre 2026 a partir de la session `20261005_172831` (Space KO).
Le 3-max n'ecrase pas `config/calibration.json` et ne modifie pas les crops
5-max. `config.py` expose deux profils :

- `5max` : calibration historique du projet, comportement par defaut ;
- `3max` : substitutions limitees aux deux familles adverses `top_left` et
  `top_right`, plus leurs zones dealer. Board, hero, pot et boutons restent
  communs.

Le profil est choisi sur chaque image par la geometrie des libelles adverses.
En cas d'image absente ou illisible, le repli est `5max`. L'OCR 3-max ne lance
plus les zones `left` et `right`, qui n'existent pas sur ce layout. Le profil
selectionne est stocke dans `OcrSnapshot.calibration_profile` puis dans
`detected_fields.table_layout`.

La logique de table est egalement separee :

- ordre 3-max : `top_left`, `top_right`, `hero` ;
- positions 3-max : BTN, SB, BB ;
- mapping des noms depuis l'historique adapte au nombre reel de sieges ;
- reconstruction des actions triee selon le layout ;
- base preflop 3-max distincte pour les opens BTN/SB et defense contre les
  relances, sans remplacer la base 5-max.

Verification : 49 captures de table de la session sont classees 3-max ; une
capture montrant le bureau Windows reste classee 5-max. Les 73 captures de la
session 5-max du 29 septembre et les 97 du 1er octobre restent toutes classees
5-max. Sur dix captures 3-max testees, les positions stables donnent notamment
`Len62`, `Gambas-51148`, `miguel1 40799`, `TR33B34RD`, leurs stacks, les cartes
hero et les trois positions du dealer. Deux captures de transition ont encore
un nom ou stack incomplet ; la memoire live doit les stabiliser sur la capture
suivante.

137 tests passent, dont isolation des calibrations, absence des sieges lateraux
en 3-max, positions, mapping historique, detection sur captures reelles et
separation de la base preflop. Limites : uniquement les layouts fixes 3-max et
5-max en plein ecran testes ; pas encore de 6-max, redimensionnement libre ou
multitable avec plusieurs geometries simultanees. La strategie 3-max reste une
base heuristique, pas une solution GTO specifique aux tournois Space KO/antes.
