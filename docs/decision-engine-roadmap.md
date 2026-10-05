# Ordre de marche du moteur de decision 5-max

Ce document est la reference persistante du projet. Les etapes sont traitees
dans cet ordre et chacune doit etre testee avant de passer a la suivante.

Suivi detaille : [corrections et validations du 24 septembre 2026](live-decision-validation.md).

1. **Fiabiliser le GameState et bloquer les conseils incoherents** *(en cours)*
   - verifier cartes hero, board, street, position, adversaires actifs et montants ;
   - afficher `ATTENDRE` si une donnee critique manque ou se contredit ;
   - conserver la raison precise du blocage pour le debug live.
   - fait : garde-fou central et diagnostic dans les donnees live ;
   - fait : couleur du rang prioritaire pour le board ;
   - fait : une carte masquee par une teinte uniforme reste incertaine au lieu
     de recevoir une fausse couleur.
2. **Reconstruire exactement la sequence d'actions et les positions** *(en cours)*
   - ordre de parole, limps, raises, calls, folds, all-in et changement de street.
   - fait : memoire cumulative des contributions separee par street ;
   - fait : distinction bet/call/raise selon le montant a egaler ;
   - fait : tri des actions selon l'ordre de parole 5-max ;
   - fait : conservation et inference prudente des gros all-in a stack disparu.
   - regression : 82 actions reconstruites sur trois sessions exploitables ;
     aucune erreur de cartes hero dans les audits relies a l'historique ;
   - rejet valide : ne pas inferer CHECK depuis la seule absence de mise ; les
     anciennes sessions prouvent que cela produit de faux checks quand un crop
     de bet est manque ;
   - restant : confirmer checks/folds par un second signal (variation du pot,
     boutons ou historique), puis comparer automatiquement chaque evenement
     live a la ligne Winamax.
   - fait : les actions nouvellement reconstruites sont reinjectees dans la
     frame courante et le conseil est recalcule avant affichage ;
   - fait : une hausse du pot sans action lisible produit `ACTION INCERTAINE`
     et bloque le conseil au lieu d'inventer un check ; controle retrospectif
     sur trois sessions : 13 anomalies signalees.
   - fait : le filtre de mise accepte maintenant le texte jaune meme lorsque
     le jeton orange est hors du crop ; le cas reel `29,5 BB` est recupere ;
   - mesure : sur les 13 anciennes anomalies, deux montants redeviennent
     lisibles avec le filtre corrige. Les autres captures ne contiennent deja
     plus le montant (jetons collectes/animation) et restent bloquees plutot
     que transformees en faux checks.
   - fait : detection des montants jaunes assombris par les anciens overlays,
     marge OCR de secours et variante Tesseract `BEB` ; validation reelle de
     `12,5 BB`, `29,5 BB` et `2,5 BB` sans regression.
   - constat : plusieurs ecarts de pot etaient des changements de street dont
     la nouvelle carte avait ete ratee, et non des mises disparues.
   - fait : `board_visible_count` compte physiquement les cartes sans lire
     leur valeur ; la street avance meme si un rang reste illisible, et le
     conseil attend tant que le board complet n'est pas fiable.
   - fait : quatre zones d'action adverses lisent les libelles sous les stacks ;
     `RAISES TO` peut fournir le montant et `FOLD/CHECK` sont memorises ;
   - securite : un fold OCR approximatif n'est accepte que si les cartes du
     siege sont egalement absentes ; test reel reconstruit `raise 29,5 BB`
     puis `fold` dans le bon ordre ; OCR complet mesure a environ 3,6 s.
   - regression ancienne : les zones retrouvent aussi `12,5 BB`, `BETS 9 BB`,
     plusieurs `FOLD` et plusieurs `CHECK`; le texte parasite des anciens
     overlays est conserve comme bruit et n'est pas transforme en action sans
     mot-cle fiable.
   - fait : journal live structure (`street`, siege, joueur, action, montant,
     source, confiance) distinct des lignes venues de l'historique ;
   - fait : apres rattachement Winamax, comparaison automatique par joueur,
     street, type et montant avec statuts `match`, `amount_mismatch` et
     `not_found`, stockee dans `action_audit` du JSON de session.
3. **Construire des ranges contextuelles** *(en cours)*
   - position, action, sizing, profondeur, profil et nombre de joueurs.
   - fait : une action explicite call prime sur une inference de relance ;
     un call all-in reste un call ; identification exacte du nom normalise ;
   - fait : plusieurs mises maximales identiques ne designent plus plusieurs
     relanceurs ; la derniere action explicite du joueur est prioritaire ;
   - restant : exploiter la sequence structuree par street pour ponderer les
     combinaisons, pas seulement selectionner une range de profil.
4. **Completer la matrice preflop 5-max**
   - open, defense, iso, 3-bet, 4-bet et all-in selon les stacks effectifs.
5. **Comparer l'EV de toutes les actions legales**
   - fold, check, call, bet et raise, avec explication des hypotheses.
6. **Ameliorer l'analyse postflop**
   - force relative, texture, draws, blockers, nuts advantage et range advantage.
7. **Mettre a jour les ranges apres chaque action**
   - reduire ou ponderer la range de chaque joueur a chaque street.
   - correction partielle : un ancien raise ne masque plus un call subsequent ;
     cela ne constitue pas encore une mise a jour probabiliste cumulative.
   - ajoute : cumul heuristique des contraintes bet/raise/call du journal
     structure ; un check ne reinitialise plus la range. Les intersections
     incompatibles sont signalees et ignorees. Tests de non-regression passes ;
     ponderation par combinaison, sizing et texture encore a realiser.
8. **Rendre exacts stack effectif et calcul multiway**
   - pots annexes, all-in, adversaires eligibles et equity multiway.
9. **Comparer plusieurs sizings**
   - calculer l'EV de tailles candidates plutot que choisir une taille fixe.
10. **Ajouter les exploits avec prudence statistique**
    - ajustements selon VPIP/PFR/fold/call uniquement avec un echantillon suffisant.
11. **Evaluer hors ligne sur les sessions enregistrees**
    - rejouer les spots, comparer conseil/realite et mesurer les regressions.

## Regle de progression

Une etape n'est marquee terminee qu'apres tests automatises et verification sur
des captures reelles. Le code precedent n'est retire que lorsque son remplacement
est mesure comme au moins aussi fiable.

## Layouts pris en charge

- 5-max : profil historique conserve par defaut ;
- 3-max : profil de crops, sieges, positions et base preflop separe, selectionne
  automatiquement sur image ;
- restant : validation live d'une session 3-max complete, puis architecture
  multi-fenetres. Le support 3-max ne signifie pas encore multitable simultane.
